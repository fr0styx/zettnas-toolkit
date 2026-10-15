"""
Regression test suite for Hardware Safety & Invariants (AGENTS.md §1.1 & §1.2).
Validates:
1. False-positive immunity on DDR4/DDR6 generic motherboards for is_zettlab_appliance().
2. Inviolable CPU Fan and emergency thermal clamp (>= 80C -> FAN_MAX_PWM = 183).
3. Per-zone hysteresis isolation (cool zone cannot clear hot zone watchdog).
4. Sensor failure failsafe (None CPU temp engages FAN_FAILSAFE_PWM = 150).
5. S.M.A.R.T. Spindown safety: smartctl -n standby and zero-wakeup guarantees.
6. UPS outage simulation drill safety (no real host shutdown on drill completion).
7. Observer mode safety (no export/import on Unraid/TrueNAS/Proxmox).
"""

import time
import pytest
from unittest.mock import MagicMock, patch
from backend.hardware.fans import is_zettlab_appliance, calc_curve_pwm, FAN_MAX_PWM, FAN_FAILSAFE_PWM, Z_STATE
from backend.hardware.storage import detect_chassis_model
from backend.services.ups_watchdog import check_ups_power_watchdog, trigger_outage_simulation, is_simulation_active
from backend.hardware.disks import fetch_disk_smart_detail, check_active_smart_tests
from backend.hardware.storage_diagnostics import are_all_pool_disks_sleeping
from backend.hardware.pal_storage import UnraidStorageAdapter, PlatformCapabilityError
from backend.hardware.cpu import read_cpu_temp


def test_is_zettlab_appliance_rejects_ddr4_generic_pcs(monkeypatch):
    """Ensures generic PC motherboards with 'D4' in the model name (e.g. DDR4 boards) are not detected as Zettlab appliances."""
    test_cases = [
        ("ASUSTeK COMPUTER INC.", "PRIME B660M-A D4", "PRIME B660M-A D4"),
        ("Micro-Star International Co., Ltd.", "MAG B550 TOMAHAWK (MS-7C91)", "B550"),
        ("Gigabyte Technology Co., Ltd.", "Z690 AORUS ELITE DDR4", "Default string"),
        ("Dell Inc.", "PowerEdge R730", "072VT0"),
        ("Supermicro", "SYS-5019D-FN8TP", "X11SDV-8C-TP8F"),
    ]

    monkeypatch.setattr("backend.hardware.unraid.read_unraid_status", lambda: None)

    for vendor, product, board in test_cases:
        Z_STATE.cached_chassis_model = None
        dmi_map = {"sys_vendor": vendor, "product_name": product, "board_name": board}
        monkeypatch.setattr("backend.hardware.storage._read_dmi_text", lambda k, m=dmi_map: m.get(k, ""))
        monkeypatch.setattr("backend.hardware.chassis.ChassisEngine._read_dmi_sys_vendor", lambda v=vendor: v)
        monkeypatch.setattr("backend.hardware.chassis.ChassisEngine._read_dmi_product_name", lambda p=product: p)
        monkeypatch.setattr(
            "backend.hardware.chassis.ChassisEngine._read_dmi_field", lambda f, b=board: b if f == "board_name" else ""
        )

        assert is_zettlab_appliance() is False, f"Generic motherboard '{product}' was falsely detected as an appliance!"
        assert detect_chassis_model(allow_fallback=False) == "generic"


def test_is_zettlab_appliance_accepts_genuine_hardware(monkeypatch):
    """Ensures genuine Zettlab/Aoostar hardware tokens are reliably detected even with AMI 'Default string'."""
    test_cases = [
        ("Zettlab", "D6 Ultra", "D6 Ultra", "d6u"),
        ("Default string", "Default string", "WY110", "d4"),
        ("Default string", "Default string", "WY120", "d6u"),
        ("Default string", "Default string", "WY140", "d8u"),
        ("Aoostar", "WTR Pro", "WTR Pro", "d4"),
    ]

    monkeypatch.setattr("backend.hardware.unraid.read_unraid_status", lambda: None)

    for vendor, product, board, expected_model in test_cases:
        Z_STATE.cached_chassis_model = None
        dmi_map = {"sys_vendor": vendor, "product_name": product, "board_name": board}
        monkeypatch.setattr("backend.hardware.storage._read_dmi_text", lambda k, m=dmi_map: m.get(k, ""))
        monkeypatch.setattr("backend.hardware.chassis.ChassisEngine._read_dmi_sys_vendor", lambda v=vendor: v)
        monkeypatch.setattr("backend.hardware.chassis.ChassisEngine._read_dmi_product_name", lambda p=product: p)
        monkeypatch.setattr(
            "backend.hardware.chassis.ChassisEngine._read_dmi_field", lambda f, b=board: b if f == "board_name" else ""
        )

        assert is_zettlab_appliance() is True, f"Genuine appliance '{board or product}' was not detected!"
        assert detect_chassis_model(allow_fallback=False) == expected_model


def test_emergency_thermal_clamp_at_80c():
    """Validates that any temperature >= 80C forces maximum PWM (183) regardless of curve or zone."""
    curve = [[30, 40], [50, 80], [70, 120]]

    # 79C -> normal interpolation
    pwm_79 = calc_curve_pwm(79, curve_points=curve, zone_key="zone1")
    assert pwm_79 <= FAN_MAX_PWM

    # 80C -> emergency clamp
    pwm_80 = calc_curve_pwm(80, curve_points=curve, zone_key="zone1")
    assert pwm_80 == FAN_MAX_PWM

    # 95C -> emergency clamp
    pwm_95 = calc_curve_pwm(95, curve_points=curve, zone_key="zone1")
    assert pwm_95 == FAN_MAX_PWM


def test_per_zone_thermal_watchdog_hysteresis():
    """Validates that a cool Zone 2 cannot release Zone 1's latch while Zone 1 is hot."""
    curve = [[30, 20], [50, 40], [70, 60], [85, 100]]

    # Zone 1 hits 82C -> latched
    pwm_z1_hot = calc_curve_pwm(82, curve_points=curve, zone_key="zone1")
    assert pwm_z1_hot == FAN_MAX_PWM
    assert Z_STATE.zone_watchdog_engaged.get("zone1") is True

    # Zone 2 is measured at 35C -> should NOT be latched
    pwm_z2_cool = calc_curve_pwm(35, curve_points=curve, zone_key="zone2")
    assert pwm_z2_cool < FAN_MAX_PWM
    assert Z_STATE.zone_watchdog_engaged.get("zone2", False) is False

    # Zone 1 drops to 78C (above 74C release temp) -> remains latched
    pwm_z1_cooldown = calc_curve_pwm(78, curve_points=curve, zone_key="zone1")
    assert pwm_z1_cooldown == FAN_MAX_PWM
    assert Z_STATE.zone_watchdog_engaged.get("zone1") is True

    # Zone 1 drops to 73C (below 74C release temp) -> release latch
    pwm_z1_released = calc_curve_pwm(73, curve_points=curve, zone_key="zone1")
    assert pwm_z1_released < FAN_MAX_PWM
    assert Z_STATE.zone_watchdog_engaged.get("zone1") is False


def test_sensor_failure_failsafe_pwm(monkeypatch):
    """Validates that when thermal sensors return None, read_cpu_temp returns None and FAN_FAILSAFE_PWM is 150."""
    monkeypatch.setattr("os.path.exists", lambda p: False)
    Z_STATE.cached_cpu_temp_path = None
    temp = read_cpu_temp()
    assert temp is None
    assert FAN_FAILSAFE_PWM == 150


def test_smart_detail_never_wakes_standby_drive(monkeypatch):
    """Validates that fetch_disk_smart_detail() never invokes waking SMART commands when wake_if_standby=False."""
    monkeypatch.setattr(
        "backend.hardware.smart_engine.SmartTelemetryEngine.is_device_sleeping", lambda dev, proto=None: True
    )

    with patch("subprocess.run") as mock_run:
        result = fetch_disk_smart_detail("sdb", wake_if_standby=False)
        assert result.get("is_standby") is True
        assert result.get("health") == "STANDBY"
        # dd iflag=direct must NOT be called on standby drive
        for call in mock_run.call_args_list:
            cmd = call[0][0]
            if isinstance(cmd, list):
                assert "dd" not in cmd, "Direct I/O read (dd) was executed on a sleeping drive!"
                if "smartctl" in cmd:
                    assert "-n" in cmd and "standby" in cmd, "smartctl executed without '-n standby' flag!"


def test_check_active_smart_tests_passes_standby_flag(monkeypatch):
    """Validates that background poller for active self-tests includes -n standby flag."""
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        mock = MagicMock()
        mock.stdout = ""
        mock.returncode = 2  # device in standby
        return mock

    monkeypatch.setattr("subprocess.run", mock_run)
    with Z_STATE.lock:
        Z_STATE.active_smart_tests["sdc"] = {"start_time": time.time(), "type": "short"}
    try:
        check_active_smart_tests()
        assert any("-n" in cmd and "standby" in cmd for cmd in calls)
    finally:
        with Z_STATE.lock:
            Z_STATE.active_smart_tests.clear()


def test_are_all_pool_disks_sleeping():
    """Validates pool standby check for storage diagnostics."""
    disks_sleeping = [{"dev": "sdb", "standby": True}, {"dev": "sdc", "standby": True}]
    disks_awake = [{"dev": "sdb", "standby": True}, {"dev": "sdc", "standby": False}]
    assert are_all_pool_disks_sleeping(disks_sleeping) is True
    assert are_all_pool_disks_sleeping(disks_awake) is False


def test_ups_outage_simulation_drill_never_shuts_down_host():
    """Validates that a simulation drill reaching 0% battery never triggers a physical host shutdown."""
    trigger_outage_simulation(duration_sec=30)
    assert is_simulation_active() is True

    # Simulated critical power loss: on battery, 0% charge, 1 minute runtime
    simulated_ups_data = {
        "available": True,
        "status": "OB DISCHRG",
        "battery_charge_pct": 0.0,
        "time_left_min": 1.0,
        "line_volts": 0.0,
    }

    with patch("backend.services.ups_watchdog.execute_atomic_failsafe_shutdown") as mock_shutdown:
        check_ups_power_watchdog(simulated_ups_data, time.time())
        # Physical shutdown MUST NOT be called during simulation drill
        assert not mock_shutdown.called, "execute_atomic_failsafe_shutdown was called during an outage drill!"
        # Simulation drill should be safely ended
        assert is_simulation_active() is False


def test_unraid_storage_adapter_observer_mode_restrictions():
    """Validates that Unraid PAL adapter declares observer mode and forbids pool export/import."""
    adapter = UnraidStorageAdapter()
    caps = adapter.get_capabilities()
    assert caps.is_observer_mode is True
    assert caps.can_export_pools is False
    assert caps.can_import_pools is False

    with pytest.raises(PlatformCapabilityError) as exc_info:
        adapter.export_pool("cache")
    assert "Unraid" in str(exc_info.value) or "cannot be detached" in str(exc_info.value)
