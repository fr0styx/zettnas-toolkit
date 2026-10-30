"""NARC-2: one "is this disk asleep" probe for the whole app, with one rule and one cache."""

import subprocess

import pytest

from backend.hardware import disks, power_state, smart_engine
from backend.services import rag_standby

STANDBY_OUT = "Device is in STANDBY mode, exit(2)"
OPEN_FAILED = "Smartctl open device: /dev/sdz failed: No such device"


@pytest.fixture
def runs(monkeypatch):
    power_state.forget()
    calls = []
    answer = {"rc": 2, "out": STANDBY_OUT}

    def run(cmd, **kw):
        calls.append(cmd)
        if answer.get("raise"):
            raise answer["raise"]
        return subprocess.CompletedProcess(cmd, answer["rc"], answer["out"], "")

    monkeypatch.setattr(subprocess, "run", run)
    yield calls, answer
    power_state.forget()


def test_one_probe_and_one_cache(runs):
    calls, answer = runs
    assert power_state.probe("/dev/sdx") == power_state.STANDBY
    assert power_state.probe("sdx") == power_state.STANDBY  # from the cache: no second smartctl
    assert len(calls) == 1 and calls[0][:4] == ["smartctl", "-n", "standby", "-i"]
    answer.update(rc=0, out="Power mode is: ACTIVE or IDLE")
    assert power_state.probe("sdx", max_age=0) == power_state.ACTIVE
    assert power_state.probe("sdx", "sat", max_age=0, path="/host/dev/sdx") == power_state.ACTIVE
    assert calls[-1] == ["smartctl", "-n", "standby", "-i", "-d", "sat", "/host/dev/sdx"]


def test_a_drive_that_cant_be_opened_is_not_asleep(runs):
    calls, answer = runs
    answer.update(rc=2, out=OPEN_FAILED)
    assert power_state.probe("sdz") == power_state.UNREACHABLE
    assert power_state.asleep(power_state.UNREACHABLE) is False
    assert rag_standby.is_backing_disk_in_standby("sdz", check_smartctl=True) is False  # the old rule said asleep


def test_unknown_answers_and_the_callers_policy(runs):
    calls, answer = runs
    answer["raise"] = subprocess.TimeoutExpired("smartctl", 6)
    assert power_state.probe("sdw") == power_state.UNKNOWN
    answer["raise"] = FileNotFoundError("no smartctl")
    assert power_state.probe("sdw") == power_state.UNKNOWN
    assert power_state.asleep(power_state.UNKNOWN) is True  # DEFER: leave it alone
    assert power_state.asleep(power_state.UNKNOWN, power_state.CHECK) is False
    assert power_state.probe("nvme0n1") == power_state.ACTIVE and power_state.probe("") == power_state.UNKNOWN
    assert len(calls) == 2  # an unknown answer isn't cached; NVMe and an empty name start nothing


def test_an_unplaced_path_follows_the_callers_policy(monkeypatch):
    monkeypatch.delenv("ZETTNAS_STANDBY_UNKNOWN", raising=False)
    unknown = rag_standby.UNKNOWN_BACKING_DEV
    assert rag_standby.is_backing_disk_in_standby(unknown) is True
    assert rag_standby.is_backing_disk_in_standby(unknown, unknown=power_state.CHECK) is False
    monkeypatch.setenv("ZETTNAS_STANDBY_UNKNOWN", "allow")
    assert rag_standby.is_backing_disk_in_standby(unknown) is False


def test_every_caller_uses_it(runs):
    calls, answer = runs
    assert disks.is_drive_asleep("sdv") is True
    assert smart_engine.SmartTelemetryEngine.is_device_sleeping("/dev/sdu") is True
    assert rag_standby.is_backing_disk_in_standby("sdt", check_smartctl=True) is True
    assert all(c[:4] == ["smartctl", "-n", "standby", "-i"] for c in calls)
    assert not any("hdparm" in c[0] for c in calls)
    assert disks.Z_STATE.cached_smart_data["sdt"][1] == "standby"  # the rest of the app sees it
