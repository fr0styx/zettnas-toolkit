"""B12a (REL-12): backups, snapshots and scrubs as protection jobs, with overdue and failed
alerts; a monthly scrub where ZettNAS owns the pools, a clear skip where the host does, and no
scrub of spinning disks unless a person switched it on and confirmed it."""

import time
from types import SimpleNamespace

import pytest

from backend.hardware.pal.base import PlatformCapabilities, PlatformType, PoolMember, StoragePool
from backend.services import protection_jobs, snapshot_service, status_summary

DAY = 86400


def _pool(pid, rotational, **kw):
    members = [PoolMember(name=f"{pid}-a", device="sda", rotational=rotational)]
    return StoragePool(id=pid, name=pid, pool_type="zfs_pool", fs_type="zfs", total_bytes=10, members=members, **kw)


class FakeAdapter:
    def __init__(self, platform=PlatformType.GENERIC_LINUX, pools=(), scrubs=None, busy=False):
        self.platform, self.pools, self.scrubs, self.busy, self.started = platform, list(pools), scrubs or {}, busy, []

    def get_platform_type(self):
        return self.platform

    def get_capabilities(self):
        return PlatformCapabilities(platform=self.platform, is_observer_mode=False, can_trigger_scrub=True)

    def list_pools(self):
        return self.pools

    def scrub_result(self, pool):
        return self.scrubs.get(pool.id)

    def is_storage_busy(self):
        return self.busy

    def trigger_scrub(self, pool_id, action="start"):
        self.started.append(pool_id)
        return {"status": "started"}


@pytest.fixture
def adapter(monkeypatch):
    holder = SimpleNamespace(a=FakeAdapter())
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: holder.a)
    monkeypatch.setattr(snapshot_service, "list_schedules", lambda: [])
    return holder


def _scrub_jobs():
    return {j["id"]: j for j in protection_jobs.jobs() if j["kind"] == "scrub"}


def test_an_ssd_pool_is_checked_monthly_by_default_and_spinning_disks_are_not(adapter):
    now = time.time()
    adapter.a = FakeAdapter(
        pools=[_pool("fast", False), _pool("big", True)],
        scrubs={"fast": {"state": "finished", "errors": 0, "finished_at": now - 5 * DAY}},
    )
    jobs = _scrub_jobs()
    assert jobs["fast"]["status"] == "ok" and jobs["fast"]["enabled"] is True
    assert jobs["big"]["status"] == "off" and "spins up" in jobs["big"]["why"]


def test_a_check_two_months_old_is_overdue(adapter):
    adapter.a = FakeAdapter(
        pools=[_pool("fast", False)],
        scrubs={"fast": {"state": "finished", "errors": 0, "finished_at": time.time() - 70 * DAY}},
    )
    assert _scrub_jobs()["fast"]["status"] == "overdue"
    assert [j["id"] for j in protection_jobs.needing_attention()] == ["fast"]


def test_the_host_runs_its_own_checks_on_unraid_and_truenas(adapter):
    for platform, host in ((PlatformType.UNRAID, "Unraid"), (PlatformType.TRUENAS, "TrueNAS")):
        adapter.a = FakeAdapter(platform=platform, pools=[_pool("tank", True)])
        job = _scrub_jobs()["tank"]
        assert job["status"] == "host_owned" and host in job["why"]
    assert protection_jobs.needing_attention() == []


def test_snapshot_schedules_failed_overdue_and_unavailable(adapter, monkeypatch):
    now = time.time()
    monkeypatch.setattr(
        snapshot_service,
        "list_schedules",
        lambda: [
            {"share": "photos", "every": "daily", "last_run": now - 3600, "last_result": "ok"},
            {"share": "docs", "every": "daily", "last_run": now - 3600, "last_result": "failed: no space"},
            {
                "share": "music",
                "every": "hourly",
                "last_run": now - 5 * 3600,
                "last_result": "ok",
                "created_at": now - 9 * DAY,
            },
        ],
    )
    monkeypatch.setattr(snapshot_service, "availability", lambda pal=None: (True, ""))
    snaps = {j["id"]: j["status"] for j in protection_jobs.jobs() if j["kind"] == "snapshot"}
    assert snaps == {"photos": "ok", "docs": "failed", "music": "overdue"}
    monkeypatch.setattr(snapshot_service, "availability", lambda pal=None: (False, "tools missing"))
    assert {j["status"] for j in protection_jobs.jobs() if j["kind"] == "snapshot"} == {"unavailable"}


def _at_3am(days_from_now=0):
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 3, 10, 0, 0, 0, -1)) + days_from_now * DAY


def test_the_monthly_scrub_starts_at_three_once(adapter):
    old = {"state": "finished", "errors": 0, "finished_at": time.time() - 40 * DAY}
    adapter.a = FakeAdapter(pools=[_pool("fast", False), _pool("big", True)], scrubs={"fast": old, "big": old})
    assert protection_jobs.run_scrubs_due(_at_3am() - 3 * 3600) == []  # midnight: not the hour
    assert protection_jobs.run_scrubs_due(_at_3am()) == ["fast"]  # the spinning pool is off
    assert adapter.a.started == ["zfs:fast"]
    assert protection_jobs.run_scrubs_due(_at_3am() + 60) == []  # just started


def test_no_scrub_while_the_storage_is_busy_or_where_the_host_owns_it(adapter):
    old = {"finished_at": time.time() - 40 * DAY}
    adapter.a = FakeAdapter(pools=[_pool("fast", False)], scrubs={"fast": old}, busy=True)
    assert protection_jobs.run_scrubs_due(_at_3am()) == []
    adapter.a = FakeAdapter(platform=PlatformType.UNRAID, pools=[_pool("fast", False)], scrubs={"fast": old})
    assert protection_jobs.run_scrubs_due(_at_3am()) == []


def test_a_spinning_pool_scrubs_once_switched_on(adapter):
    old = {"finished_at": time.time() - 40 * DAY}
    adapter.a = FakeAdapter(pools=[_pool("big", True)], scrubs={"big": old})
    protection_jobs.set_scrub("big", True)
    assert protection_jobs.run_scrubs_due(_at_3am()) == ["big"]


@pytest.mark.real_confirmations
def test_switching_it_on_for_spinning_disks_asks_first(client, auth_headers, adapter):
    adapter.a = FakeAdapter(pools=[_pool("big", True), _pool("fast", False)])
    res = client.put("/api/protection/scrub/big", json={"enabled": True}, headers=auth_headers)
    assert res.status_code == 428 and res.json()["action"] == "pool.scrub_schedule"
    assert client.put("/api/protection/scrub/fast", json={"enabled": True}, headers=auth_headers).status_code == 200
    assert client.put("/api/protection/scrub/big", json={"enabled": False}, headers=auth_headers).status_code == 200
    assert client.put("/api/protection/scrub/nope", json={"enabled": False}, headers=auth_headers).status_code == 404


def test_the_api_lists_the_jobs(client, auth_headers, adapter):
    adapter.a = FakeAdapter(pools=[_pool("fast", False)])
    jobs = client.get("/api/protection/jobs", headers=auth_headers).json()["jobs"]
    assert any(j["kind"] == "scrub" and j["id"] == "fast" for j in jobs)


def test_late_jobs_are_alerted_and_on_the_overview(adapter, monkeypatch):
    from backend.services import backup_watch

    adapter.a = FakeAdapter(pools=[_pool("fast", False)], scrubs={"fast": {"finished_at": time.time() - 70 * DAY}})
    sent = []
    monkeypatch.setattr("backend.services.notifications.send_notification", lambda *a, **k: sent.append((a, k)))
    protection_jobs._LAST_ALERT["at"] = 0.0
    assert [j["id"] for j in protection_jobs.check_and_alert(time.time())] == ["fast"]
    assert any("monthly check of fast" in a[0] for a, _ in sent)
    assert protection_jobs.check_and_alert(time.time() + 60) == []  # once an hour
    backup_watch._LAST_CHECK["at"] = 0.0
    kinds = [i["kind"] for i in status_summary.summary()["items"]]
    assert "scrub_overdue" in kinds


def test_the_scheduler_starts_due_scrubs(monkeypatch):
    from backend.services import pool_alerts, scheduler

    calls = []
    monkeypatch.setattr(pool_alerts, "check_and_alert", lambda now: None)
    monkeypatch.setattr(pool_alerts, "send_weekly_if_due", lambda now: None)
    monkeypatch.setattr(protection_jobs, "run_scrubs_due", lambda now: calls.append(("scrub", now)))
    scheduler._run_pool_checks(123.0)
    assert calls == [("scrub", 123.0)]  # the alerts run in BackupWatch (REL-18)
    monkeypatch.setattr(protection_jobs, "run_scrubs_due", lambda now: 1 / 0)
    scheduler._run_pool_checks(123.0)  # logged, not raised
