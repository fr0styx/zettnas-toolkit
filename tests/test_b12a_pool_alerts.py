"""B12a (REL-11 / FEAT-05): degraded pools, disks out, disk and scrub errors and 85 % / 95 %
full become alerts and Overview items, and a weekly health report goes out."""

import time

from backend.hardware.pal.base import PoolMember, StoragePool
from backend.services import pool_alerts, status_summary


def _pool(**kw):
    base = dict(
        id="tank", name="tank", pool_type="zfs_pool", fs_type="zfs", total_bytes=1000, used_bytes=100, used_pct=10.0
    )
    return StoragePool(**{**base, **kw})


def _kinds(items):
    return sorted((i["kind"], i["level"]) for i in items)


# --- reading scrub results ---------------------------------------------------------------------


def test_zpool_scan_lines():
    done = "  scan: scrub repaired 0B in 00:10:12 with 3 errors on Sun Oct 12 00:34:13 2025\n"
    got = pool_alerts.parse_zpool_scan("pool: tank\n state: ONLINE\n" + done)
    assert got["state"] == "finished" and got["errors"] == 3 and got["finished_at"]
    assert pool_alerts.parse_zpool_scan("  scan: none requested")["state"] == "never"
    assert pool_alerts.parse_zpool_scan("  scan: scrub in progress since Sun Oct 12")["state"] == "running"
    assert pool_alerts.parse_zpool_scan("no scan line") is None


def test_btrfs_scrub_status():
    raw = """UUID: 1234
Scrub started:    Sun Oct 12 00:00:01 2025
Status:           finished
Duration:         0:01:02
\tdata_extents_scrubbed: 10
\tread_errors: 1
\tcsum_errors: 2
\tverify_errors: 0
\tsuper_errors: 0
\tuncorrectable_errors: 0
\tcorrected_errors: 5
"""
    got = pool_alerts.parse_btrfs_scrub(raw)
    assert got["state"] == "finished" and got["errors"] == 3 and got["finished_at"]
    assert pool_alerts.parse_btrfs_scrub("UUID: 1\n\tno stats available\n")["state"] == "never"


def test_unraid_reports_the_last_parity_check(monkeypatch):
    from backend.hardware.pal import unraid

    adapter = unraid.UnraidStorageAdapter.__new__(unraid.UnraidStorageAdapter)
    monkeypatch.setattr(
        unraid, "read_unraid_status", lambda: {"last_parity_check": {"errors": 7, "finished_at": 1790000000, "exit": 0}}
    )
    got = adapter.scrub_result(_pool(id="unraid_array", fs_type="xfs", pool_type="unraid_array"))
    assert got == {"state": "finished", "errors": 7, "finished_at": 1790000000.0}
    monkeypatch.setattr(unraid, "read_unraid_status", lambda: {"last_parity_check": {"finished_at": None}})
    assert adapter.scrub_result(_pool(id="unraid_array"))["state"] == "never"


# --- what is wrong -----------------------------------------------------------------------------


def test_a_healthy_pool_has_nothing_to_say():
    assert pool_alerts.problems([_pool()], {"tank": {"errors": 0}}) == []


def test_every_kind_of_problem():
    pool = _pool(
        status="DEGRADED",
        used_pct=96.0,
        members=[
            PoolMember(name="disk1", device="sdb", status="DISK_DSBL"),
            PoolMember(name="disk2", device="sdc", num_errors=4),
            PoolMember(name="disk3", device="sdd", status="STANDBY"),
        ],
    )
    got = pool_alerts.problems([pool], {"tank": {"errors": 2}})
    assert _kinds(got) == [
        ("disk_disabled", "critical"),
        ("disk_errors", "warning"),
        ("pool_degraded", "critical"),
        ("pool_full", "critical"),
        ("scrub_errors", "critical"),
    ]
    assert got[-1]["level"] == "warning"  # critical first


def test_85_percent_warns_and_95_is_critical():
    assert _kinds(pool_alerts.problems([_pool(used_pct=86.0)])) == [("pool_full", "warning")]
    assert _kinds(pool_alerts.problems([_pool(used_pct=95.0)])) == [("pool_full", "critical")]
    assert pool_alerts.problems([_pool(used_pct=99.0, total_bytes=0)]) == []  # nothing to measure


# --- alerts ------------------------------------------------------------------------------------


def _alerts(monkeypatch, items):
    monkeypatch.setattr(pool_alerts, "current", lambda max_age=0, now=None: items)
    sent = []
    return sent, lambda **kw: sent.append(kw)


def test_a_new_problem_alerts_once_and_a_critical_one_daily(monkeypatch):
    degraded = {
        "id": "pool:tank:degraded",
        "level": "critical",
        "kind": "pool_degraded",
        "subject": "tank",
        "detail": "DEGRADED",
    }
    sent, send = _alerts(monkeypatch, [degraded])
    now = time.time()
    assert pool_alerts.check_and_alert(now, send=send)["new"] == ["pool:tank:degraded"]
    assert pool_alerts.check_and_alert(now + 600, send=send) == {"new": [], "reminded": [], "fixed": []}
    assert pool_alerts.check_and_alert(now + 86400 + 1, send=send)["reminded"] == ["pool:tank:degraded"]
    assert [s["level"] for s in sent] == ["critical", "critical"] and "degraded" in sent[0]["title"]


def test_a_fixed_problem_gets_a_note(monkeypatch):
    full = {"id": "pool:tank:full", "level": "warning", "kind": "pool_full", "subject": "tank", "detail": "88%"}
    sent, send = _alerts(monkeypatch, [full])
    pool_alerts.check_and_alert(time.time(), send=send)
    monkeypatch.setattr(pool_alerts, "current", lambda max_age=0, now=None: [])
    assert pool_alerts.check_and_alert(time.time(), send=send)["fixed"] == ["pool:tank:full"]
    assert "fixed" in sent[-1]["title"] and sent[-1]["level"] == "info"


def test_a_warning_that_turns_critical_alerts_again(monkeypatch):
    item = {"id": "pool:tank:full", "level": "warning", "kind": "pool_full", "subject": "tank", "detail": "88%"}
    sent, send = _alerts(monkeypatch, [item])
    pool_alerts.check_and_alert(time.time(), send=send)
    item.update(level="critical", detail="96%")
    assert pool_alerts.check_and_alert(time.time(), send=send)["new"] == ["pool:tank:full"]


def test_the_scheduler_checks_every_five_minutes_only(monkeypatch):
    calls = []
    monkeypatch.setattr(pool_alerts, "current", lambda max_age=0, now=None: calls.append(1) or [])
    monkeypatch.setattr("backend.services.notifications.send_notification", lambda **kw: None)
    pool_alerts._last_check["at"] = 0.0
    now = time.time()
    pool_alerts.check_and_alert(now)
    pool_alerts.check_and_alert(now + 60)
    pool_alerts.check_and_alert(now + 301)
    assert len(calls) == 2


# --- the Overview and the weekly report ----------------------------------------------------------


def test_the_overview_lists_pool_problems_and_skips_the_old_storage_line(monkeypatch):
    full = {"id": "pool:tank:full", "level": "critical", "kind": "pool_full", "subject": "tank", "detail": "96%"}
    monkeypatch.setattr(pool_alerts, "current", lambda max_age=pool_alerts.CACHE_S, now=None: [full])
    monkeypatch.setattr("backend.hardware.storage.read_storage", lambda: {"pct": 96})
    items = status_summary.summary()["items"]
    assert [i["kind"] for i in items].count("pool_full") == 1
    assert "storage_full" not in [i["kind"] for i in items]
    assert next(i for i in items if i["kind"] == "pool_full")["open"] == "storage"


def _sunday_9():
    t = time.localtime()
    days = (6 - t.tm_wday) % 7
    base = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 9, 5, 0, 0, 0, -1))
    return base + days * 86400


def test_the_weekly_report_goes_out_on_sunday_morning_once(monkeypatch):
    monkeypatch.setattr(pool_alerts, "weekly_report", lambda now=None: ("Weekly", "Everything looks fine."))
    sent = []
    sunday = _sunday_9()
    assert pool_alerts.send_weekly_if_due(sunday, send=lambda **kw: sent.append(kw)) is True
    assert pool_alerts.send_weekly_if_due(sunday + 600, send=lambda **kw: sent.append(kw)) is False
    assert pool_alerts.send_weekly_if_due(sunday + 86400, send=lambda **kw: sent.append(kw)) is False  # Monday
    assert len(sent) == 1 and sent[0]["event_type"] == "health"


def test_the_weekly_report_says_how_things_are(monkeypatch):
    class Adapter:
        def list_pools(self):
            return [_pool(used_pct=42.0)]

        def scrub_result(self, pool):
            return {"state": "finished", "errors": 0, "finished_at": time.time() - 3 * 86400 - 600}

    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: Adapter())
    monkeypatch.setattr(pool_alerts, "current", lambda max_age=0, now=None: [])
    monkeypatch.setattr("backend.services.backup_watch.overdue_backups", lambda now=None: [])
    from backend.state import Z_STATE

    # no drive verdicts of its own: none left over from another test (seen in random order)
    monkeypatch.setattr(Z_STATE, "drive_verdicts", {})
    title, body = pool_alerts.weekly_report()
    assert "weekly" in title.lower() and "Everything looks fine." in body
    assert "tank: 42% used" in body and "3 day(s) ago with 0 errors" in body and "all on time" in body


def test_the_daily_summary_and_weekly_switch_are_saved(client, auth_headers):
    from backend.services.notifications import load_notification_config

    cfg = client.get("/api/notifications/config", headers=auth_headers).json()
    cfg.update(digest_mode="daily", digest_hour=7, weekly_report=False)
    res = client.post("/api/notifications/config", json=cfg, headers=auth_headers)
    assert res.status_code == 200, res.text
    saved = load_notification_config()
    assert (saved["digest_mode"], saved["digest_hour"], saved["weekly_report"]) == ("daily", 7, False)
    assert pool_alerts.send_weekly_if_due(_sunday_9(), send=lambda **kw: None) is False  # switched off


def test_people_can_ask_for_storage_and_weekly_alerts():
    from backend.services.notifications import ROUTABLE_EVENTS

    assert {"storage", "health"} <= set(ROUTABLE_EVENTS)


class _Cmd:
    """An adapter whose commands answer from a table."""

    def __init__(self, answers):
        self.answers, self.ran = answers, []

    def __call__(self, cmd):
        self.ran.append(cmd)
        return self.answers.get(cmd[0], (1, "", "missing"))


def test_the_storage_layer_reads_zfs_and_btrfs_scrubs(monkeypatch):
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter

    adapter = GenericLinuxStorageAdapter.__new__(GenericLinuxStorageAdapter)
    run = _Cmd(
        {
            "zpool": (0, "  scan: scrub repaired 0B in 00:01:00 with 1 errors on Sun Oct 12 00:34:13 2025", ""),
            "btrfs": (0, "Status: finished\n\tcsum_errors: 2\n", ""),
        }
    )
    monkeypatch.setattr(adapter, "_run_cmd", run)
    assert adapter.scrub_result(_pool())["errors"] == 1
    assert (
        adapter.scrub_result(_pool(id="b", fs_type="btrfs", pool_type="btrfs_raid", mountpoint="/mnt/b"))["errors"] == 2
    )
    assert adapter.scrub_result(_pool(id="x", fs_type="xfs", pool_type="single")) is None
    run.answers = {}
    assert adapter.scrub_result(_pool()) is None  # the command failed


def test_unraid_cache_pools_use_the_usual_reading(monkeypatch):
    from backend.hardware.pal import unraid

    adapter = unraid.UnraidStorageAdapter.__new__(unraid.UnraidStorageAdapter)
    monkeypatch.setattr(adapter, "_run_cmd", _Cmd({"zpool": (0, "  scan: none requested", "")}))
    assert adapter.scrub_result(_pool(id="cache"))["state"] == "never"


def test_the_scheduler_runs_the_pool_checks_and_survives_a_failure(monkeypatch):
    from backend.services import scheduler

    calls = []
    monkeypatch.setattr(pool_alerts, "check_and_alert", lambda now: calls.append("check"))
    monkeypatch.setattr(pool_alerts, "send_weekly_if_due", lambda now: calls.append("weekly"))
    scheduler._run_pool_checks(time.time())
    assert calls == ["check", "weekly"]
    monkeypatch.setattr(pool_alerts, "check_and_alert", lambda now: 1 / 0)
    scheduler._run_pool_checks(time.time())  # logged, not raised
