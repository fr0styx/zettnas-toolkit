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
    monkeypatch.setattr(Z_STATE, "critical_temp_active", False, raising=False)
    monkeypatch.setattr(storage, "read_storage", lambda: {"pct": 40})
    monkeypatch.setattr(backup_watch, "overdue_backups", lambda: [])
    monkeypatch.setattr(ransomware_guard, "writes_frozen", lambda: False)
    monkeypatch.setattr(ups, "read_ups_status", lambda: {"status": "OL"})
    monkeypatch.setattr(config, "is_using_default_password", lambda: False)
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
