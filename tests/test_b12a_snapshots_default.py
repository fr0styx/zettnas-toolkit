"""B12a (FEAT-02): snapshots on by default for new shares (hourly, a day of them plus one a day
for 30 days), offered for existing ones, and a whole share rolled back to a snapshot with the
current state kept first."""

import os
from types import SimpleNamespace

import pytest

from backend.services import safe_defaults_advisor
from backend.services import snapshot_service as snaps


def _name(day, hhmm, share="photos"):
    return f"{share}@auto-202610{day:02d}-{hhmm}"


def test_retention_keeps_the_newest_and_one_a_day():
    names = [_name(d, f"{h:02d}00") for d in range(1, 11) for h in range(0, 24, 6)]  # 10 days, 4 a day
    kept = snaps.to_keep(names, keep=3, keep_daily=5)
    newest = sorted(names, reverse=True)
    assert set(newest[:3]) <= kept
    daily = {n for n in kept if n not in newest[:3]}
    assert {n.split("@auto-")[1][:8] for n in kept} == {f"202610{d:02d}" for d in range(6, 11)}
    assert len(daily) == 4  # day 10's newest is already among the newest three
    assert snaps.to_keep(names, keep=2) == set(newest[:2])


class FakePal:
    def __init__(self, tmp_path, snapshot_ok=True):
        self.pool = tmp_path / "pool"
        self.live = self.pool / "photos"
        self.live.mkdir(parents=True)
        self.snapdir = self.pool / "@snapshots"
        self.snapdir.mkdir()
        self.snapshot_ok = snapshot_ok
        self.created = []
        self.deleted = []

    def get_capabilities(self):
        return SimpleNamespace(can_snapshot=True)

    def list_pools(self):
        return [SimpleNamespace(id="tank", total_bytes=1)]

    def get_pool_path(self, pool_id):
        return str(self.pool)

    def list_shares(self):
        return [SimpleNamespace(name="photos", mountpoint=str(self.live))]

    def list_snapshots(self, pool_id):
        return [{"name": p.name, "path": str(p)} for p in self.snapdir.iterdir()]

    def create_snapshot(self, pool_id, share, name, **kw):
        if not self.snapshot_ok:
            return {"status": "error"}
        self.created.append(name)
        import shutil

        shutil.copytree(self.live, self.snapdir / name)
        return {"status": "created"}

    def delete_snapshot(self, pool_id, name):
        self.deleted.append(name)


@pytest.fixture
def pal(tmp_path, monkeypatch):
    p = FakePal(tmp_path)
    monkeypatch.setattr(snaps, "_pal", lambda: p)
    monkeypatch.setattr(snaps, "SCHEDULES_FILE", str(tmp_path / "schedules.json"))
    monkeypatch.setattr(snaps, "_set_previous_versions", lambda share, on: None)
    return p


def test_a_whole_share_rolls_back_with_the_current_state_kept_first(pal):
    (pal.live / "a.jpg").write_text("old a")
    (pal.live / "album").mkdir()
    (pal.live / "album" / "b.jpg").write_text("old b")
    pal.create_snapshot("tank", "photos", "photos@auto-20261027-1000")
    (pal.live / "a.jpg").write_text("ransomware")
    (pal.live / "new.jpg").write_text("added later")
    import shutil

    shutil.rmtree(pal.live / "album")
    res = snaps.rollback("photos@auto-20261027-1000", pal=pal, pool_id="tank")
    assert (pal.live / "a.jpg").read_text() == "old a" and (pal.live / "album" / "b.jpg").read_text() == "old b"
    assert not (pal.live / "new.jpg").exists()
    safety = res["safety_snapshot"]
    assert safety.startswith("photos@before-rollback-") and safety in pal.created
    assert (pal.snapdir / safety / "new.jpg").read_text() == "added later"  # the rollback can be undone


def test_nothing_changes_without_the_safety_snapshot(pal):
    (pal.live / "a.jpg").write_text("now")
    pal.create_snapshot("tank", "photos", "photos@auto-20261027-1000")
    (pal.live / "a.jpg").write_text("newer")
    pal.snapshot_ok = False
    with pytest.raises(RuntimeError, match="nothing was changed"):
        snaps.rollback("photos@auto-20261027-1000", pal=pal, pool_id="tank")
    assert (pal.live / "a.jpg").read_text() == "newer"


def test_only_a_share_snapshot_can_roll_a_share_back(pal):
    with pytest.raises(ValueError):
        snaps.rollback("pool-wide-snapshot", pal=pal, pool_id="tank")


def test_a_new_share_gets_snapshots_on_by_default(pal, monkeypatch):
    monkeypatch.setattr(snaps, "availability", lambda pal=None: (True, ""))
    assert snaps.ensure_default("photos") is True
    sched = snaps.list_schedules()[0]
    assert (sched["every"], sched["keep"], sched["keep_daily"]) == ("hourly", 24, 30)
    assert snaps.ensure_default("photos") is False  # already has one
    monkeypatch.setattr(snaps, "availability", lambda pal=None: (False, "no tools"))
    assert snaps.ensure_default("music") is False


def test_existing_shares_without_snapshots_get_an_advisor_fix(pal, monkeypatch):
    monkeypatch.setattr(snaps, "availability", lambda pal=None: (True, ""))
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: pal)
    found = {f["id"]: f for f in safe_defaults_advisor.findings()}
    assert "photos" in found["snapshots_off"]["details"]
    assert "photos" in safe_defaults_advisor.apply_fix("snapshots_off")
    assert "snapshots_off" not in {f["id"] for f in safe_defaults_advisor.findings()}


def test_no_snapshot_advice_where_snapshots_cannot_run(pal, monkeypatch):
    monkeypatch.setattr(snaps, "availability", lambda pal=None: (False, "no tools"))
    assert safe_defaults_advisor._snapshots_finding() is None


@pytest.mark.real_confirmations
def test_rolling_back_asks_first(client, auth_headers):
    res = client.post("/api/snapshots/photos@auto-20261027-1000/rollback", headers=auth_headers)
    assert res.status_code == 428 and res.json()["action"] == "snapshot.rollback"


def test_the_rollback_route_reports_problems(client, auth_headers, monkeypatch):
    def raise_(exc):
        def f(name):
            raise exc

        return f

    for exc, code in ((FileNotFoundError("gone"), 404), (ValueError("bad"), 400), (RuntimeError("no safety"), 409)):
        monkeypatch.setattr(snaps, "rollback", raise_(exc))
        assert client.post("/api/snapshots/x@y/rollback", headers=auth_headers).status_code == code
    monkeypatch.setattr(snaps, "rollback", lambda name: {"share": "x", "safety_snapshot": "x@before"})
    assert client.post("/api/snapshots/x@y/rollback", headers=auth_headers).json()["safety_snapshot"] == "x@before"


@pytest.mark.real_storage_tools
def test_a_missing_btrfs_is_not_reported_as_a_snapshot(tmp_path, monkeypatch):
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter

    adapter = GenericLinuxStorageAdapter.__new__(GenericLinuxStorageAdapter)
    adapter._pool_path = str(tmp_path)
    monkeypatch.setattr(adapter, "_run_cmd", lambda cmd: (127, "", "btrfs: not found"))
    assert adapter.create_snapshot("p", "photos", "photos@auto-1")["status"] == "error"
    assert os.path.isdir(tmp_path / "@snapshots")
