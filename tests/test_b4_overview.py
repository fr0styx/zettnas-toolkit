"""UX-1: what needs attention, for the Overview."""

import pytest

from backend.services import status_summary


@pytest.fixture
def quiet(monkeypatch):
    """A healthy server: every source says all is well."""
    from backend import config
    from backend.hardware import storage, ups
    from backend.services import backup_watch, ransomware_guard
    from backend.state import Z_STATE

    monkeypatch.setattr(Z_STATE, "cached_smart_data", {"sda": (30, "ok"), "sdb": (None, "standby")})
    monkeypatch.setattr(Z_STATE, "drive_verdicts", {})
    monkeypatch.setattr(Z_STATE, "critical_temp_active", False, raising=False)
    monkeypatch.setattr(storage, "read_storage", lambda: {"pct": 40})
    monkeypatch.setattr(backup_watch, "overdue_backups", lambda: [])
    monkeypatch.setattr(ransomware_guard, "writes_frozen", lambda: False)
    monkeypatch.setattr(ups, "read_ups_status", lambda: {"status": "OL"})
    monkeypatch.setattr(config, "is_using_default_password", lambda: False)
    # the pool alerts cache their answer for 5 minutes: a "pool full" an earlier test left there
    # must not reach these tests
    from backend.services import pool_alerts

    monkeypatch.setattr(pool_alerts, "current", lambda *a, **k: [])
    return monkeypatch


def test_a_healthy_server_has_nothing_to_report(quiet):
    assert status_summary.summary() == {"ok": True, "items": []}


def test_problems_are_listed_worst_first(quiet):
    from backend import config
    from backend.hardware import storage, ups
    from backend.services import backup_watch, ransomware_guard
    from backend.state import Z_STATE

    quiet.setattr(Z_STATE, "cached_smart_data", {"sda": (30, "warn"), "sdb": (40, "crit")})
    quiet.setattr(Z_STATE, "critical_temp_active", True, raising=False)
    quiet.setattr(storage, "read_storage", lambda: {"pct": 98})
    quiet.setattr(backup_watch, "overdue_backups", lambda: [{"id": "j1", "name": "Photos"}])
    quiet.setattr(ransomware_guard, "writes_frozen", lambda: True)
    quiet.setattr(ups, "read_ups_status", lambda: {"status": "OB DISCHRG"})
    quiet.setattr(config, "is_using_default_password", lambda: True)
    out = status_summary.summary()
    kinds = [i["kind"] for i in out["items"]]
    assert not out["ok"]
    assert set(kinds) == {
        "drive_warning",
        "drive_failing",
        "storage_full",
        "backup_overdue",
        "writes_frozen",
        "on_battery",
        "too_hot",
        "default_password",
    }
    levels = [i["level"] for i in out["items"]]
    assert levels == sorted(levels, key=lambda lv: 0 if lv == "critical" else 1)


def test_nearly_full_is_a_warning_and_a_broken_check_is_skipped(quiet):
    from backend.hardware import storage
    from backend.services import backup_watch

    quiet.setattr(storage, "read_storage", lambda: {"pct": 91})
    quiet.setattr(backup_watch, "overdue_backups", lambda: 1 / 0)
    out = status_summary.summary()
    assert out["items"] == [
        {"id": "storage:full", "level": "warning", "kind": "storage_full", "subject": "91%", "open": "storage"}
    ]


def test_the_endpoint_answers(client, auth_headers, quiet):
    r = client.get("/api/system/status-summary", headers=auth_headers)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_drive_health_verdicts_decide_what_the_overview_says(quiet):
    import time

    from backend.state import Z_STATE

    now = time.time()
    quiet.setattr(Z_STATE, "cached_smart_data", {"sda": (30, "crit"), "sdb": (40, "ok"), "sdz": (35, "warn")})
    quiet.setattr(
        Z_STATE,
        "drive_verdicts",
        {
            "sda": {"verdict": "ok", "kind": "", "summary": "No sign of trouble.", "ts": now},
            "sdb": {"verdict": "now", "kind": "replace", "summary": "8 sectors could not be read", "ts": now},
            "sdc": {"verdict": "soon", "kind": "cooling", "summary": "The drive is too hot", "ts": now},
            "sdd": {"verdict": "watch", "kind": "replace", "summary": "An old drive", "ts": now},
            "sde": {"verdict": "now", "kind": "replace", "summary": "gone", "ts": now - 3 * 3600},
        },
    )
    items = {i["subject"]: i for i in status_summary._drives()}
    # Drive Health's verdict wins over the old pass/fail flag; watch-only and stale verdicts stay quiet
    assert set(items) == {"sdb", "sdc", "sdz"}
    assert items["sdb"]["kind"] == "drive_failing" and items["sdb"]["level"] == "critical"
    assert items["sdb"]["detail"] == "8 sectors could not be read"
    assert items["sdc"]["kind"] == "drive_attention" and items["sdc"]["level"] == "warning"
    assert items["sdz"]["kind"] == "drive_warning"  # not judged yet: the old check still speaks
    assert {i["open"] for i in items.values()} == {"drives"}
