"""RES-7: a whole box back from its off-site backup's recovery kit, with the real restic."""

import json
import os
import shutil

import pytest

from backend import config
from backend.services import backup_engine, box_restore, nas_name
from backend.services import offsite_backup as ob

needs_restic = pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed")


def _write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _read(path):
    with open(path) as f:
        return f.read()


def _box(tmp_path, name, monkeypatch):
    """One Kiboto's data folder; the off-site backup and the settings export both use it."""
    d = tmp_path / name
    d.mkdir()
    monkeypatch.setattr(ob, "REPOS_FILE", str(d / "offsite_repos.json"))
    monkeypatch.setattr(ob, "KEY_DIR", str(d / "offsite_keys"))
    monkeypatch.setattr(ob, "DATA_DIR", str(d))
    monkeypatch.setattr(ob, "RCLONE_CONFIG_FILE", str(d / "rclone" / "rclone.conf"))
    monkeypatch.setattr(backup_engine, "DATA_DIR", str(d))
    monkeypatch.setattr(ob, "SETTINGS_DIR", str(d / "backups" / "offsite-settings"))
    monkeypatch.setattr(box_restore, "RCLONE_CONFIG_FILE", str(d / "rclone" / "rclone.conf"))
    return d


@pytest.fixture
def storage(tmp_path, monkeypatch):
    s = tmp_path / "storage"
    (s / "family").mkdir(parents=True)
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(s)])
    monkeypatch.setattr(nas_name, "_self", lambda: {})  # no Docker here: nobody restarts the app
    monkeypatch.setattr(ob, "_start", lambda rid, fn, *a, **k: fn(*a, **k))  # jobs run inline
    return s


@needs_restic
def test_the_kit_alone_brings_back_settings_and_files(tmp_path, monkeypatch, storage):
    # the old box: a setting, a family folder, a nightly backup to a USB disk
    old = _box(tmp_path, "old", monkeypatch)
    _write(old / "identity.json", json.dumps({"server_name": "Attic"}))
    _write(old / "cache" / "thumbs" / "a.webp", "x" * 1000)  # rebuilt by itself: not in the copy
    fam = storage / "family"
    _write(fam / "taxes.txt", "2025 return")
    _write(fam / "photos" / "beach.txt", "sand")
    repo_dir = storage / "usb" / "kiboto-backup"
    ob.save_repo("usb", "USB disk", str(repo_dir), [str(fam)], hour=None)
    result = ob.backup("usb")
    assert result["settings_copy"]
    assert len(ob.snapshots("usb")) == 1  # versions are the file backups only
    every = json.loads(ob.run_restic(ob.get_repo("usb"), ["snapshots", "--json"]))
    newest = max(every, key=lambda s: s["time"])
    assert newest["tags"] == [ob.FILE_TAG]  # old kits plain restore latest still gets the files
    kit = ob.recovery_kit("usb")

    # the house burnt down: a new box, empty shares, only the kit and the USB disk survived
    shutil.rmtree(fam)
    new = _box(tmp_path, "new", monkeypatch)
    connected = box_restore.connect(kit)
    rid = connected["repo"]["id"]
    assert connected["repo"]["hour"] is None  # nothing is written into the old backup by itself
    assert [v["paths"] for v in connected["versions"]] == [[str(fam)]]
    assert len(connected["settings"]) == 1

    out = box_restore.restore_settings(rid)
    assert out["restarting"] is False
    moved = backup_engine.apply_staged_restore(str(new))
    assert "identity.json" in moved
    assert json.loads(_read(new / "identity.json"))["server_name"] == "Attic"
    assert not (new / "cache").exists()

    # the restored settings hold the old box's backups again, keys included
    assert [r["id"] for r in ob.list_repos()] == ["usb"]
    started = box_restore.start_files_restore("usb")
    assert started["paths"] == [str(fam)]
    assert _read(fam / "taxes.txt") == "2025 return"
    assert _read(fam / "photos" / "beach.txt") == "sand"

    # a second run leaves files that are already there as they are
    _write(fam / "taxes.txt", "edited since")
    box_restore.start_files_restore("usb")
    assert _read(fam / "taxes.txt") == "edited since"

    with pytest.raises(box_restore.KitError, match="already connected"):
        box_restore.connect(kit)


@needs_restic
def test_a_drill_and_the_versions_ignore_the_settings_copies(tmp_path, monkeypatch, storage):
    _box(tmp_path, "box", monkeypatch)
    _write(storage / "family" / "note.txt", "hello")
    ob.save_repo("usb", "USB", str(storage / "usb" / "r"), [str(storage / "family")], hour=None)
    ob.backup("usb")
    assert ob.drill("usb")["file"].endswith("note.txt")
    assert len(ob.settings_copies("usb")) == 1


def test_parse_kit_reads_every_field():
    kit = (
        "Kiboto off-site backup: recovery kit\n"
        "Name: Cloud\n"
        "Backup location: rclone:b2:my-bucket/kiboto\n"
        "Recovery key: " + "k" * 43 + "\n"
        "Folders in it: /mnt/user/family, /mnt/user/photos\n"
        "  2. export RESTIC_REST_USERNAME='ann' RESTIC_REST_PASSWORD='p4ss'\n"
        "----- rclone.conf -----\n[b2]\ntype = b2\naccount = 123\n-----------------------\n"
    )
    k = box_restore.parse_kit(kit)
    assert k["name"] == "Cloud"
    assert k["location"] == "rclone:b2:my-bucket/kiboto"
    assert k["key"] == "k" * 43
    assert k["paths"] == ["/mnt/user/family", "/mnt/user/photos"]
    assert (k["rest_user"], k["rest_password"]) == ("ann", "p4ss")
    assert k["rclone"] == "[b2]\ntype = b2\naccount = 123"


def test_parse_kit_takes_the_key_from_the_commands_when_the_line_is_missing():
    k = box_restore.parse_kit("Backup location: /mnt/disks/usb/b\n  2. export RESTIC_PASSWORD='" + "a" * 32 + "'\n")
    assert k["key"] == "a" * 32


@pytest.mark.parametrize(
    "text,words",
    [
        ("hello there", "not a Kiboto recovery kit"),
        ("Kiboto off-site backup: recovery kit\nName: x\n", "missing its backup location"),
        ("Backup location: /x\nRecovery key: short\n", "looks damaged"),
        ("x" * (65 * 1024), "too big"),
    ],
)
def test_parse_kit_refuses_what_is_not_a_kit(text, words):
    with pytest.raises(box_restore.KitError, match=words):
        box_restore.parse_kit(text)


def test_the_kits_rclone_remote_is_added_but_never_replaces_another(tmp_path, monkeypatch):
    conf = tmp_path / "rclone.conf"
    monkeypatch.setattr(box_restore, "RCLONE_CONFIG_FILE", str(conf))
    box_restore._add_rclone_remote("[b2]\ntype = b2\naccount = 1", "rclone:b2:bucket")
    assert "[b2]" in _read(conf)
    assert oct(os.stat(conf).st_mode & 0o777) == "0o600"
    box_restore._add_rclone_remote("[b2]\ntype = b2\naccount = 1", "rclone:b2:bucket")  # same: fine
    with pytest.raises(box_restore.KitError, match="already exists"):
        box_restore._add_rclone_remote("[b2]\ntype = b2\naccount = 2", "rclone:b2:bucket")
    with pytest.raises(box_restore.KitError, match="no rclone settings"):
        box_restore._add_rclone_remote("", "rclone:s3:bucket")
    with pytest.raises(box_restore.KitError, match="no remote called s3"):
        box_restore._add_rclone_remote("[b2]\ntype = b2", "rclone:s3:bucket")
    with pytest.raises(box_restore.KitError, match="damaged"):
        box_restore._add_rclone_remote("type = b2", "rclone:b2:bucket")
    box_restore._add_rclone_remote("", "/mnt/disks/usb")  # a folder needs no remote


def test_restart_only_when_docker_starts_kiboto_again(monkeypatch):
    killed = []
    monkeypatch.setattr(box_restore.os, "kill", lambda pid, sig: killed.append(sig))
    monkeypatch.setattr(nas_name, "_self", lambda: {"HostConfig": {"RestartPolicy": {"Name": "no"}}})
    assert box_restore.restart_to_apply(delay=0) == {"restarting": False}
    monkeypatch.setattr(nas_name, "_self", lambda: {"HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}}})
    assert box_restore.restart_to_apply(delay=0) == {"restarting": True}
    for t in list(box_restore.threading.enumerate()):
        if t.name == "restore-restart":
            t.join(2)
    assert killed == [box_restore.signal.SIGTERM]


def test_a_settings_export_leaves_out_the_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_engine, "DATA_DIR", str(tmp_path))
    _write(tmp_path / "identity.json", "{}")
    _write(tmp_path / "cache" / "thumbs" / "a.webp", "thumb")
    _write(tmp_path / "restic_cache" / "x" / "data", "blob")
    import zipfile

    stream = backup_engine.generate_backup_zip_stream()
    names = zipfile.ZipFile(stream).namelist()
    assert "identity.json" in names
    assert not [n for n in names if n.startswith(("cache/", "restic_cache/"))]


def test_the_api_routes_need_the_admin_scope_and_confirmation():
    from backend.api import offsite

    routes = {r.path: r for r in offsite.router.routes}
    for path in (
        "/offsite/connect-kit",
        "/offsite/repos/{repo_id}/restore-settings",
        "/offsite/repos/{repo_id}/restore-all",
    ):
        assert path in routes
    names = [
        getattr(d.call, "__qualname__", "")
        for d in routes["/offsite/repos/{repo_id}/restore-all"].dependant.dependencies
    ]
    assert any("require_confirmation" in n for n in names)
    from backend.confirmations import ACTIONS

    assert "offsite.restore_all" in ACTIONS
