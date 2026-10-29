"""B12b (REL-15, FEAT-04, D9): a Recycle Bin per share, SMB deletes into it, auto-empty after 30
days or above a tenth of the disk, and the grace period: what was in a bin at the update keeps 30
days from then and the size limit leaves it alone until those end."""

import os
import time

import pytest

from backend import config
from backend.services import recycle_bin as rb
from backend.services import samba_engine
from backend.services.samba_engine import SambaShareConfig

DAY = 86400


@pytest.fixture
def root(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    (pool / "photos").mkdir(parents=True)
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    return pool


def _binned(bin_dir, name, deleted, size=10, info=True):
    files = bin_dir / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / name).write_bytes(b"x" * size)
    if info:
        (bin_dir / "info").mkdir(exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(deleted))
        (bin_dir / "info" / f"{name}.trashinfo").write_text(f"[Trash Info]\nPath=/x/{name}\nDeletionDate={stamp}\n")
    os.utime(files / name, (deleted, deleted))


def test_each_share_has_its_own_bin(root):
    (root / "photos" / "a.jpg").write_text("a")
    name = rb.move_to_bin(str(root / "photos" / "a.jpg"))
    assert (root / "photos" / ".RecycleBin" / "files" / name).exists()
    assert rb.item_id(str(root / "photos" / ".RecycleBin"), name) == f"photos::{name}"
    assert rb.item_id(str(root / ".RecycleBin"), name) == name
    assert rb.locate(f"photos::{name}") == (str(root / "photos" / ".RecycleBin"), name)
    assert rb.locate(f"music::{name}") is None and rb.locate("../x") is None
    assert str(root / "photos" / ".RecycleBin") in rb.all_bins()


def test_items_go_after_30_days(root):
    b = root / "photos" / ".RecycleBin"
    now = time.time()
    rb.grace_start(now - 100 * DAY)  # auto-empty arrived long ago
    _binned(b, f"{int(now - 40 * DAY)}_old.txt", now - 40 * DAY)
    _binned(b, f"{int(now - 5 * DAY)}_new.txt", now - 5 * DAY)
    assert rb.auto_empty(str(b), now) == 1
    assert [i["name"].split("_", 1)[1] for i in rb.items(str(b))] == ["new.txt"]


def test_what_was_there_at_the_update_keeps_30_days_from_it(root):
    b = root / "photos" / ".RecycleBin"
    now = time.time()
    rb.grace_start(now)  # the update is today
    _binned(b, "kept.txt", now - 90 * DAY)
    assert rb.auto_empty(str(b), now, force=True) == 0
    assert rb.auto_empty(str(b), now + 29 * DAY, force=True) == 0
    assert rb.auto_empty(str(b), now + 31 * DAY, force=True) == 1


def test_the_size_limit_takes_the_oldest_but_not_what_is_in_grace(root, monkeypatch):
    b = root / "photos" / ".RecycleBin"
    now = time.time()
    rb.grace_start(now - 10 * DAY)
    _binned(b, "from-before.txt", now - 60 * DAY, size=500)  # in a bin at the update
    _binned(b, f"{int(now - 3 * DAY)}_older.txt", now - 3 * DAY, size=500)
    _binned(b, f"{int(now - DAY)}_newer.txt", now - DAY, size=500)
    monkeypatch.setattr(rb, "_disk_bytes", lambda d: 10_000)  # a limit of 1,000 bytes
    assert rb.auto_empty(str(b), now) == 1
    left = sorted(i["name"] for i in rb.items(str(b)))
    assert left == [f"{int(now - DAY)}_newer.txt", "from-before.txt"]
    assert rb.total_bytes() == 1000


def test_a_bin_is_checked_at_most_once_an_hour(root, monkeypatch):
    b = root / "photos" / ".RecycleBin"
    b.mkdir()
    rb.auto_empty(str(b), force=True)

    def scanned(_d):
        raise AssertionError("scanned again")

    monkeypatch.setattr(rb, "items", scanned)
    assert rb.auto_empty(str(b)) == 0


def test_an_smb_delete_is_listed_and_goes_back_into_its_share(client, auth_headers, monkeypatch):
    share = os.path.join(config.ALLOWED_BROWSE_ROOTS[0], f"recyc{int(time.time() * 1000) % 10**8}")
    b = os.path.join(share, ".RecycleBin", "files")
    os.makedirs(b)
    with open(os.path.join(b, "report.docx"), "w") as f:
        f.write("deleted from Windows")
    listing = client.get("/api/fs/trash", headers=auth_headers).json()["items"]
    mine = next(i for i in listing if i["id"] == f"{os.path.basename(share)}::report.docx")
    assert mine["name"] == "report.docx" and mine["original_path"] == ""
    res = client.post("/api/fs/trash/restore", json={"item_id": mine["id"]}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["path"] == os.path.join(share, "report.docx")
    assert client.post("/api/fs/trash/restore", json={"item_id": mine["id"]}, headers=auth_headers).status_code == 404
    assert client.post("/api/fs/trash/restore", json={"item_id": "a/b"}, headers=auth_headers).status_code == 400


def _conf(tmp_path, monkeypatch, share):
    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(tmp_path / "smb.conf"))
    monkeypatch.setattr(samba_engine, "validate_share", lambda s: None)
    engine = samba_engine.SambaEngine.__new__(samba_engine.SambaEngine)
    engine._shares = {share.name: share}
    return engine.generate_and_save_conf()


def test_smb_deletes_go_to_the_share_bin(tmp_path, monkeypatch):
    conf = _conf(tmp_path, monkeypatch, SambaShareConfig(name="photos", path=str(tmp_path)))
    assert "vfs objects = catia fruit streams_xattr recycle" in conf
    assert "recycle:repository = .RecycleBin/files" in conf and "recycle:touch_mtime = yes" in conf
    off = _conf(tmp_path, monkeypatch, SambaShareConfig(name="photos", path=str(tmp_path), recycle_bin=False))
    assert "recycle" not in off.split("[photos]")[1]


def test_previous_versions_and_the_bin_together(tmp_path, monkeypatch):
    monkeypatch.setattr(samba_engine, "_snapshot_dir_for", lambda path: "/pool/@snapshots")
    conf = _conf(tmp_path, monkeypatch, SambaShareConfig(name="photos", path=str(tmp_path), previous_versions=True))
    assert "vfs objects = catia fruit streams_xattr shadow_copy2 recycle" in conf


def test_the_overview_counts_what_the_bins_hold(root, monkeypatch):
    from backend.services import protection_status

    b = root / "photos" / ".RecycleBin"
    _binned(b, f"{int(time.time())}_a.txt", time.time(), size=1234)
    rb.auto_empty(str(b), force=True)
    monkeypatch.setattr(protection_status, "copies", lambda: [])
    assert protection_status.status()["recycle_bytes"] == 1234


def test_a_name_with_a_time_counts_from_it_and_one_without_from_its_date(root):
    b = root / "photos" / ".RecycleBin"
    _binned(b, "1793000000_a.txt", 1793091600, info=False)
    _binned(b, "plain.txt", 1793091600, info=False)
    found = {i["name"]: i["deleted_at"] for i in rb.items(str(b))}
    assert found == {"1793000000_a.txt": 1793000000.0, "plain.txt": 1793091600.0}


def test_the_bin_view_shows_every_shares_bin(client, auth_headers):
    """Deleting inside a share fills that share's bin; the File Explorer's Recycle Bin (the top
    one) used to show only its own folder, so the item couldn't be seen or restored there."""
    root = config.ALLOWED_BROWSE_ROOTS[0]
    share = os.path.join(root, f"binview{int(time.time() * 1000) % 10**8}")
    photos = os.path.join(share, "Media", "Photos")
    os.makedirs(photos)
    src = os.path.join(photos, "IMG_0412.HEIC")
    with open(src, "w") as f:
        f.write("photo")
    assert client.post("/api/fs/delete", json={"path": src}, headers=auth_headers).status_code == 200
    assert not os.path.exists(src) and os.path.isdir(os.path.join(share, ".RecycleBin", "files"))

    view = client.get(f"/api/browse?path={root}/.RecycleBin", headers=auth_headers).json()
    assert view["recycle_bin"] is True
    item = next(d for d in view["dirs"] if d.get("original_path") == src)
    assert item["name"] == "IMG_0412.HEIC" and item["size"] == 5 and item["ext"] == ".heic"
    assert item["path"].startswith(os.path.join(share, ".RecycleBin", "files"))
    # a folder picker (dirs only) still sees the plain folder
    assert (
        "recycle_bin" not in client.get(f"/api/browse?path={root}/.RecycleBin&dirs_only=1", headers=auth_headers).json()
    )

    res = client.post("/api/fs/trash/restore", json={"item_id": item["trash_id"]}, headers=auth_headers)
    assert res.status_code == 200 and os.path.exists(src)
