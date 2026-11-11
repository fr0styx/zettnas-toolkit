"""SET-13: every alert is an entry in the event log, at the moment it is sent. Twelve kinds of
alert (a failed backup, a degraded pool, a stopped sync) reached a phone and left no trace."""

import pathlib
import re

import pytest

from backend import db, event_store, state
from backend.services import notifications as n

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "history.db"))
    monkeypatch.setattr(state, "EVENTS_FILE", str(tmp_path / "events.json"))
    monkeypatch.setattr(event_store, "_state", {"table_in": "", "pruned": 0.0, "said": 0.0})
    monkeypatch.setattr(state.Z_STATE, "event_log", [])
    monkeypatch.setattr(n, "load_notification_config", lambda: {"enabled": False, "push_enabled": False})
    monkeypatch.setattr(n, "_route_to_people", lambda *a, **k: [])
    n._logged.clear()
    state._event_unsaved.clear()
    state._event_recent.clear()
    yield state.events_snapshot
    n._logged.clear()


def test_an_alert_is_written_even_when_no_channel_is_set_up(log):
    res = n.send_notification(
        "Backup failed: Photos",
        "Backup job 'Photos' failed: disk full",
        level="error",
        event_type="backup",
        text=n.alert_text("backup_failed", name="Photos", error="disk full"),
    )
    assert res == {"dispatched": False, "reason": "disabled"}
    (entry,) = log()
    assert entry["level"] == "error" and entry["title"] == "Backup failed: Photos"
    assert entry["kind"] == "backup_failed" and entry["link"] == "backup"
    assert entry["details"]["title_key"] == "alert.backup_failed.title" and entry["details"]["alert"] == "backup"


def test_a_finished_backup_is_green_and_an_alert_without_a_name_leads_by_its_type(log):
    n.send_notification(
        {
            "type": "backup",
            "title": "Backup succeeded: Photos",
            "message": "ok",
            "level": "info",
            "text": n.alert_text("backup_ok", name="Photos"),
        }
    )
    n.send_notification({"type": "sync", "title": "Cloud Sync Failed: Copy", "message": "no route", "level": "error"})
    n.send_notification("S.M.A.R.T. Hardware Failure: /dev/sdb", "failed", level="critical", event_type="smart")
    n.send_notification("Something general", "x", level="normal")
    smart, sync, backup = log()[1:]
    assert backup["level"] == "success" and backup["link"] == "backup"
    assert sync["link"] == "backup" and "kind" not in sync and sync["details"] == {"alert": "sync", "link": "backup"}
    assert smart["level"] == "critical" and smart["link"] == "drives"
    assert log()[0]["level"] == "info" and "link" not in log()[0]


def test_an_alert_raised_again_within_its_cooldown_is_not_written_again(log, monkeypatch):
    clock = {"t": 1_700_000_000.0}
    monkeypatch.setattr(n.time, "time", lambda: clock["t"])
    for _ in range(3):
        n.send_notification(
            "Pool degraded", "tank lost a disk", level="warning", event_type="storage", dedup_key="pool-tank"
        )
        clock["t"] += 300
    assert len(log()) == 1 and "count" not in log()[0]
    n.send_notification("Pool failed", "tank is gone", level="critical", event_type="storage", dedup_key="pool-tank")
    assert len(log()) == 2  # worse than before: written at once
    n.send_notification("Pool failed", "tank is gone", level="critical", event_type="storage", dedup_key="pool-tank")
    assert len(log()) == 2
    clock["t"] += 1800
    n.send_notification(
        "Pool degraded", "tank lost a disk", level="warning", event_type="storage", dedup_key="pool-tank"
    )
    # after the cooldown it is written again: the same report within the hour is counted on its entry
    assert len(log()) == 2 and log()[0]["title"] == "Pool degraded" and log()[0]["count"] == 2


def test_a_caller_with_its_own_entry_opts_out_and_a_quiet_job_is_only_logged(log, monkeypatch):
    n.send_notification("UPS: the safe shutdown starts", "now", level="critical", event_type="ups", record=False)
    n.send_notification(
        {"type": "system", "title": "Alert Resolved", "message": "fine", "level": "info", "record": False}
    )
    assert log() == []
    sent = []
    monkeypatch.setattr(n, "_dispatch_shared", lambda *a, **k: sent.append(a) or {"dispatched": True, "channels": {}})
    monkeypatch.setattr(n, "load_notification_config", lambda: {"enabled": True, "push_enabled": False})
    res = n.send_notification(
        {"type": "backup", "title": "Backup succeeded: Quiet", "message": "ok", "level": "info", "deliver": False}
    )
    assert res == {"dispatched": False, "reason": "recorded only"} and sent == []
    assert [e["title"] for e in log()] == ["Backup succeeded: Quiet"]
    n.send_notification({"type": "backup", "title": "Backup succeeded: Loud", "message": "ok", "level": "info"})
    assert len(sent) == 1 and len(log()) == 2


def test_the_shared_log_names_the_threat_not_the_file(log, monkeypatch):
    from backend.services import malware_scan

    told = []
    monkeypatch.setattr(n, "send_notification", lambda *a, **k: told.append((a, k)))
    malware_scan._alert({"name": "tax-return-2026.pdf", "threat": "Eicar-Test-Signature"})
    (entry,) = log()
    assert "tax-return" not in entry["message"] and "Eicar-Test-Signature" in entry["message"]
    assert entry["kind"] == "malware_found" and told[0][1]["record"] is False
    assert "tax-return-2026.pdf" in told[0][0][1]  # the alert to the owner's channels still names it


# Callers that write their own entry for the same thing, or whose alerts are kept out of the log
# that everyone with the view right reads: they must say so, or the log shows the thing twice.
OPT_OUT = {
    "backend/services/alert_rules.py": 2,
    "backend/services/copy_engine.py": 4,
    "backend/services/drive_alerts.py": 1,
    "backend/services/frigate_events.py": 1,
    "backend/services/malware_scan.py": 1,
    "backend/services/ransomware_guard.py": 1,
    "backend/services/security_alerts.py": 1,
    "backend/services/self_updater.py": 1,
    "backend/services/stats_collector.py": 1,
    "backend/services/ups_watchdog.py": 3,
}


def test_the_callers_that_opt_out_are_the_ones_listed():
    found = {}
    for path in sorted((ROOT / "backend").rglob("*.py")):
        hits = len(re.findall(r"record=False|\"record\": False", path.read_text(encoding="utf-8")))
        if hits:
            found[str(path.relative_to(ROOT))] = hits
    assert found == OPT_OUT
