"""NARC-1: a drive smartctl can't open or identify is unreachable, not asleep."""

import subprocess

from backend.hardware import disks
from backend.hardware.smart_power import is_standby, smartctl_power

STANDBY = "smartctl 7.4 2023-08-01 r5530\nDevice is in STANDBY mode, exit(2)\n"
SLEEP = "Device is in SLEEP mode, exit(2)\n"
OPEN_FAILED = "Smartctl open device: /dev/sdb failed: No such device\n"
NO_IDENTIFY = "Read Device Identity failed: scsi error unsupported field in scsi command\n"
JSON_STANDBY = (
    '{"smartctl": {"messages": [{"string": "Device is in STANDBY mode, exit(2)", "severity": "information"}]}}'
)


def test_the_message_decides():
    assert smartctl_power(2, STANDBY) == "standby"
    assert smartctl_power(2, SLEEP) == "standby"
    assert smartctl_power(2, JSON_STANDBY) == "standby"
    assert smartctl_power(2, OPEN_FAILED) == "unreachable"
    assert smartctl_power(2, NO_IDENTIFY) == "unreachable"
    assert smartctl_power(6, NO_IDENTIFY) == "unreachable"
    assert smartctl_power(0, "SMART overall-health self-assessment test result: PASSED") == "active"
    assert smartctl_power(4, "some attribute failed") == "active"  # other bits aren't about power
    assert is_standby(2, STANDBY) and not is_standby(2, OPEN_FAILED)


def test_no_call_site_reads_bit_one_as_sleep():
    import inspect

    from backend.hardware import smart_engine

    for mod in (disks, smart_engine):
        src = inspect.getsource(mod)
        assert "returncode & 2" not in src and "returncode == 2" not in src, mod.__name__


def test_an_unreachable_drive_is_a_warning_said_once(monkeypatch):
    events = []
    readings = {}
    monkeypatch.setattr(disks, "add_event", lambda *a, **k: events.append(a))
    monkeypatch.setattr(disks.Z_STATE.smart, "set_reading", lambda dev, t, h: readings.__setitem__(dev, (t, h)))
    disks._UNREACHABLE.discard("sdz")
    disks._note_unreachable("sdz", OPEN_FAILED)
    disks._note_unreachable("sdz", OPEN_FAILED)
    assert readings["sdz"][1] == "warn"
    assert len(events) == 1 and "doesn't answer" in events[0][2]
    disks._UNREACHABLE.discard("sdz")


def test_is_drive_asleep_does_not_hide_a_vanished_drive(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 2, OPEN_FAILED, "")

    monkeypatch.setattr(disks.subprocess, "run", fake_run)
    monkeypatch.setattr(disks, "_get_smart_device_type", lambda *a: "sat", raising=False)
    monkeypatch.setattr(disks, "_resolve_dev_path", lambda d: "/dev/" + d, raising=False)
    assert disks.is_drive_asleep("sdz") is False
    monkeypatch.setattr(disks.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, STANDBY, ""))
    assert disks.is_drive_asleep("sdz") is True
