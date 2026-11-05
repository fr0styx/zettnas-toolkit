"""NREL-7/NREL-5: a subvolume share is rolled back by a swap; a folder share can become a subvolume."""

import os
import shutil
import time

import pytest

from backend.fsutil import ENCRYPTED_HIDDEN
from backend.hardware.pal import generic_linux as gl
from backend.services import snapshot_service as snaps
from tests.test_b12a_snapshots_default import FakePal


def _btrfs(calls, fail=()):
    """A stand-in for the btrfs and cp commands, on plain folders."""

    def run(cmd):
        calls.append(cmd)
        if any(cmd[: len(f)] == list(f) for f in fail):
            return 1, "", "refused"
        if cmd[:3] == ["btrfs", "subvolume", "snapshot"]:
            shutil.copytree(cmd[3], cmd[4], symlinks=True)
        elif cmd[:3] == ["btrfs", "subvolume", "create"]:
            os.mkdir(cmd[3])
        elif cmd[:3] == ["btrfs", "subvolume", "delete"]:
            shutil.rmtree(cmd[3], ignore_errors=True)
        elif cmd[:3] == ["btrfs", "subvolume", "list"]:
            return 0, "", ""
        elif cmd[0] == "cp":
            src, dest = cmd[-2], cmd[-1]
            if src.endswith(os.sep + "."):
                shutil.copytree(src[:-2], dest, dirs_exist_ok=True, symlinks=True)
            elif os.path.isdir(src):
                shutil.copytree(src, dest, symlinks=True)
            else:
                shutil.copy2(src, dest)
        else:
            return 1, "", "unknown"
        return 0, "", ""

    return run


def _share(tmp_path):
    live, snap = tmp_path / "pool" / "photos", tmp_path / "pool" / "@snapshots" / "photos@auto-1"
    for d in (live / ".RecycleBin", live / ENCRYPTED_HIDDEN, snap / ".RecycleBin"):
        d.mkdir(parents=True)
    (live / "a.jpg").write_text("ransomware")
    (live / "new.jpg").write_text("added later")
    (live / ".RecycleBin" / "today.jpg").write_text("deleted today")
    (live / ENCRYPTED_HIDDEN / "cipher").write_text("encrypted now")
    (snap / "a.jpg").write_text("old a")
    (snap / ".RecycleBin" / "old.jpg").write_text("deleted long ago")
    return live, snap


def _leftovers(live):
    return [p for p in os.listdir(live.parent) if p.startswith("photos.")]


def test_the_snapshot_is_swapped_in_and_the_bin_and_encrypted_folders_stay(tmp_path, monkeypatch):
    live, snap = _share(tmp_path)
    a, calls = gl.GenericLinuxStorageAdapter(str(tmp_path / "pool")), []
    monkeypatch.setattr(a, "_run_cmd", _btrfs(calls))
    a.swap_in_snapshot(str(live), str(snap), snaps.KEEP_ON_ROLLBACK)
    assert (live / "a.jpg").read_text() == "old a" and not (live / "new.jpg").exists()
    assert (live / ".RecycleBin" / "today.jpg").exists() and not (live / ".RecycleBin" / "old.jpg").exists()
    assert (live / ENCRYPTED_HIDDEN / "cipher").read_text() == "encrypted now"
    assert _leftovers(live) == []


@pytest.mark.parametrize("fail", [("btrfs", "subvolume", "snapshot"), ("cp",)])
def test_a_failed_swap_leaves_the_share_as_it_was(tmp_path, monkeypatch, fail):
    live, snap = _share(tmp_path)
    a = gl.GenericLinuxStorageAdapter(str(tmp_path / "pool"))
    monkeypatch.setattr(a, "_run_cmd", _btrfs([], fail=[fail]))
    with pytest.raises(RuntimeError, match="nothing was changed"):
        a.swap_in_snapshot(str(live), str(snap), snaps.KEEP_ON_ROLLBACK)
    assert (live / "a.jpg").read_text() == "ransomware" and _leftovers(live) == []


def test_a_failed_rename_puts_the_share_back(tmp_path, monkeypatch):
    live, snap = _share(tmp_path)
    a = gl.GenericLinuxStorageAdapter(str(tmp_path / "pool"))
    monkeypatch.setattr(a, "_run_cmd", _btrfs([]))
    real = os.rename

    def rename(src, dst):
        if ".rollback-" in str(src):
            raise OSError("busy")
        real(src, dst)

    monkeypatch.setattr(gl.os, "rename", rename)
    with pytest.raises(OSError):
        a.swap_in_snapshot(str(live), str(snap), snaps.KEEP_ON_ROLLBACK)
    assert (live / "a.jpg").read_text() == "ransomware" and _leftovers(live) == []


def test_when_a_swap_is_possible(tmp_path, monkeypatch):
    a = gl.GenericLinuxStorageAdapter(str(tmp_path))
    monkeypatch.setattr(gl, "is_subvolume", lambda p: True)
    answers = {"out": "", "code": 0}
    monkeypatch.setattr(a, "_run_cmd", lambda cmd: (answers["code"], answers["out"], ""))
    assert a.can_swap_in(str(tmp_path), str(tmp_path))
    answers["out"] = "ID 260 gen 9 top level 5 path photos/homes"
    assert not a.can_swap_in(str(tmp_path), str(tmp_path))  # a nested subvolume: not in the snapshot
    answers.update(out="", code=1)
    assert not a.can_swap_in(str(tmp_path), str(tmp_path))  # can't tell: copy instead
    monkeypatch.setattr(gl, "is_subvolume", lambda p: False)
    assert not a.can_swap_in(str(tmp_path), str(tmp_path))
    assert gl.is_subvolume(str(tmp_path / "missing")) is False


def test_a_folder_share_becomes_a_subvolume(tmp_path, monkeypatch):
    share = tmp_path / "docs"
    (share / "sub").mkdir(parents=True)
    (share / "sub" / "f.txt").write_text("keep")
    a, calls = gl.GenericLinuxStorageAdapter(str(tmp_path)), []
    monkeypatch.setattr(a, "_run_cmd", _btrfs(calls))
    old = a.convert_to_subvolume(str(share))
    assert (share / "sub" / "f.txt").read_text() == "keep" and os.path.isdir(old)
    assert calls[0][:3] == ["btrfs", "subvolume", "create"]
    shutil.rmtree(old)
    monkeypatch.setattr(a, "_run_cmd", _btrfs([], fail=[("cp",)]))
    with pytest.raises(RuntimeError, match="nothing was changed"):
        a.convert_to_subvolume(str(share))
    assert sorted(os.listdir(tmp_path)) == ["docs"]
    monkeypatch.setattr(a, "_run_cmd", _btrfs([], fail=[("btrfs", "subvolume", "create")]))
    with pytest.raises(RuntimeError, match="nothing was changed"):
        a.convert_to_subvolume(str(share))


def test_a_failed_rename_leaves_the_folder(tmp_path, monkeypatch):
    share = tmp_path / "docs"
    share.mkdir()
    (share / "f.txt").write_text("keep")
    a = gl.GenericLinuxStorageAdapter(str(tmp_path))
    monkeypatch.setattr(a, "_run_cmd", _btrfs([]))
    real = os.rename

    def rename(src, dst):
        if ".subvolume-" in str(src):
            raise OSError("busy")
        real(src, dst)

    monkeypatch.setattr(gl.os, "rename", rename)
    with pytest.raises(OSError):
        a.convert_to_subvolume(str(share))
    assert (share / "f.txt").read_text() == "keep" and sorted(os.listdir(tmp_path)) == ["docs"]


def test_which_shares_can_be_converted(tmp_path, monkeypatch):
    a = gl.GenericLinuxStorageAdapter(str(tmp_path))
    monkeypatch.setattr(gl, "fs_of", lambda p: "btrfs")
    monkeypatch.setattr(gl, "is_subvolume", lambda p: False)
    monkeypatch.setattr(
        "backend.hardware.pal.base.storage_tools", lambda: {"btrfs": True, "zfs": False, "mdadm": False}
    )
    assert a.can_convert(str(tmp_path))
    monkeypatch.setattr(gl, "is_subvolume", lambda p: True)
    assert not a.can_convert(str(tmp_path))
    assert not a.can_convert(str(tmp_path / "missing"))


class SwapPal(FakePal):
    def __init__(self, tmp_path, swap=True):
        super().__init__(tmp_path)
        self.swap, self.swapped, self.converted = swap, [], []

    def can_swap_in(self, live, snap):
        return self.swap

    def swap_in_snapshot(self, live, snap, keep):
        self.swapped.append((live, snap, keep))

    def can_convert(self, path):
        return not self.converted

    def convert_to_subvolume(self, path):
        old = path + ".before-subvolume-x"
        os.mkdir(old)
        self.converted.append(path)
        return old


@pytest.fixture
def pal(tmp_path, monkeypatch):
    p = SwapPal(tmp_path)
    monkeypatch.setattr(snaps, "_pal", lambda: p)
    monkeypatch.setattr(snaps, "SCHEDULES_FILE", str(tmp_path / "schedules.json"))
    monkeypatch.setattr(snaps, "_set_previous_versions", lambda share, on: None)
    monkeypatch.setattr("backend.services.encrypted_folders.listing", lambda: [])
    return p


def test_rollback_swaps_when_it_can_and_needs_no_room(pal, monkeypatch):
    (pal.live / "a.jpg").write_text("old")
    pal.create_snapshot("tank", "photos", "photos@auto-1")

    class Usage:
        free = 0

    monkeypatch.setattr(snaps.shutil, "disk_usage", lambda p: Usage)
    res = snaps.rollback("photos@auto-1", pal=pal, pool_id="tank", background=True)
    assert res["method"] == "swap" and "job_id" not in res and pal.swapped[0][2] == snaps.KEEP_ON_ROLLBACK
    assert res["safety_snapshot"] in pal.created  # the state before is still kept first


def _wait(job_id):
    from backend.services.jobs import job_manager

    for _ in range(200):
        done = [j for j in job_manager.list(everyone=True)["history"] if j["id"] == job_id]
        if done:
            return done[0]
        time.sleep(0.02)
    return None


def test_a_scheduled_folder_share_is_offered_and_converted(pal, monkeypatch):
    monkeypatch.setattr(snaps, "list_schedules", lambda: [{"share": "photos"}, {"share": "gone"}])
    assert snaps.convertible(pal) == ["photos"]
    res = snaps.convert("photos", pal=pal, owner="ana")
    job = _wait(res["job_id"])
    assert job and job["status"] == "done" and job["title_id"] == "jobs.t.convert"
    assert pal.converted == [str(pal.live.resolve())] and not os.path.exists(pal.converted[0] + ".before-subvolume-x")
    with pytest.raises(ValueError):
        snaps.convert("photos", pal=pal)  # a subvolume now
    assert snaps.convertible(FakePal.__new__(FakePal)) == []


def test_converting_refuses_with_an_encrypted_folder_open_and_reports_failures(pal, monkeypatch):
    monkeypatch.setattr(
        "backend.services.encrypted_folders.listing", lambda: [{"name": "Tax", "share": "photos", "unlocked": True}]
    )
    with pytest.raises(RuntimeError, match="Lock the encrypted folders"):
        snaps.convert("photos", pal=pal)
    monkeypatch.setattr("backend.services.encrypted_folders.listing", lambda: [])

    def boom(path):
        raise RuntimeError("The files could not be copied over (no space); nothing was changed.")

    monkeypatch.setattr(pal, "convert_to_subvolume", boom)
    job = _wait(snaps.convert("photos", pal=pal)["job_id"])
    assert job["status"] == "error" and "no space" in job["error"]


def test_the_api(client, auth_headers, monkeypatch):
    monkeypatch.setattr(snaps, "convertible", lambda pal=None: ["photos"])
    assert client.get("/api/snapshots/schedules", headers=auth_headers).json()["convertible"] == ["photos"]

    def raise_(exc):
        def f(share, **kw):
            raise exc

        return f

    for exc, code in ((FileNotFoundError("gone"), 404), (ValueError("no"), 400), (RuntimeError("open"), 409)):
        monkeypatch.setattr(snaps, "convert", raise_(exc))
        assert client.post("/api/snapshots/shares/photos/convert", headers=auth_headers).status_code == code
    monkeypatch.setattr(snaps, "convert", lambda share, **kw: {"share": share, "job_id": "job:1"})
    assert client.post("/api/snapshots/shares/photos/convert", headers=auth_headers).json()["job_id"] == "job:1"


@pytest.mark.real_confirmations
def test_converting_asks_first(client, auth_headers):
    res = client.post("/api/snapshots/shares/photos/convert", headers=auth_headers)
    assert res.status_code == 428 and res.json()["action"] == "share.make_subvolume"


# --- found by the round trip on real pools (scripts/hardware_snapshots.py) ---------------------
def test_a_subvolume_is_not_taken_for_a_mount_point(tmp_path, monkeypatch):
    mounts = tmp_path / "mounts"
    mounts.write_text(f"/dev/nvme0n1p1 {tmp_path} btrfs rw 0 0\n")
    assert gl.is_mount_point(str(tmp_path), str(mounts))
    assert not gl.is_mount_point(str(tmp_path / "photos"), str(mounts))
    a = gl.GenericLinuxStorageAdapter(str(tmp_path))
    monkeypatch.setattr(gl, "is_subvolume", lambda p: True)
    monkeypatch.setattr(gl.os.path, "ismount", lambda p: True)  # what Python says of a subvolume
    monkeypatch.setattr(a, "_run_cmd", lambda cmd: (0, "", ""))
    assert a.can_swap_in(str(tmp_path / "photos"), str(tmp_path / "snap"))
    monkeypatch.setattr(gl, "is_mount_point", lambda p: True)
    assert not a.can_swap_in(str(tmp_path / "photos"), str(tmp_path / "snap"))


def test_a_snapshot_that_reads_empty_never_empties_the_share(pal):
    (pal.live / "a.jpg").write_text("the only copy")
    (pal.snapdir / "photos@auto-1").mkdir()  # what a ZFS snapshot looks like in a container
    with pytest.raises(RuntimeError, match="reads as empty"):
        snaps.rollback("photos@auto-1", pal=pal, pool_id="tank")
    assert (pal.live / "a.jpg").read_text() == "the only copy" and not pal.swapped
    assert not [n for n in pal.created if "before-rollback" in n]  # nothing taken, nothing changed


def test_snapshots_are_read_where_the_adapter_says(pal, tmp_path):
    view = tmp_path / "view"
    (view / "album").mkdir(parents=True)
    (view / "album" / "b.jpg").write_text("from the mount")
    (pal.snapdir / "photos@auto-1").mkdir()
    pal.readable_snapshot_path = lambda snap: str(view)
    assert [e["name"] for e in snaps.browse("photos@auto-1", "album", pal=pal, pool_id="tank")["entries"]] == ["b.jpg"]
