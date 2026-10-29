"""FEAT-07: a USB disk that is plugged in is offered for a backup or a photo import, and the
photo import copies with the card reader's verified copy."""

import threading

import pytest

from backend.services import copy_engine, usb_copy
from backend.services import offsite_backup as ob


class _State:
    def __init__(self):
        self.pending_usb = None
        self.ui_wake = threading.Event()


@pytest.fixture
def usb(tmp_path, monkeypatch):
    root = tmp_path / "disks"
    root.mkdir()
    mounts = tmp_path / "mounts"
    mounts.write_text("overlay / overlay rw 0 0\n")
    monkeypatch.setattr(usb_copy, "USB_ROOT", str(root))
    monkeypatch.setattr(usb_copy, "MOUNTS", str(mounts))
    monkeypatch.setattr(usb_copy, "SETTINGS_FILE", str(tmp_path / "usb.json"))
    monkeypatch.setattr(usb_copy, "_SEEN", None)
    return root, mounts


def plug(root, mounts, name, dcim=False):
    disk = root / name
    disk.mkdir()
    if dcim:
        (disk / "DCIM" / "100CANON").mkdir(parents=True)
        (disk / "DCIM" / "100CANON" / "IMG_0001.JPG").write_bytes(b"jpeg" * 50)
    with open(mounts, "a") as f:
        f.write(f"/dev/sdx1 {str(disk).replace(' ', chr(92) + '040')} exfat rw 0 0\n")
    return str(disk)


def unplug(mounts, path):
    with open(mounts) as f:
        lines = [line for line in f if path not in line.replace("\\040", " ")]
    with open(mounts, "w") as f:
        f.writelines(lines)


def test_mounted_reads_only_the_mount_table(usb):
    root, mounts = usb
    a = plug(root, mounts, "Backup Disk")
    with open(mounts, "a") as f:
        f.write(f"/dev/sdy1 {root}/a/b ext4 rw 0 0\nshort\n")  # deeper paths aren't disks
    assert usb_copy.mounted() == [a]
    assert usb_copy.mounted(str(root), str(root / "missing")) == []


def test_describe_lists_space_media_and_backups(usb, monkeypatch):
    root, mounts = usb
    cam = plug(root, mounts, "camera", dcim=True)
    monkeypatch.setattr(
        ob,
        "list_repos",
        lambda: [
            {"id": "usb1", "name": "USB", "location": f"{cam}/zettnas"},
            {"id": "cloud", "location": "rclone:x:y"},
        ],
    )
    d = usb_copy.describe(cam)
    assert d["media"] is True and d["backups"] == [{"id": "usb1", "name": "USB"}] and d["total_bytes"] > 0
    assert usb_copy.describe(str(root / "gone"))["total_bytes"] == 0
    assert [x["name"] for x in usb_copy.disks()] == ["camera"]
    with pytest.raises(KeyError):
        usb_copy.find(str(root / "not-mounted"))


def test_a_new_disk_is_offered_once(usb, monkeypatch):
    root, mounts = usb
    monkeypatch.setattr(
        ob, "list_repos", lambda: [{"id": "nightly", "name": "Nightly", "location": f"{root}/backup/zettnas"}]
    )
    sent, state = [], _State()
    plug(root, mounts, "old")  # already there at start: not offered
    assert usb_copy.tick(state, sent.append) == []
    disk = plug(root, mounts, "backup")
    assert usb_copy.tick(state, sent.append) == [disk]
    assert state.pending_usb["backups"] == [{"id": "nightly", "name": "Nightly"}] and state.ui_wake.is_set()
    assert "back up the NAS to it" in sent[0]["message"]
    assert usb_copy.tick(state, sent.append) == []  # still plugged in: no second offer
    unplug(mounts, disk)
    usb_copy.tick(state, sent.append)
    assert state.pending_usb is None  # the offered disk went away


def test_a_plain_disk_is_not_offered_and_offers_can_be_off(usb, monkeypatch):
    root, mounts = usb
    monkeypatch.setattr(ob, "list_repos", lambda: [])
    sent, state = [], _State()
    usb_copy.tick(state, sent.append)
    plug(root, mounts, "empty")
    usb_copy.tick(state, sent.append)
    assert state.pending_usb is None and sent == []
    usb_copy.save_settings(offer=False)
    plug(root, mounts, "cam", dcim=True)
    usb_copy.tick(state, sent.append)
    assert state.pending_usb is None


def test_auto_backup_starts_and_still_offers_the_photos(usb, monkeypatch):
    root, mounts = usb
    started = []
    monkeypatch.setattr(ob, "list_repos", lambda: [{"id": "b1", "name": "B1", "location": f"{root}/both"}])
    monkeypatch.setattr(ob, "start_backup", lambda rid, owner=None: started.append(rid))
    usb_copy.save_settings(auto_backup=True, offer=True)
    sent, state = [], _State()
    usb_copy.tick(state, sent.append)
    plug(root, mounts, "both", dcim=True)
    usb_copy.tick(state, sent.append)
    assert started == ["b1"]
    assert sent[0]["title"] == "Backing up to USB disk"
    assert state.pending_usb["backups"] == [] and state.pending_usb["media"] is True


def test_start_backups(usb, monkeypatch):
    root, mounts = usb
    disk = plug(root, mounts, "d")
    monkeypatch.setattr(ob, "list_repos", lambda: [])
    with pytest.raises(LookupError, match="Protect this NAS"):
        usb_copy.start_backups(disk)
    monkeypatch.setattr(ob, "list_repos", lambda: [{"id": "a", "location": disk}, {"id": "b", "location": disk + "/x"}])

    def start(rid, owner=None):
        if rid == "b":
            raise ob.BusyError("running")

    monkeypatch.setattr(ob, "start_backup", start)
    assert usb_copy.start_backups(disk, owner="admin") == ["a"]


def test_settings_round_trip(usb):
    assert usb_copy.settings() == {"offer": True, "auto_backup": False}
    assert usb_copy.save_settings(auto_backup=True, offer=None, nonsense=True) == {"offer": True, "auto_backup": True}
    state = _State()
    state.pending_usb = {"path": "/x"}
    usb_copy.dismiss(state)
    assert state.pending_usb is None


def test_usb_source(tmp_path, monkeypatch):
    from backend.services import protection_status

    root = tmp_path / "disks"
    (root / "cam" / "DCIM").mkdir(parents=True)
    (root / "plain").mkdir()
    monkeypatch.setattr(protection_status, "USB_ROOT", str(root))
    assert copy_engine.usb_source(str(root / "cam")) == str(root / "cam" / "DCIM")
    assert copy_engine.usb_source(str(root / "plain")) == str(root / "plain")
    with pytest.raises(Exception, match="not a USB disk"):
        copy_engine.usb_source(str(tmp_path))


@pytest.mark.asyncio
async def test_the_import_copies_and_verifies(tmp_path, monkeypatch):
    from backend.services import protection_status
    from backend.state import Z_STATE

    root = tmp_path / "disks"
    photo = root / "cam" / "DCIM" / "100CANON" / "IMG_0001.JPG"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"jpeg-bytes" * 300)
    dst = tmp_path / "photos"
    dst.mkdir()
    monkeypatch.setattr(protection_status, "USB_ROOT", str(root))
    monkeypatch.setattr(copy_engine, "resolve_copy_destination", lambda d: str(dst))
    monkeypatch.setattr(copy_engine, "_slot_source", lambda mode: pytest.fail("the card slots aren't looked at"))
    monkeypatch.setattr("time.sleep", lambda s: None)
    Z_STATE.copy_active = False
    Z_STATE.copy_abort_flag = False
    await copy_engine._do_copy({"source": "usb", "source_path": str(root / "cam"), "dest": str(dst), "use_exif": False})
    assert Z_STATE.copy_progress["file"] == "Finished successfully."
    copied = list(dst.rglob("IMG_0001.JPG"))
    assert copied and copied[0].read_bytes() == photo.read_bytes()


def test_api(client, auth_headers, usb, monkeypatch):
    root, mounts = usb
    disk = plug(root, mounts, "cam", dcim=True)
    monkeypatch.setattr(ob, "list_repos", lambda: [])
    res = client.get("/api/usb/disks", headers=auth_headers).json()
    assert res["disks"][0]["media"] is True and res["settings"]["offer"] is True
    assert (
        client.put("/api/usb/settings", json={"auto_backup": True}, headers=auth_headers).json()["auto_backup"] is True
    )
    assert client.post("/api/usb/import", json={"path": str(root / "nope")}, headers=auth_headers).status_code == 404
    assert client.post("/api/usb/backup", json={"path": disk}, headers=auth_headers).status_code == 409
    assert client.post("/api/usb/backup", json={"path": str(root / "nope")}, headers=auth_headers).status_code == 404

    from backend.api import system
    from backend.state import Z_STATE

    ran, done = [], threading.Event()

    async def fake_copy(cfg):
        ran.append(cfg)
        done.set()

    monkeypatch.setattr(system, "_do_copy", fake_copy)
    Z_STATE.copy_active = False
    assert client.post("/api/usb/import", json={"path": disk}, headers=auth_headers).json()["status"] == "started"
    assert done.wait(5)
    assert ran[0]["source_path"] == disk and ran[0]["source"] == "usb"
    Z_STATE.copy_active = True
    assert client.post("/api/usb/import", json={"path": disk}, headers=auth_headers).status_code == 409
    Z_STATE.copy_active = False

    monkeypatch.setattr(ob, "list_repos", lambda: [{"id": "u", "location": disk}])
    monkeypatch.setattr(ob, "start_backup", lambda rid, owner=None: None)
    assert client.post("/api/usb/backup", json={"path": disk}, headers=auth_headers).json()["backups"] == ["u"]
    assert client.post("/api/usb/dismiss", headers=auth_headers).json()["status"] == "dismissed"
