"""SET-05, the owner's decision S14: the bin's two rules are guarded and said.

A deleted folder larger than a tenth of its drive was removed for good at the bin's next check,
which could be the delete itself or the moment the bin was opened to restore it, while the screen
said "Moved to the Recycle Bin · Undo". Nothing younger than a day is removed by the size rule
now, a delete too large for the bin asks first, and the bin says when each item goes."""

import os
import shutil
import time

import pytest

from backend.config import POOL_PATH as POOL_DIR
from backend.services import recycle_bin

DAY = 86400


@pytest.fixture
def bin_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(recycle_bin.config, "DATA_DIR", str(tmp_path / "data"))
    os.makedirs(tmp_path / "data")
    b = tmp_path / "share" / recycle_bin.BIN
    os.makedirs(b / "files")
    os.makedirs(b / "info")
    monkeypatch.setattr(recycle_bin, "_disk_bytes", lambda d: 1000)  # the bin may hold 100 bytes
    monkeypatch.setattr(recycle_bin, "asleep", lambda d: False)
    recycle_bin.grace_start(time.time() - 400 * DAY)  # an install long past its first 30 days
    return str(b)


def _put(bin_dir, name, size, age_days, now):
    path = os.path.join(bin_dir, "files", name)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    when = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - age_days * DAY))
    with open(os.path.join(bin_dir, "info", f"{name}.trashinfo"), "w") as f:
        f.write(f"[Trash Info]\nPath=/somewhere/{name}\nDeletionDate={when}\n")
    return path


def _names(bin_dir):
    return sorted(os.listdir(os.path.join(bin_dir, "files")))


def test_what_was_just_deleted_stays_a_day_whatever_its_size(bin_dir):
    now = time.time()
    _put(bin_dir, "huge-just-deleted", 500, 0.01, now)  # five times what the bin may hold
    assert recycle_bin.auto_empty(bin_dir, now=now, force=True) == 0
    assert _names(bin_dir) == ["huge-just-deleted"]
    # a day later the size rule applies to it
    assert recycle_bin.auto_empty(bin_dir, now=now + 1.1 * DAY, force=True) == 1
    assert _names(bin_dir) == []


def test_the_size_rule_takes_the_oldest_first_and_spares_the_last_day(bin_dir):
    now = time.time()
    _put(bin_dir, "old", 60, 5, now)
    _put(bin_dir, "older", 60, 9, now)
    _put(bin_dir, "today", 60, 0.2, now)
    assert recycle_bin.auto_empty(bin_dir, now=now, force=True) == 2  # 180 > 100: the two old ones go
    assert _names(bin_dir) == ["today"]


def test_thirty_days_still_holds(bin_dir):
    now = time.time()
    _put(bin_dir, "small-and-old", 1, 31, now)
    _put(bin_dir, "small-and-new", 1, 2, now)
    assert recycle_bin.auto_empty(bin_dir, now=now, force=True) == 1
    assert _names(bin_dir) == ["small-and-new"]


def test_the_bin_knows_when_each_item_goes(bin_dir):
    now = time.time()
    _put(bin_dir, "a-old", 60, 20, now)
    _put(bin_dir, "b-new", 30, 2, now)
    held = recycle_bin.items(bin_dir)
    goes = recycle_bin.leaving(bin_dir, held, now)
    assert goes["a-old"] == pytest.approx(now + 10 * DAY, abs=120)  # 30 days after it was deleted
    assert goes["b-new"] == pytest.approx(now + 28 * DAY, abs=120)
    _put(bin_dir, "c-big", 80, 0.5, now)  # now 170 > 100: the oldest goes at the next check,
    goes = recycle_bin.leaving(bin_dir, recycle_bin.items(bin_dir), now)
    assert goes["a-old"] == pytest.approx(now, abs=5)
    assert goes["b-new"] == pytest.approx(now, abs=5)  # and the next oldest (110 > 100 still)
    assert goes["c-big"] == pytest.approx(now + 29.5 * DAY, abs=120)


def test_too_large_for_the_bin(bin_dir, tmp_path):
    small, big = tmp_path / "small.bin", tmp_path / "Videos"
    small.write_bytes(b"x" * 100)
    os.makedirs(big / "2024")
    (big / "2024" / "a.mkv").write_bytes(b"x" * 60)
    (big / "b.mkv").write_bytes(b"x" * 60)
    assert recycle_bin.too_large_for_bin(str(small), bin_dir) is False  # exactly the limit fits
    assert recycle_bin.too_large_for_bin(str(big), bin_dir) is True
    assert recycle_bin.too_large_for_bin(str(tmp_path / "gone"), bin_dir) is False


@pytest.fixture
def pool_folder(monkeypatch):
    # an install long past its first 30 days (a new one counts every item from its first check)
    long_ago = time.time() - 400 * DAY
    monkeypatch.setattr(recycle_bin, "grace_start", lambda now=None: long_ago)
    folder = os.path.join(POOL_DIR, "set05_bin")
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(os.path.join(folder, "Videos"))
    with open(os.path.join(folder, "Videos", "film.mkv"), "wb") as f:
        f.write(b"x" * 2048)
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


def test_a_delete_too_large_for_the_bin_asks_first(client, auth_headers, pool_folder, monkeypatch):
    target = os.path.join(pool_folder, "Videos")
    monkeypatch.setattr(recycle_bin, "_disk_bytes", lambda d: 10_000)  # the bin may hold 1000 bytes
    r = client.post("/api/fs/delete", json={"path": target}, headers=auth_headers)
    assert r.status_code == 409 and r.json()["error"] == "too_large_for_bin"
    assert os.path.isdir(target)  # nothing happened
    r = client.post("/api/fs/delete", json={"path": target, "large_ok": True}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["trash_id"]
    assert not os.path.exists(target)
    # it is in the bin, and the bin says it goes in a day, not in thirty
    listing = client.get("/api/fs/trash", headers=auth_headers).json()
    mine = next(i for i in listing["items"] if str(i["original_path"]).endswith("set05_bin/Videos"))
    assert mine["leaves_at"] == pytest.approx(time.time() + DAY, abs=300)
    assert listing["leaving_soon"] >= 1
    assert listing["rules"] == {"keep_days": 30, "max_percent_of_disk": 10, "min_days": 1, "soon_days": 7}
    # the File Explorer's bin view carries the same
    view = client.get("/api/fs/list", params={"path": os.path.dirname(mine["path"])}, headers=auth_headers)
    if view.status_code == 200 and view.json().get("recycle_bin"):
        row = next(d for d in view.json()["dirs"] if d["trash_id"] == mine["id"])
        assert row["leaves_at"] == mine["leaves_at"] and view.json()["leaving_soon"] >= 1
    client.post("/api/fs/trash/restore", json={"item_id": mine["id"]}, headers=auth_headers)


def test_an_ordinary_delete_is_not_asked_about(client, auth_headers, pool_folder):
    target = os.path.join(pool_folder, "Videos", "film.mkv")
    r = client.post("/api/fs/delete", json={"path": target}, headers=auth_headers)
    assert r.status_code == 200, r.text
    listing = client.get("/api/fs/trash", headers=auth_headers).json()
    mine = next(i for i in listing["items"] if str(i["original_path"]).endswith("Videos/film.mkv"))
    assert mine["leaves_at"] == pytest.approx(time.time() + 30 * DAY, abs=300)
    client.post("/api/fs/trash/restore", json={"item_id": mine["id"]}, headers=auth_headers)
