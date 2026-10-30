"""NUX-24: the USB photo import says where the photos go."""

import json

from backend.services import usb_copy


def test_the_import_names_its_destination(tmp_path, monkeypatch):
    cfg = tmp_path / "buttons.json"
    monkeypatch.setattr(usb_copy, "BUTTON_CFG_FILE", str(cfg))
    assert usb_copy.import_dest() == "/mnt/user/"
    cfg.write_text(json.dumps({"dest": "/mnt/user/Photos/"}))
    assert usb_copy.import_dest() == "/mnt/user/Photos/"
    disk = tmp_path / "cam"
    (disk / "DCIM").mkdir(parents=True)
    monkeypatch.setattr(usb_copy, "_backups_on", lambda p: [])
    d = usb_copy.describe(str(disk))
    assert d["media"] is True and d["import_dest"] == "/mnt/user/Photos/"
