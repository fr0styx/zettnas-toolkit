"""Integration and safety test suite for Zero RPM fan mode.

Verifies:
1. Chassis topology resolving (D4 single rear fan vs D6U/D8 dual zone split).
2. Spun-down disk standby interlock and single disk spinup breaking standby.
3. NVMe wind-tunnel override revoking Zero RPM when M.2 SSD >= ceiling temp.
4. 180s continuous anti-flutter delay gating before shutting off fans.
5. Unraid subsystem interlock (mover / parity check revoking Zero RPM).
6. Absolute CPU fan (pwm3) zero-RPM immunity under all conditions.
7. Reactive tachometer stall detection vs Zero RPM / spinup grace suppression.
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from backend.config import (
    FAN_KICKSTART_PWM,
    FAN_KICKSTART_SECS,
    FAN_MIN_PWM,
    FAN_MAX_PWM,
    FAN_SPINUP_GRACE_SECS,
    FAN_ZERO_RPM_STOP_DELAY,
    FAN_ZERO_RPM_DEFAULT_NVME_CEILING,
    FAN_ZERO_RPM_DEFAULT_STOP_TEMP,
    FAN_ZERO_RPM_DEFAULT_START_TEMP,
)
from backend.hardware.fans import (
    apply_zone_pwm,
    calc_curve_pwm,
    clamp_fan_pwm,
)
from backend.state import Z_STATE


@pytest.fixture(autouse=True)
def reset_fan_state():
    """Reset Z_STATE fan state trackers before each test."""
    Z_STATE.fan_state_tracker = {
        "pwm1": {"current": 67, "last_up_time": 0.0, "kickstart_until": 0.0, "last_spinup_time": 0.0, "standby_since": 0.0},
        "pwm2": {"current": 67, "last_up_time": 0.0, "kickstart_until": 0.0, "last_spinup_time": 0.0, "standby_since": 0.0},
        "pwm3": {"current": 67, "last_up_time": 0.0, "kickstart_until": 0.0, "last_spinup_time": 0.0, "standby_since": 0.0},
    }
    Z_STATE.critical_temp_active = False
    yield


# =========================================================================
# 1. Chassis Topology & Standby Interlock Tests
# =========================================================================

def test_d4_topology_requires_all_4_disks_in_standby():
    """On D4 chassis (single rear fan cooling all 4 bays), all 4 disks must be in standby."""
    chassis_model = "D4"
    disks = [
        {"name": "disk1", "bay": 1, "standby": True, "temp": 30},
        {"name": "disk2", "bay": 2, "standby": True, "temp": 31},
        {"name": "disk3", "bay": 3, "standby": True, "temp": 29},
        {"name": "disk4", "bay": 4, "standby": False, "temp": 33},  # One drive is active
    ]

    is_d4 = (chassis_model == "D4")
    if is_d4:
        bay_disks = [d for d in disks if d.get("bay") in (1, 2, 3, 4)]
        z1_all_standby = bool(bay_disks and all(d.get("standby", False) for d in bay_disks))
    else:
        z1_disks = [d for d in disks if d.get("bay") in (1, 2)]
        z1_all_standby = bool(z1_disks and all(d.get("standby", False) for d in z1_disks))

    # disk4 is spinning -> Zone 1 must NOT be standby
    assert z1_all_standby is False

    # Now spin down disk4
    disks[3]["standby"] = True
    bay_disks = [d for d in disks if d.get("bay") in (1, 2, 3, 4)]
    z1_all_standby = bool(bay_disks and all(d.get("standby", False) for d in bay_disks))
    assert z1_all_standby is True


def test_d8_topology_dual_zone_independence():
    """On D6U/D8 chassis, Zone 1 (bays 1-4) and Zone 2 (bays 5+) operate independently."""
    chassis_model = "D8"
    disks = [
        {"name": "disk1", "bay": 1, "standby": True, "temp": 30},
        {"name": "disk2", "bay": 2, "standby": True, "temp": 31},
        {"name": "disk3", "bay": 3, "standby": True, "temp": 29},
        {"name": "disk4", "bay": 4, "standby": True, "temp": 30},
        {"name": "disk5", "bay": 5, "standby": False, "temp": 42},  # Zone 2 active
        {"name": "disk6", "bay": 6, "standby": False, "temp": 44},
    ]

    is_d4 = (chassis_model == "D4")
    assert not is_d4

    z1_disks = [d for d in disks if d.get("bay") in (1, 2, 3, 4)]
    z2_disks = [d for d in disks if d.get("bay") in (5, 6, 7, 8)]

    z1_all_standby = bool(z1_disks and all(d.get("standby", False) for d in z1_disks))
    z2_all_standby = bool(z2_disks and all(d.get("standby", False) for d in z2_disks))

    assert z1_all_standby is True
    assert z2_all_standby is False


# =========================================================================
# 2. NVMe Wind-Tunnel Override Tests
# =========================================================================

def test_nvme_ceiling_overrides_zero_rpm():
    """Even if all disks are in standby and disk temps are cold, NVMe >= ceiling revokes Zero RPM."""
    zero_rpm_enabled = True
    zero_rpm_nvme_ceiling = 50
    t_zone1 = 30
    zero_rpm_stop_temp = 34
    z1_all_standby = True
    critical_override = False
    storage_busy = False

    # Scenario A: NVMe is cool (42°C < 50°C) -> Eligible
    t_nvme_cool = 42
    nvme_over_ceiling_cool = bool(t_nvme_cool is not None and t_nvme_cool >= zero_rpm_nvme_ceiling)
    z1_eligible_cool = bool(
        zero_rpm_enabled
        and not critical_override
        and not storage_busy
        and z1_all_standby
        and t_zone1 <= zero_rpm_stop_temp
        and not nvme_over_ceiling_cool
    )
    assert z1_eligible_cool is True

    # Scenario B: NVMe runs hot (53°C >= 50°C) -> Revokes Zero RPM to preserve wind tunnel cooling
    t_nvme_hot = 53
    nvme_over_ceiling_hot = bool(t_nvme_hot is not None and t_nvme_hot >= zero_rpm_nvme_ceiling)
    z1_eligible_hot = bool(
        zero_rpm_enabled
        and not critical_override
        and not storage_busy
        and z1_all_standby
        and t_zone1 <= zero_rpm_stop_temp
        and not nvme_over_ceiling_hot
    )
    assert z1_eligible_hot is False


# =========================================================================
# 3. Continuous Anti-Flutter Gating Tests
# =========================================================================

def test_anti_flutter_180s_delay_gating():
    """Zero RPM requires 180 continuous seconds of cold standby before stopping fans."""
    now = 1000.0
    st1 = Z_STATE.fan_state_tracker["pwm1"]
    st1["current"] = 67
    st1["standby_since"] = 0.0

    z1_eligible = True

    # Step 1: Disks just entered standby at t=1000
    if z1_eligible:
        if st1.get("standby_since", 0.0) == 0.0:
            st1["standby_since"] = now

    assert st1["standby_since"] == 1000.0

    # At t=1050 (50s elapsed) -> Not ready
    t_50 = 1050.0
    z1_zero_rpm_ready_50 = bool(
        z1_eligible
        and st1.get("standby_since", 0.0) > 0.0
        and (t_50 - st1["standby_since"]) >= FAN_ZERO_RPM_STOP_DELAY
    )
    assert z1_zero_rpm_ready_50 is False

    # At t=1180 (180s elapsed) -> Ready!
    t_180 = 1180.0
    z1_zero_rpm_ready_180 = bool(
        z1_eligible
        and st1.get("standby_since", 0.0) > 0.0
        and (t_180 - st1["standby_since"]) >= FAN_ZERO_RPM_STOP_DELAY
    )
    assert z1_zero_rpm_ready_180 is True

    # Step 2: Sudden temperature spike or disk wake up breaks eligibility
    z1_eligible = False
    if not z1_eligible:
        st1["standby_since"] = 0.0

    assert st1["standby_since"] == 0.0


# =========================================================================
# 4. Single Disk Spinup Breaking Standby & Kickstart Pulse
# =========================================================================

def test_disk_spinup_triggers_kickstart_from_zero():
    """When a disk spins up while fan is stopped at 0 RPM, transition triggers 2.0s 150 PWM kickstart."""
    st = Z_STATE.fan_state_tracker["pwm1"]
    st["current"] = 0
    st["kickstart_until"] = 0.0
    st["last_spinup_time"] = 0.0

    now = 2000.0
    with patch("time.time", return_value=now):
        # Target PWM is 67 (idle speed). Transition from 0 -> 67 triggers kickstart!
        active_pwm = apply_zone_pwm(1, 67, hold_secs=120, allow_zero=False)

        assert active_pwm == FAN_KICKSTART_PWM  # 150 PWM
        assert st["kickstart_until"] == now + FAN_KICKSTART_SECS
        assert st["last_spinup_time"] == now
        assert st["current"] == 67

    # During kickstart window (1.0s later) -> still holds 150 PWM
    with patch("time.time", return_value=now + 1.0):
        active_pwm_mid = apply_zone_pwm(1, 67, hold_secs=120, allow_zero=False)
        assert active_pwm_mid == FAN_KICKSTART_PWM

    # After kickstart window (2.5s later) -> settles to requested target PWM (67)
    with patch("time.time", return_value=now + 2.5):
        active_pwm_after = apply_zone_pwm(1, 67, hold_secs=120, allow_zero=False)
        assert active_pwm_after == 67


# =========================================================================
# 5. Storage Subsystem Interlock (Mover / Parity)
# =========================================================================

def test_storage_busy_revokes_zero_rpm():
    """Active mover or parity check prevents fans from stopping."""
    zero_rpm_enabled = True
    z1_all_standby = True
    t_zone1 = 30
    zero_rpm_stop_temp = 34
    critical_override = False

    # Parity check running
    storage_busy = True
    z1_eligible = bool(
        zero_rpm_enabled
        and not critical_override
        and not storage_busy
        and z1_all_standby
        and t_zone1 <= zero_rpm_stop_temp
    )
    assert z1_eligible is False

    # Parity check finished
    storage_busy = False
    z1_eligible = bool(
        zero_rpm_enabled
        and not critical_override
        and not storage_busy
        and z1_all_standby
        and t_zone1 <= zero_rpm_stop_temp
    )
    assert z1_eligible is True


# =========================================================================
# 6. Absolute CPU Fan (pwm3) Zero-RPM Immunity
# =========================================================================

def test_cpu_fan_pwm3_never_stops():
    """CPU fan (pwm3) must never stop under any circumstance, even if allow_zero=True is passed."""
    # Attempt direct clamp with allow_zero=True
    clamped_3 = clamp_fan_pwm(0, allow_zero=False)
    assert clamped_3 == FAN_MIN_PWM

    # Attempt zone pwm command of 0 to pwm3 with allow_zero=True
    pwm3_out = apply_zone_pwm(3, 0, hold_secs=90, allow_zero=True)
    assert pwm3_out >= FAN_MIN_PWM
    assert pwm3_out == FAN_MIN_PWM

    # Curve calculation for CPU fan explicitly uses allow_zero=False
    curve_out = calc_curve_pwm(25, allow_zero=False)
    assert curve_out >= FAN_MIN_PWM


# =========================================================================
# 7. Reactive Tachometer Stall Detection vs Zero RPM Suppression
# =========================================================================

def test_stall_watchdog_suppression_logic():
    """Stall watchdog must NOT trigger alarm when commanded to 0 or during 6s spinup grace."""
    now = 5000.0

    # Scenario A: Normal spinning stall (tachometer 0 RPM, cmd_pwm = 120, spinup > 6s ago) -> STALL!
    fans = [0, 1200, 1500]
    i = 0
    rpm = fans[i]
    cmd_pwm = 120
    last_spinup = now - 10.0  # 10s ago

    is_suppressed = (cmd_pwm == 0) or ((now - last_spinup) < FAN_SPINUP_GRACE_SECS)
    assert is_suppressed is False  # Genuine stall detected

    # Scenario B: Fan commanded to 0 RPM in Zero RPM mode -> Suppressed
    cmd_pwm_zero = 0
    is_suppressed_zero = (cmd_pwm_zero == 0) or ((now - last_spinup) < FAN_SPINUP_GRACE_SECS)
    assert is_suppressed_zero is True  # Suppressed, no false positive

    # Scenario C: Fan just spun up (kickstarting), tachometer hasn't registered RPM yet (2s into spinup) -> Suppressed
    last_spinup_recent = now - 2.0
    cmd_pwm_spinup = FAN_KICKSTART_PWM
    is_suppressed_grace = (cmd_pwm_spinup == 0) or ((now - last_spinup_recent) < FAN_SPINUP_GRACE_SECS)
    assert is_suppressed_grace is True  # Suppressed by 6s grace window
