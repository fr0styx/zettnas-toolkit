"""Fan curve math: sanitization, interpolation, PWM floor/ceiling, hold logic."""

import pytest

from backend.config import (
    FAN_KICKSTART_PWM,
    FAN_KICKSTART_SECS,
    FAN_MAX_PWM,
    FAN_MIN_PWM,
)
from backend.hardware.fans import (
    apply_zone_pwm,
    calc_curve_pwm,
    clamp_fan_pwm,
    get_hold_remaining,
    sanitize_curve_points,
)
from backend.state import Z_STATE

# ---- sanitize_curve_points ----


def test_sanitize_none_and_empty():
    assert sanitize_curve_points(None) is None
    assert sanitize_curve_points([]) is None


def test_sanitize_requires_two_points():
    assert sanitize_curve_points([[40, 50]]) is None


def test_sanitize_sorts_by_temperature():
    assert sanitize_curve_points([[60, 100], [30, 20]]) == [[30, 20], [60, 100]]


def test_sanitize_makes_curve_monotonic():
    # A hotter point can never be slower than a cooler one.
    assert sanitize_curve_points([[31, 16], [38, 41], [49, 30], [60, 100]]) == [[31, 16], [38, 41], [49, 41], [60, 100]]


def test_sanitize_clamps_out_of_range_values():
    assert sanitize_curve_points([[-10, -5], [150, 300]]) == [[0, 0], [100, 100]]


def test_sanitize_collapses_duplicate_temperatures_to_max():
    assert sanitize_curve_points([[40, 20], [40, 60], [50, 70]]) == [[40, 60], [50, 70]]


def test_sanitize_skips_malformed_points():
    assert sanitize_curve_points([[30, 10], "bad", [None, 5], [1], [60, 90]]) == [[30, 10], [60, 90]]


def test_sanitize_accepts_numeric_strings():
    assert sanitize_curve_points([["30", "10"], ["60", "90"]]) == [[30, 10], [60, 90]]


# ---- calc_curve_pwm: linear fallback ----


@pytest.mark.parametrize("temp", [None, 0, -5])
def test_invalid_temperature_returns_floor(temp):
    assert calc_curve_pwm(temp) == FAN_MIN_PWM


def test_linear_below_min_is_floor():
    assert calc_curve_pwm(30, temp_min=37, temp_max=50) == FAN_MIN_PWM


def test_linear_above_max_is_ceiling():
    assert calc_curve_pwm(55, temp_min=37, temp_max=50) == FAN_MAX_PWM


def test_linear_midpoint_interpolates():
    mid = calc_curve_pwm(43.5, temp_min=37, temp_max=50)
    assert FAN_MIN_PWM < mid < FAN_MAX_PWM
    assert abs(mid - (FAN_MIN_PWM + FAN_MAX_PWM) / 2) <= 1


def test_linear_degenerate_span_does_not_divide_by_zero():
    assert FAN_MIN_PWM <= calc_curve_pwm(40, temp_min=40, temp_max=40) <= FAN_MAX_PWM


# ---- calc_curve_pwm: custom curve ----

CURVE = [[31, 16], [38, 41], [49, 59], [60, 100]]


def test_curve_never_below_floor():
    # 16% of 183 = 29 PWM, which is below the reliable spin floor.
    assert calc_curve_pwm(25, curve_points=CURVE) == FAN_MIN_PWM
    assert calc_curve_pwm(31, curve_points=CURVE) == FAN_MIN_PWM


def test_curve_top_point_is_full_speed():
    assert calc_curve_pwm(60, curve_points=CURVE) == FAN_MAX_PWM
    assert calc_curve_pwm(80, curve_points=CURVE) == FAN_MAX_PWM


def test_curve_interpolates_between_points():
    # Halfway between (49,59%) and (60,100%) -> ~79.5% of 183.
    val = calc_curve_pwm(54.5, curve_points=CURVE)
    assert abs(val - int(0.795 * FAN_MAX_PWM)) <= 1


def test_curve_output_is_monotonic_in_temperature():
    values = [calc_curve_pwm(t, curve_points=CURVE) for t in range(20, 70)]
    assert values == sorted(values)


def test_non_monotonic_input_curve_still_monotonic_output():
    bad = [[30, 80], [40, 20], [50, 90]]
    values = [calc_curve_pwm(t, curve_points=bad) for t in range(25, 60)]
    assert values == sorted(values)


def test_invalid_curve_falls_back_to_linear():
    assert calc_curve_pwm(55, curve_points=[[40, 50]], temp_min=37, temp_max=50) == FAN_MAX_PWM


# ---- apply_zone_pwm hysteresis ----


@pytest.fixture
def fresh_zone():
    Z_STATE.fan_state_tracker.pop("pwm9", None)
    yield 9
    Z_STATE.fan_state_tracker.pop("pwm9", None)


def test_zone_ramps_up_immediately(fresh_zone):
    assert apply_zone_pwm(fresh_zone, 150, hold_secs=120) == 150


def test_zone_holds_before_ramping_down(fresh_zone):
    apply_zone_pwm(fresh_zone, 150, hold_secs=120)
    assert apply_zone_pwm(fresh_zone, 80, hold_secs=120) == 150
    assert get_hold_remaining("pwm9", 120) > 100


def test_zone_ramps_down_after_hold(fresh_zone):
    apply_zone_pwm(fresh_zone, 150, hold_secs=120)
    Z_STATE.fan_state_tracker["pwm9"]["last_up_time"] -= 121
    assert apply_zone_pwm(fresh_zone, 80, hold_secs=120) == 80
    assert get_hold_remaining("pwm9", 120) == 0


# ---- Per-Zone Curves ----


def test_per_zone_independent_curves():
    # Zone 1 aggressive curve for hot disks
    z1_curve = [[30, 20], [40, 60], [50, 100]]
    # Zone 2 relaxed curve for cool disks
    z2_curve = [[30, 10], [45, 30], [55, 100]]

    pwm1 = calc_curve_pwm(40, curve_points=z1_curve)
    pwm2 = calc_curve_pwm(40, curve_points=z2_curve)

    assert pwm1 > pwm2


def test_cpu_curve_higher_thresholds():
    # CPU operates at 50-85C
    cpu_curve = [[50, 30], [70, 70], [85, 100]]

    # At 45C (below min), fan runs at minimum
    assert calc_curve_pwm(45, curve_points=cpu_curve) == FAN_MIN_PWM
    # At 70C, fan runs at 70%
    val = calc_curve_pwm(70, curve_points=cpu_curve)
    assert abs(val - int(0.70 * FAN_MAX_PWM)) <= 1
    # At 85C+, fan runs at 100%
    assert calc_curve_pwm(85, curve_points=cpu_curve) == FAN_MAX_PWM
    assert calc_curve_pwm(95, curve_points=cpu_curve) == FAN_MAX_PWM


def test_hardware_thermal_watchdog_overrides_flat_low_curve():
    Z_STATE.thermal_watchdog_engaged = False
    # User configures a flat/low curve (max 40% at 75C)
    flat_curve = [[30, 10], [50, 25], [75, 40]]
    # At 75C, user curve is respected
    val = calc_curve_pwm(75, curve_points=flat_curve)
    assert abs(val - int(0.40 * FAN_MAX_PWM)) <= 1

    # At 80C+, inviolable watchdog triggers 100% PWM
    assert calc_curve_pwm(80, curve_points=flat_curve) == FAN_MAX_PWM
    assert calc_curve_pwm(85, curve_points=flat_curve) == FAN_MAX_PWM
    assert Z_STATE.thermal_watchdog_engaged is True


def test_hardware_thermal_watchdog_hysteresis():
    Z_STATE.thermal_watchdog_engaged = False
    flat_curve = [[30, 10], [50, 15], [75, 20]]
    # Engage watchdog at 82C
    calc_curve_pwm(82, curve_points=flat_curve)
    assert Z_STATE.thermal_watchdog_engaged is True

    # Drop to 77C (between 74 and 80): watchdog stays engaged due to thermal hysteresis
    assert calc_curve_pwm(77, curve_points=flat_curve) == FAN_MAX_PWM
    assert Z_STATE.thermal_watchdog_engaged is True

    # Drop to 74C or below: watchdog disengages and curve resumes
    val_74 = calc_curve_pwm(74, curve_points=flat_curve)
    assert Z_STATE.thermal_watchdog_engaged is False
    assert val_74 < FAN_MAX_PWM


# ---- Zero RPM & Kickstart Tests ----


def test_clamp_fan_pwm_binary_cutoff():
    # allow_zero=False: strictly clamped to [FAN_MIN_PWM, FAN_MAX_PWM]
    assert clamp_fan_pwm(0, allow_zero=False) == FAN_MIN_PWM
    assert clamp_fan_pwm(30, allow_zero=False) == FAN_MIN_PWM
    assert clamp_fan_pwm(57, allow_zero=False) == FAN_MIN_PWM
    assert clamp_fan_pwm(58, allow_zero=False) == 58
    assert clamp_fan_pwm(120, allow_zero=False) == 120
    assert clamp_fan_pwm(200, allow_zero=False) == FAN_MAX_PWM

    # allow_zero=True: 0 stays 0; stall zone (1..57) clamps to FAN_MIN_PWM
    assert clamp_fan_pwm(0, allow_zero=True) == 0
    assert clamp_fan_pwm(-10, allow_zero=True) == 0
    assert clamp_fan_pwm(1, allow_zero=True) == FAN_MIN_PWM
    assert clamp_fan_pwm(30, allow_zero=True) == FAN_MIN_PWM
    assert clamp_fan_pwm(57, allow_zero=True) == FAN_MIN_PWM
    assert clamp_fan_pwm(58, allow_zero=True) == 58
    assert clamp_fan_pwm(120, allow_zero=True) == 120
    assert clamp_fan_pwm(200, allow_zero=True) == FAN_MAX_PWM


def test_apply_zone_pwm_kickstart_from_zero(fresh_zone):
    # Establish fan stopped at 0
    Z_STATE.fan_state_tracker["pwm9"] = {
        "current": 0,
        "last_up_time": 0.0,
        "kickstart_until": 0.0,
        "last_spinup_time": 0.0,
        "standby_since": 0.0,
    }

    # Transitioning from 0 to 67 must trigger non-blocking kickstart pulse (150 PWM)
    res = apply_zone_pwm(fresh_zone, 67, hold_secs=120, allow_zero=True)
    assert res == FAN_KICKSTART_PWM
    assert Z_STATE.fan_state_tracker["pwm9"]["current"] == 67
    assert Z_STATE.fan_state_tracker["pwm9"]["kickstart_until"] > 0

    # During the 2.0s kickstart window, continues returning FAN_KICKSTART_PWM
    res_during = apply_zone_pwm(fresh_zone, 67, hold_secs=120, allow_zero=True)
    assert res_during == FAN_KICKSTART_PWM

    # Once kickstart window expires, smoothly settles at target PWM
    Z_STATE.fan_state_tracker["pwm9"]["kickstart_until"] -= FAN_KICKSTART_SECS + 1.0
    res_after = apply_zone_pwm(fresh_zone, 67, hold_secs=120, allow_zero=True)
    assert res_after == 67


def test_apply_zone_pwm_no_kickstart_when_already_spinning(fresh_zone):
    # Spinning fan ramping up 67 -> 100
    Z_STATE.fan_state_tracker["pwm9"] = {
        "current": 67,
        "last_up_time": 0.0,
        "kickstart_until": 0.0,
        "last_spinup_time": 0.0,
        "standby_since": 0.0,
    }
    res = apply_zone_pwm(fresh_zone, 100, hold_secs=120, allow_zero=True)
    assert res == 100  # Immediately ramps to 100 without kickstart


def test_apply_zone_pwm_zero_rpm_downward_hold(fresh_zone):
    import time

    now = time.time()
    # Spinning fan at 67 commanded to 0
    Z_STATE.fan_state_tracker["pwm9"] = {
        "current": 67,
        "last_up_time": now,
        "kickstart_until": 0.0,
        "last_spinup_time": now,
        "standby_since": 0.0,
    }

    # Immediately commanding 0 should hold at current speed (67)
    assert apply_zone_pwm(fresh_zone, 0, hold_secs=120, allow_zero=True) == 67

    # After hold_secs expires, fan drops to 0
    Z_STATE.fan_state_tracker["pwm9"]["last_up_time"] -= 125
    assert apply_zone_pwm(fresh_zone, 0, hold_secs=120, allow_zero=True) == 0
    assert Z_STATE.fan_state_tracker["pwm9"]["current"] == 0


def test_apply_zone_pwm_cpu_fan_cannot_zero():
    # pwm3 (CPU fan) must never enter Zero RPM even if allow_zero=True
    Z_STATE.fan_state_tracker["pwm3"] = {
        "current": 85,
        "last_up_time": 0.0,
        "kickstart_until": 0.0,
        "last_spinup_time": 0.0,
        "standby_since": 0.0,
    }
    # Command 0 to CPU fan
    res = apply_zone_pwm(3, 0, hold_secs=0, allow_zero=True)
    # CPU fan forces allow_zero=False and clamps to FAN_MIN_PWM (58)
    assert res == FAN_MIN_PWM
