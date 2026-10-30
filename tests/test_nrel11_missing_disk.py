"""NREL-11: a backup to a USB disk that isn't plugged in fails; it never fills a folder in the container."""

import pytest

from backend.services import offsite_backup as ob


def test_a_missing_disk_is_named(monkeypatch):
    monkeypatch.setattr(ob.os.path, "ismount", lambda p: p == "/mnt/disks/usb1")
    assert ob.disk_missing("/mnt/disks/usb1/backup") is None
    assert "isn't connected" in ob.disk_missing("/mnt/disks/usb2/backup")
    assert ob.disk_missing("/mnt/user/Backups") is None  # a share is always there


def test_init_and_backup_refuse(monkeypatch):
    made = []
    monkeypatch.setattr(
        ob, "get_repo", lambda rid: {"id": rid, "name": "USB", "location": "/mnt/disks/usb2/b", "initialized": False}
    )
    monkeypatch.setattr(ob.os.path, "ismount", lambda p: False)
    monkeypatch.setattr(ob.os, "makedirs", lambda *a, **k: made.append(a[0]))
    with pytest.raises(ob.ResticError, match="isn't connected"):
        ob.init("r1")
    with pytest.raises(ob.ResticError, match="isn't connected"):
        ob.backup("r1")
    assert made == []
