"""ARC-5: fan control behaves exactly as recorded, wherever its code lives.

A grid of situations (chassis, disks, temperatures, zero-RPM, busy storage) runs through the
fan-control step with the hardware replaced by recorders. Its decisions and every fan
command must match tests/golden/fan_control.json, recorded before fan control moved out of
the stats collector. Regenerate only for an intended behaviour change:

    ZETTNAS_UPDATE_GOLDEN=1 pytest tests/test_arc5_fan_control_characterization.py
"""

import importlib
import itertools
import json
import os
import sys
import types

import pytest

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "fan_control.json")

DISK_SETS = {
    "all_flash_cold": [{"dev": "nvme0n1", "role": "cache", "temp": 38}],
    "all_flash_hot": [{"dev": "nvme0n1", "role": "cache", "temp": 61}],
    "mixed_active": [
        {"dev": "sda", "role": "data", "temp": 36},
        {"dev": "sdb", "role": "data", "temp": 44},
        {"dev": "sdc", "role": "data", "temp": 39},
        {"dev": "sdd", "role": "data", "temp": 47},
        {"dev": "nvme0n1", "role": "cache", "temp": 41},
    ],
    "zone1_asleep": [
        {"dev": "sda", "role": "data", "temp": 33, "standby": True},
        {"dev": "sdb", "role": "data", "temp": 34, "standby": True},
        {"dev": "sdc", "role": "data", "temp": 42},
        {"dev": "sdd", "role": "data", "temp": 43},
    ],
    "all_asleep": [
        {"dev": "sda", "role": "data", "temp": 30, "standby": True},
        {"dev": "sdb", "role": "data", "temp": 31, "standby": True},
        {"dev": "nvme0n1", "role": "cache", "temp": 40},
    ],
    "bays_critical": [
        {"dev": "sda", "role": "data", "temp": 41, "bay": 1},
        {"dev": "sdb", "role": "data", "temp": 58, "bay": 5},
        {"dev": "sdc", "role": "data", "temp": 40, "bay": 6},
    ],
}


def _target():
    """The fan-control function and the module that holds it (before or after the move)."""
    try:
        mod = importlib.import_module("backend.services.fan_control")
        return mod.run_fan_control, mod
    except ImportError:
        sc = importlib.import_module("backend.services.stats_collector")
        return sc._run_fan_control, sc


def _scenarios():
    for chassis, disks, cpu, zero_rpm, busy in itertools.product(
        ("d4", "d6u", "d8u"), sorted(DISK_SETS), (45, 88), (False, True), (False, True)
    ):
        if busy and not zero_rpm:
            continue  # storage interlocks only matter for zero-RPM
        yield f"{chassis}|{disks}|cpu{cpu}|zero{int(zero_rpm)}|busy{int(busy)}", chassis, disks, cpu, zero_rpm, busy


def _run(monkeypatch, chassis, disks, cpu, zero_rpm, busy):
    from backend.hardware import pal_storage
    from backend.state import Z_STATE

    fn, mod = _target()
    calls = []

    def apply_zone_pwm(zone, target, *a, **k):
        calls.append(["zone", zone, target, sorted(k.items())])
        return target

    def set_fan_pwm(*a, **k):
        calls.append(["set", list(a), sorted(k.items())])
        return True

    clock = types.SimpleNamespace(time=lambda: 1_790_000_000.0, monotonic=lambda: 50_000.0, sleep=lambda s: None)
    monkeypatch.setattr(mod, "apply_zone_pwm", apply_zone_pwm)
    monkeypatch.setattr(mod, "set_fan_pwm", set_fan_pwm)
    monkeypatch.setattr(mod, "detect_chassis_model", lambda *a, **k: chassis)
    monkeypatch.setattr(mod, "read_unraid_status", lambda *a, **k: {"mover": {"active": busy}})
    monkeypatch.setattr(mod, "add_event", lambda *a, **k: calls.append(["event", a[0], a[1]]))
    monkeypatch.setattr(mod, "time", clock)
    monkeypatch.setattr(
        pal_storage, "get_storage_platform", lambda *a, **k: types.SimpleNamespace(is_storage_busy=lambda: False)
    )
    Z_STATE.fan_state_tracker.clear()
    Z_STATE.critical_temp_active = False
    Z_STATE.thermal_watchdog_engaged = False
    out = fn(
        cpu_hold_secs=30,
        cpu_temp=cpu,
        ctrl_cpu_fan=True,
        disk_hold_secs=60,
        disks=[dict(d) for d in DISK_SETS[disks]],
        fan_cfg={},
        profile="balanced",
        temp_max=50,
        temp_min=37,
        zero_rpm_enabled=zero_rpm,
        zero_rpm_nvme_ceiling=50,
        zero_rpm_stop_delay=0,
        zero_rpm_stop_temp=35,
    )
    return json.loads(json.dumps({"result": out, "calls": calls}, sort_keys=True, default=str))


def test_fan_control_matches_the_recording(monkeypatch):
    got = {}
    for name, *args in _scenarios():
        with monkeypatch.context() as m:
            got[name] = _run(m, *args)
    if os.environ.get("ZETTNAS_UPDATE_GOLDEN") == "1":
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump(got, fh, indent=1, sort_keys=True)
            fh.write("\n")
        pytest.skip("golden file written")
    with open(GOLDEN, encoding="utf-8") as fh:
        want = json.load(fh)
    assert set(got) == set(want)
    changed = [name for name in want if got[name] != want[name]]
    assert not changed, f"fan control changed in {len(changed)} situations, e.g. {changed[:3]}"
    assert len(got) >= 40 and any(c[0] == "zone" for v in got.values() for c in v["calls"])


def test_the_situations_cover_the_safety_cases():
    names = [n for n, *_ in _scenarios()]
    assert any("bays_critical" in n for n in names) and any("cpu88" in n for n in names)
    assert sys.modules.get("backend") is not None
