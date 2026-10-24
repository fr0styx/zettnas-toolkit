"""Batch 6: offsite backup restore drill with the real restic (init, back up, damage,
list versions, browse, restore, verify, prune)."""

import os
import shutil

import pytest

from backend import config
from backend.services import offsite_backup as ob

pytestmark = pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed")


@pytest.fixture
def env(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    (storage / "family").mkdir(parents=True)
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(storage)])
    monkeypatch.setattr(ob, "REPOS_FILE", str(tmp_path / "repos.json"))
    monkeypatch.setattr(ob, "KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    return storage


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _read(path):
    with open(path) as f:
        return f.read()


def test_offsite_restore_drill(env):
    fam = env / "family"
    _write(str(fam / "taxes.txt"), "2025 return")
    _write(str(fam / "photos" / "beach.txt"), "sand")
    repo_dir = env / "usb" / "zettnas-backup"
    ob.save_repo("usb", "USB disk", str(repo_dir), [str(fam)], keep={"daily": 3}, hour=None)
    first = ob.backup("usb")
    assert first["files_new"] == 2
    _write(str(fam / "taxes.txt"), "ENCRYPTED")  # the disaster
    second = ob.backup("usb")
    assert second["files_changed"] == 1
    versions = ob.snapshots("usb")
    assert len(versions) == 2
    oldest = versions[-1]["id"]
    entries = ob.browse("usb", oldest, str(fam))
    assert {e["name"] for e in entries} == {"photos", "taxes.txt"}
    out = ob.restore("usb", oldest, str(fam / "taxes.txt"), str(env / "restored"))
    assert _read(out["restored_to"]) == "2025 return"
    assert _read(str(fam / "taxes.txt")) == "ENCRYPTED"  # live file untouched
    assert ob.check("usb", read_percent=100)["ok"]
    # the repository is encrypted: no plain file content on the destination
    for root, _dirs, files in os.walk(repo_dir):
        for name in files:
            with open(os.path.join(root, name), "rb") as f:
                assert b"2025 return" not in f.read()


def test_paths_must_be_on_the_storage(env):
    with pytest.raises(ValueError):
        ob.save_repo("bad", "x", "/etc/backups", [str(env / "family")])
    with pytest.raises(ValueError):
        ob.save_repo("bad", "x", str(env / "usb"), ["/app/data"])
    ob.save_repo("ok", "x", str(env / "usb2"), [str(env / "family")], hour=None)
    with pytest.raises(ValueError):
        ob.restore("ok", "latest", "/x", "/app/data")
