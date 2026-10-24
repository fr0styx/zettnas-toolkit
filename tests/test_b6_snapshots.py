"""Batch 6: snapshot schedules and a restore drill (take, change, browse, restore)."""

import os
import shutil
import time
from types import SimpleNamespace

import pytest

from backend.services import snapshot_service as snaps


class FakePal:
    """A storage platform whose snapshots are directory copies, like Btrfs snapshots to a reader."""

    def __init__(self, pool):
        self.pool = pool
        os.makedirs(os.path.join(pool, "@shares", "family"), exist_ok=True)
        os.makedirs(os.path.join(pool, "@snapshots"), exist_ok=True)
        self.locked = set()

    def list_pools(self):
        return [SimpleNamespace(id="pool1", fs_type="btrfs")]

    def get_pool_path(self, pool_id):
        return self.pool

    def list_shares(self):
        return [SimpleNamespace(name="family", mountpoint=os.path.join(self.pool, "@shares", "family"))]

    def create_snapshot(self, pool_id, subvol, name, readonly=True, worm_mode=None, retention_days=None):
        dest = os.path.join(self.pool, "@snapshots", name)
        shutil.copytree(os.path.join(self.pool, "@shares", subvol), dest)
        if worm_mode:
            self.locked.add(name)
        return {"status": "created"}

    def list_snapshots(self, pool_id):
        d = os.path.join(self.pool, "@snapshots")
        return [
            {"name": n, "path": os.path.join(d, n), "is_immutable": n in self.locked} for n in sorted(os.listdir(d))
        ]

    def delete_snapshot(self, pool_id, name):
        shutil.rmtree(os.path.join(self.pool, "@snapshots", name))


@pytest.fixture
def pal(tmp_path, monkeypatch):
    monkeypatch.setattr(snaps, "SCHEDULES_FILE", str(tmp_path / "sched.json"))
    monkeypatch.setattr(snaps, "_set_previous_versions", lambda share, on: None)
    p = FakePal(str(tmp_path / "pool"))
    monkeypatch.setattr(snaps, "_pal", lambda: p)
    return p


def _read(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


def _live(pal, *parts):
    return os.path.join(pal.pool, "@shares", "family", *parts)


def test_restore_drill(pal):
    with open(_live(pal, "taxes.txt"), "w") as f:
        f.write("2025 return")
    os.makedirs(_live(pal, "photos"))
    with open(_live(pal, "photos", "beach.jpg"), "wb") as f:
        f.write(b"\xff\xd8 beach")
    snaps.save_schedule("family", "daily", keep=5)
    done = snaps.run_due(now=time.time())
    assert done and done[0]["ok"]
    name = done[0]["name"]
    assert name.startswith("family@auto-")
    # the "disaster": a file encrypted, a folder deleted
    with open(_live(pal, "taxes.txt"), "w") as f:
        f.write("ENCRYPTED")
    shutil.rmtree(_live(pal, "photos"))
    listing = snaps.browse(name)
    assert {e["name"] for e in listing["entries"]} == {"photos", "taxes.txt"}
    beside = snaps.restore(name, "taxes.txt")
    assert "restored" in beside["restored"] and _read(_live(pal, beside["restored"])) == "2025 return"
    assert _read(_live(pal, "taxes.txt")) == "ENCRYPTED"  # untouched without overwrite
    snaps.restore(name, "taxes.txt", overwrite=True)
    assert _read(_live(pal, "taxes.txt")) == "2025 return"
    snaps.restore(name, "photos")
    assert _read(_live(pal, "photos", "beach.jpg"), "rb") == b"\xff\xd8 beach"


def test_paths_cannot_escape(pal):
    snaps.save_schedule("family", "daily", keep=5)
    name = snaps.run_due()[0]["name"]
    with pytest.raises(FileNotFoundError):
        snaps.browse(name, "../../")
    with pytest.raises(FileNotFoundError):
        snaps.restore(name, "../../../etc/passwd")


def test_schedule_runs_when_due_and_prunes(pal, monkeypatch):
    snaps.save_schedule("family", "hourly", keep=2)
    names = iter(f"family@auto-2025010{i}-0000" for i in range(1, 6))
    monkeypatch.setattr(snaps, "snapshot_name", lambda share, now=None: next(names))
    t = time.time()
    for i in range(4):
        snaps.run_due(now=t + i * 3601)
    assert snaps.run_due(now=t + 3 * 3601 + 10) == []  # not due yet
    left = [s["name"] for s in pal.list_snapshots("pool1")]
    assert left == ["family@auto-20250103-0000", "family@auto-20250104-0000"]


def test_locked_snapshots_are_kept(pal, monkeypatch):
    snaps.save_schedule("family", "hourly", keep=1, immutable_days=7)
    names = iter(["family@auto-20250101-0000", "family@auto-20250102-0000"])
    monkeypatch.setattr(snaps, "snapshot_name", lambda share, now=None: next(names))
    snaps.run_due(now=100000.0)
    snaps.run_due(now=100000.0 + 3601)
    assert len(pal.list_snapshots("pool1")) == 2


def test_bad_schedules_are_refused(pal):
    with pytest.raises(ValueError):
        snaps.save_schedule("../etc", "daily", 3)
    with pytest.raises(ValueError):
        snaps.save_schedule("family", "every-second", 3)


def test_previous_versions_in_samba(tmp_path):
    from backend.services.samba_engine import SambaShareConfig, _snapshot_dir_for

    assert _snapshot_dir_for("/mnt/pool/@shares/family") == "/mnt/pool/@snapshots"
    cfg = SambaShareConfig(name="family", path="/mnt/pool/@shares/family", previous_versions=True)
    assert cfg.previous_versions
