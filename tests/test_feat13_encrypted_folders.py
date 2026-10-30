"""FEAT-13: encrypted folders inside a share, with gocryptfs (a stand-in here)."""

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services import encrypted_folders as ef
from backend.services import encrypted_index as ei

KEY = "-".join(["0123abcd"] * 8)


class FakeGocryptfs:
    """Answers like gocryptfs -init and a mount; keeps track of what is open."""

    def __init__(self):
        self.mounted: set[str] = set()
        self.calls: list[list[str]] = []

    def run(self, args, password):
        self.calls.append(args)
        if "-init" in args:
            cipher = args[-1]
            with open(os.path.join(cipher, "gocryptfs.conf"), "w") as fh:
                fh.write(password)
            return 0, f"Your master key is:\n\n    {KEY}\n\nIf the gocryptfs.conf file becomes corrupted..."
        cipher, plain = args[-2], args[-1]
        with open(os.path.join(cipher, "gocryptfs.conf")) as fh:
            if fh.read() != password:
                return 12, "Password incorrect."
        self.mounted.add(plain)
        return 0, ""

    def fusermount(self, cmd, **kw):
        if cmd[0] == "fusermount3":
            if "busy" in cmd[-1]:
                return subprocess.CompletedProcess(cmd, 1, "", "Device or resource busy")
            self.mounted.discard(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def box(tmp_path, monkeypatch):
    family = tmp_path / "Family"
    family.mkdir()
    monkeypatch.setattr(ei, "SETTINGS_FILE", str(tmp_path / "encrypted_folders.json"))
    monkeypatch.setattr(ei, "ROOT", str(tmp_path / "encrypted"))
    fake = FakeGocryptfs()
    monkeypatch.setattr(ef, "_run", fake.run)
    monkeypatch.setattr(ef, "_mounted", lambda: set(fake.mounted))
    monkeypatch.setattr("backend.proc.run_bounded", fake.fusermount)
    from backend.hardware import pal_storage

    shares = [SimpleNamespace(name="Family", mountpoint=str(family))]
    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: SimpleNamespace(list_shares=lambda: shares))
    fake.family = family
    return fake


def test_make_lock_open_and_take_off(box):
    out = ef.create("Family", "Taxes", "correct horse battery staple")
    assert out == {"name": "Taxes", "path": ef.plain_path("Taxes"), "recovery_key": KEY}
    assert os.path.isfile(box.family / ".zettnas-encrypted" / "Taxes" / "gocryptfs.conf")
    assert ef.listing() == [
        {
            "name": "Taxes",
            "share": "Family",
            "path": ef.plain_path("Taxes"),
            "unlocked": True,
            "unlock_at_start": False,
            "created": ef.listing()[0]["created"],
        }
    ]
    assert "correct horse" not in Path(ei.SETTINGS_FILE).read_text()  # the password is not kept

    ef.lock("Taxes")
    assert not ef.is_unlocked("Taxes")
    with pytest.raises(ef.EncryptedFolderError, match="wrong"):
        ef.unlock("Taxes", "not the password at all")
    ef.unlock("Taxes", "correct horse battery staple")
    assert ef.is_unlocked("Taxes")
    with pytest.raises(ValueError, match="Lock the folder first"):
        ef.forget("Taxes")
    ef.lock("Taxes")
    assert ef.forget("Taxes") == {"name": "Taxes", "forgotten": True}
    assert ef.listing() == []
    # the encrypted files stay, and can be added back with the password
    assert ef.adopt("Family", "Taxes", "correct horse battery staple")["name"] == "Taxes"
    assert ef.is_unlocked("Taxes")


def test_what_is_refused(box):
    with pytest.raises(ValueError, match="48 letters"):
        ef.create("Family", "../etc", "correct horse battery staple")
    with pytest.raises(ValueError):
        ef.create("Family", "Taxes", "password")  # a common password
    with pytest.raises(ValueError, match="no share called"):
        ef.create("Nowhere", "Taxes", "correct horse battery staple")
    ef.create("Family", "Taxes", "correct horse battery staple")
    with pytest.raises(ValueError, match="already an encrypted folder"):
        ef.create("Family", "Taxes", "correct horse battery staple")
    with pytest.raises(ValueError, match="no encrypted folder called"):
        ef.adopt("Family", "Other", "correct horse battery staple")
    for fn, args in ((ef.unlock, ("Nope", "x")), (ef.lock, ("Nope",)), (ef.forget, ("Nope",))):
        with pytest.raises(KeyError):
            fn(*args)


def test_a_busy_folder_stays_open(box, monkeypatch):
    ef.create("Family", "busy", "correct horse battery staple")
    with pytest.raises(ef.EncryptedFolderError, match="still has a file open"):
        ef.lock("busy")


def test_kept_password_opens_it_at_start(box):
    from backend import secret_box

    ef.create("Family", "Photos", "correct horse battery staple", unlock_at_start=True)
    kept = ef._settings()["folders"]["Photos"]["password"]
    assert secret_box.is_sealed(kept) and secret_box.unseal(kept) == "correct horse battery staple"
    ef.lock("Photos")
    assert ef.unlock_at_start() == 1 and ef.is_unlocked("Photos")
    assert ef.unlock_at_start() == 0  # already open
    assert ef.reseal() == 1

    ef.set_unlock_at_start("Photos", None)
    assert ef.listing()[0]["unlock_at_start"] is False
    # turning it on again checks the password with a read-only second view
    with pytest.raises(ef.EncryptedFolderError, match="wrong"):
        ef.set_unlock_at_start("Photos", "a wrong password here")
    assert ef.set_unlock_at_start("Photos", "correct horse battery staple") == {
        "name": "Photos",
        "unlock_at_start": True,
    }
    assert any("-ro" in c for c in box.calls)
    ef.lock("Photos")
    ef.set_unlock_at_start("Photos", None)
    ef.set_unlock_at_start("Photos", "correct horse battery staple")  # locked: opening it is the check
    assert ef.is_unlocked("Photos")


def test_a_broken_kept_password_is_logged_not_raised(box):
    ef.create("Family", "Old", "correct horse battery staple", unlock_at_start=True)
    ef.lock("Old")
    s = ef._settings()
    from backend import secret_box

    s["folders"]["Old"]["password"] = secret_box.seal("something else entirely")
    from backend.fsutil import atomic_write_json

    atomic_write_json(ei.SETTINGS_FILE, s)
    assert ef.unlock_at_start() == 0


def test_no_gocryptfs_says_so(monkeypatch):
    monkeypatch.setattr(ef, "tool", lambda: None)
    with pytest.raises(ef.EncryptedFolderError, match="no gocryptfs"):
        ef._run(["-init"], "pw")


def test_the_password_goes_in_on_stdin(monkeypatch):
    seen = {}

    def fake(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, "out", "")

    monkeypatch.setattr(ef, "tool", lambda: "/usr/bin/gocryptfs")
    monkeypatch.setattr("backend.proc.run_bounded", fake)
    assert ef._run(["-q", "/c", "/p"], "s3cret") == (0, "out")
    assert seen["input"] == "s3cret\n" and "s3cret" not in " ".join(seen["cmd"])


def test_mounts_are_read_from_the_kernel(tmp_path, monkeypatch):
    mounts = tmp_path / "mounts"
    mounts.write_text("/dev/sda1 / ext4 rw 0 0\n/c /mnt/encrypted/My\\040Taxes fuse.gocryptfs rw 0 0\n")
    real_open = open
    monkeypatch.setattr(
        "builtins.open", lambda p, *a, **k: real_open(mounts if p == "/proc/self/mounts" else p, *a, **k)
    )
    assert ef._mounted() == {"/mnt/encrypted/My Taxes"}


def test_deleted_files_stay_inside_the_encryption(box):
    from backend.services import recycle_bin

    inside = os.path.join(ei.ROOT, "Taxes", "2021", "return.pdf")
    assert recycle_bin.bin_for(inside) == os.path.join(ei.ROOT, "Taxes", ".RecycleBin")
    assert ef.bin_for(os.path.join(ei.ROOT, "Taxes")) is None  # the folder itself
    assert ef.bin_for(os.path.join(ei.ROOT, "Taxes", ".RecycleBin", "x")) is None
    assert ef.bin_for("/mnt/user/Family/x") is None


def test_access_follows_the_share(box, monkeypatch):
    from backend.services import share_access

    ef.create("Family", "Taxes", "correct horse battery staple")
    monkeypatch.setattr(
        share_access, "known_shares", lambda: [{"name": "Family", "path": str(box.family), "samba": {}}]
    )
    monkeypatch.setattr(share_access, "_user", lambda u: {"role_id": "share_user"})
    monkeypatch.setattr(share_access, "_home_for", lambda u, user: "")
    cfg = {
        "shares": {"Family": {"users": {"mia": "write", "leo": "read"}}},
        "role_defaults": {},
        "default_level": "none",
    }
    monkeypatch.setattr(share_access, "load_config", lambda: cfg)
    assert (ef.plain_path("Taxes"), "write") in share_access.grants_for("mia")
    assert (ef.plain_path("Taxes"), "read") in share_access.grants_for("leo")
    assert (ef.plain_path("Taxes"), "none") in share_access.grants_for("kid")


def test_api(client, auth_headers, box):
    got = client.get("/api/encrypted-folders", headers=auth_headers).json()
    assert got["folders"] == [] and "available" in got
    r = client.post(
        "/api/encrypted-folders",
        headers=auth_headers,
        json={"share": "Family", "name": "Taxes", "password": "correct horse battery staple"},
    )
    assert r.status_code == 200 and r.json()["recovery_key"] == KEY
    assert client.get("/api/encrypted-folders", headers=auth_headers).json()["folders"][0]["unlocked"] is True
    assert client.post("/api/encrypted-folders/Taxes/lock", headers=auth_headers).status_code == 200
    wrong = client.post("/api/encrypted-folders/Taxes/unlock", headers=auth_headers, json={"password": "nope nope"})
    assert wrong.status_code == 409 and "wrong" in wrong.json()["detail"]
    assert wrong.json()["error"] == "wrong_password"  # not "conflict": its own words in every language (NUX-1)
    ok = client.post(
        "/api/encrypted-folders/Taxes/unlock", headers=auth_headers, json={"password": "correct horse battery staple"}
    )
    assert ok.status_code == 200
    assert client.post("/api/encrypted-folders/Nope/lock", headers=auth_headers).status_code == 404
    assert (
        client.post("/api/encrypted-folders/Nope/unlock", headers=auth_headers, json={"password": "x"}).status_code
        == 404
    )
    bad = client.post(
        "/api/encrypted-folders", headers=auth_headers, json={"share": "Family", "name": "x/y", "password": "pw"}
    )
    assert bad.status_code == 400
    kept = client.put("/api/encrypted-folders/Taxes/unlock-at-start", headers=auth_headers, json={"password": None})
    assert kept.status_code == 200 and kept.json()["unlock_at_start"] is False
    assert client.delete("/api/encrypted-folders/Taxes", headers=auth_headers).status_code == 400  # still open
    client.post("/api/encrypted-folders/Taxes/lock", headers=auth_headers)
    assert client.delete("/api/encrypted-folders/Taxes", headers=auth_headers).status_code == 200
    back = client.post(
        "/api/encrypted-folders/adopt",
        headers=auth_headers,
        json={"share": "Family", "name": "Taxes", "password": "correct horse battery staple"},
    )
    assert back.status_code == 200


def test_people_reach_only_folders_in_their_shares(box, monkeypatch):
    from backend.api import encrypted_folders as api

    ef.create("Family", "Taxes", "correct horse battery staple")
    monkeypatch.setattr("backend.services.app_catalog.share_mounts", lambda: {"Family": str(box.family)})
    levels = {"mia": "write", "leo": "read"}
    monkeypatch.setattr("backend.services.share_access.level_for", lambda u, p: levels.get(u, "none"))

    def who(name):
        return SimpleNamespace(username=name, has_scope=lambda s: False)

    assert api._can_use(who("mia"), "Family", True)
    assert api._can_use(who("leo"), "Family", False) and not api._can_use(who("leo"), "Family", True)
    assert not api._can_use(who("kid"), "Family", False)
    assert api._can_use(SimpleNamespace(username="admin", has_scope=lambda s: s == "*"), "Family", True)


# --- the audit's fixes (NREL-1 to NREL-4) -------------------------------------------------------


def test_the_recovery_key_is_read_over_two_lines(box, monkeypatch):
    two_lines = (
        "Your master key is:\n\n    0123abcd-0123abcd-0123abcd-0123abcd-\n    0123abcd-0123abcd-0123abcd-0123abcd\n"
    )

    def init_two_lines(args, password):
        if "-init" in args:
            box.run(args, password)
            assert "-q" not in args  # quiet would leave the key out
            return 0, two_lines
        return box.run(args, password)

    monkeypatch.setattr(ef, "_run", init_two_lines)
    assert ef.create("Family", "Keys", "correct horse battery staple")["recovery_key"] == KEY


def test_a_mount_does_not_keep_our_pipes(box):
    ef.create("Family", "Pipes", "correct horse battery staple")
    mounts = [c for c in box.calls if "-init" not in c]
    assert mounts and all("-nosyslog" not in c for c in mounts)


def test_a_locked_folder_leaves_nothing_to_write_into(box):
    ef.create("Family", "Taxes", "correct horse battery staple")
    assert os.path.isdir(ef.plain_path("Taxes"))
    ef.lock("Taxes")
    assert not os.path.exists(ef.plain_path("Taxes"))
    os.makedirs(ef.plain_path("Taxes"))  # left from before a restart
    assert ef.unlock_at_start() == 0 and not os.path.exists(ef.plain_path("Taxes"))


def test_paths_into_locked_folders_and_encrypted_files_are_refused(monkeypatch):
    from backend import fsutil

    monkeypatch.setattr(fsutil, "open_encrypted", lambda: {"/mnt/encrypted/Open"})
    assert fsutil.encrypted_refused("/mnt/encrypted/Locked/x.txt")
    assert fsutil.encrypted_refused("/mnt/encrypted/new-folder")
    assert not fsutil.encrypted_refused("/mnt/encrypted/Open/x.txt")
    assert not fsutil.encrypted_refused("/mnt/encrypted/Open")
    assert fsutil.encrypted_refused("/mnt/user/Family/.zettnas-encrypted/Taxes/gocryptfs.conf")
    assert not fsutil.encrypted_refused("/mnt/user/Family/Taxes.txt")
    assert fsutil.is_encrypted_mount("/mnt/encrypted/Open")
    assert not fsutil.is_encrypted_mount("/mnt/encrypted/Open/x.txt")
    assert not fsutil.is_encrypted_mount("/mnt/encrypted/Locked")


def test_resolve_within_applies_the_guard(tmp_path, monkeypatch):
    from backend import fsutil

    hidden = tmp_path / "Family" / ".zettnas-encrypted" / "Taxes"
    hidden.mkdir(parents=True)
    (tmp_path / "Family" / "ok.txt").write_text("x")
    monkeypatch.setattr(fsutil, "protected_dirs", lambda: [])
    assert fsutil.resolve_within(str(tmp_path / "Family" / "ok.txt"), [str(tmp_path)])
    assert fsutil.resolve_within(str(hidden), [str(tmp_path)]) is None


def test_an_open_folder_is_not_deleted_or_moved(monkeypatch):
    from fastapi import HTTPException

    from backend import fsutil
    from backend.services.path_access import refuse_encrypted_mount

    monkeypatch.setattr(fsutil, "open_encrypted", lambda: {"/mnt/encrypted/Open"})
    with pytest.raises(HTTPException) as e:
        refuse_encrypted_mount("/mnt/encrypted/Open")
    assert e.value.status_code == 400 and "Lock it" in e.value.detail
    refuse_encrypted_mount("/mnt/encrypted/Open/file.txt")  # files inside can go
    refuse_encrypted_mount("")


def test_the_kernel_mount_list_is_read(tmp_path, monkeypatch):
    from backend import fsutil

    mounts = tmp_path / "mounts"
    mounts.write_text("/c /mnt/encrypted/My\\040Taxes fuse.gocryptfs rw 0 0\n")
    real_open = open
    monkeypatch.setattr(
        "builtins.open", lambda p, *a, **k: real_open(mounts if p == "/proc/self/mounts" else p, *a, **k)
    )
    assert fsutil.open_encrypted() == {"/mnt/encrypted/My Taxes"}


def test_the_recovery_key_comes_from_xray_when_init_hides_it(box, monkeypatch):
    """gocryptfs -init prints "suppressing master key display" when not on a terminal (seen on the
    real binary): the key is read with gocryptfs-xray instead (NREL-1)."""
    import subprocess as sp

    def init_quiet(args, password):
        out = box.run(args, password)
        return (0, "Not running on a terminal, suppressing master key display") if "-init" in args else out

    monkeypatch.setattr(ef, "_run", init_quiet)
    monkeypatch.setattr(ef.shutil, "which", lambda name: "/usr/bin/" + name)
    seen = {}

    def xray(cmd, **kw):
        if cmd[0].endswith("gocryptfs-xray"):
            seen.update(cmd=cmd, input=kw.get("input"))
            return sp.CompletedProcess(cmd, 0, "0123abcd" * 8 + "\n", "")
        return box.fusermount(cmd, **kw)

    monkeypatch.setattr("backend.proc.run_bounded", xray)
    out = ef.create("Family", "Quiet", "correct horse battery staple")
    assert out["recovery_key"] == KEY
    assert seen["cmd"][1] == "-dumpmasterkey" and seen["input"] == "correct horse battery staple\n"
