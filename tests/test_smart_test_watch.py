"""The SMART self-test tracker: it records how a test ended, and never records a pass it did
not see (smartctl saying nothing used to count as "passed")."""

import json
import subprocess
import time

import pytest

from backend.hardware import disks
from backend.state import Z_STATE


def _ata_doc(status_value, status_string, log=None):
    doc = {"ata_smart_data": {"self_test": {"status": {"value": status_value, "string": status_string}}}}
    if log is not None:
        doc["ata_smart_self_test_log"] = {"standard": {"table": log}}
    return doc


@pytest.fixture
def watch(monkeypatch):
    out = {"doc": None, "raw": "", "code": 0}
    events, logged, notes = [], [], []

    def run(cmd, **kw):
        if "-j" in cmd:
            return subprocess.CompletedProcess(cmd, out["code"], json.dumps(out["doc"]) if out["doc"] else "", "")
        return subprocess.CompletedProcess(cmd, out["code"], out["raw"], "")

    monkeypatch.setattr(disks.subprocess, "run", run)
    monkeypatch.setattr(disks, "_resolve_dev_path", lambda d: "/dev/" + d)
    monkeypatch.setattr(disks, "_get_smart_device_type", lambda d, nvme=False: "sat")
    monkeypatch.setattr(disks, "add_event", lambda **kw: events.append(kw))
    monkeypatch.setattr(disks, "log_smart_test_result", lambda **kw: logged.append(kw))
    monkeypatch.setattr(disks, "send_notification", lambda **kw: notes.append(kw))
    with Z_STATE.lock:
        saved = dict(Z_STATE.active_smart_tests)
        Z_STATE.active_smart_tests.clear()
        Z_STATE.active_smart_tests["sdb"] = {
            "start_time": time.time() - 120,
            "test_type": "short",
            "model": "WD Red",
            "serial": "WX1",
        }
    yield out, events, logged, notes
    with Z_STATE.lock:
        Z_STATE.active_smart_tests.clear()
        Z_STATE.active_smart_tests.update(saved)


def test_no_answer_from_smartctl_is_not_a_pass(watch):
    out, events, logged, _ = watch
    out["raw"] = "Error: timed out"
    disks.check_active_smart_tests()
    assert "sdb" in Z_STATE.active_smart_tests  # still waiting for a real result
    assert events == [] and logged == []


def test_after_two_days_without_an_answer_the_result_is_unknown(watch):
    out, events, logged, _ = watch
    with Z_STATE.lock:
        Z_STATE.active_smart_tests["sdb"]["start_time"] = time.time() - disks.UNREADABLE_TEST_GIVE_UP_S - 60
    disks.check_active_smart_tests()
    assert "sdb" not in Z_STATE.active_smart_tests and logged == []
    assert events[0]["details"]["status"] == "UNKNOWN" and events[0]["details"]["passed"] is False


def test_progress_is_tracked_while_running(watch):
    out, events, _, _ = watch
    out["doc"] = _ata_doc(243, "Self-test routine in progress...")
    disks.check_active_smart_tests()
    assert Z_STATE.active_smart_tests["sdb"]["last_pct"] == 70 and events == []


def test_a_passed_test_is_recorded(watch):
    out, events, logged, notes = watch
    out["doc"] = _ata_doc(
        0,
        "completed without error",
        [
            {
                "type": {"string": "Short offline"},
                "status": {"string": "Completed without error", "passed": True},
                "lifetime_hours": 9001,
            }
        ],
    )
    disks.check_active_smart_tests()
    assert logged[0]["status"] == "PASSED" and logged[0]["passed"] is True
    assert "/dev/sdb" in logged[0]["report_markdown"] and "PASSED" in logged[0]["report_markdown"]
    assert events[0]["level"] == "success" and notes == [] and "sdb" not in Z_STATE.active_smart_tests


def test_a_failed_test_is_recorded_and_notified(watch):
    out, events, logged, notes = watch
    out["doc"] = _ata_doc(
        0,
        "completed",
        [
            {
                "type": {"string": "Extended offline"},
                "status": {"string": "Completed: read failure", "passed": False},
                "lifetime_hours": 9001,
                "lba_first_error": 123456,
            }
        ],
    )
    disks.check_active_smart_tests()
    assert logged[0]["status"] == "FAILED" and logged[0]["lba_first_error"] == 123456
    assert notes and notes[0]["level"] == "critical"


def test_an_aborted_test_is_a_warning_without_a_notification(watch):
    out, events, logged, notes = watch
    out["doc"] = _ata_doc(1, "aborted by host")
    disks.check_active_smart_tests()
    assert logged[0]["status"] == "ABORTED" and events[0]["level"] == "warning" and notes == []


def test_a_sleeping_disk_is_left_alone(watch):
    out, events, logged, _ = watch
    out["code"] = 2  # smartctl -n standby: the disk is asleep
    disks.check_active_smart_tests()
    assert "sdb" in Z_STATE.active_smart_tests and logged == []


def test_report_markdown_sections():
    md = disks.generate_smart_test_report_markdown(
        "nvme0n1",
        "short",
        "completed",
        True,
        model="Samsung 990",
        serial="S1",
        duration_sec=75,
        power_on_hours=1234,
        temp_start=41,
        temp_end=None,
        is_nvme=True,
        metrics={"nvme_spare": 100, "nvme_used": 2, "tbw_tb": 12.5},
        recommendation="Fine.",
    )
    assert "PASSED" in md and "1m 15s" in md and "1,234 hours" in md and "41°C (start) -> --" in md
    assert "Available Spare**: 100%" in md and "Total Bytes Written**: 12.5 TB" in md and "Fine." in md
    hdd = disks.generate_smart_test_report_markdown(
        "sda", "long", "aborted by host", False, duration_sec=9, metrics={"realloc": 3}
    )
    assert "ABORTED" in hdd and "9s" in hdd and "Reallocated Sectors**: 3" in hdd and "SATA / SAS" in hdd
