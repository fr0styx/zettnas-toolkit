"""Fan sysfs control against a fake zettlab_d8_fans hwmon: floor, CPU-fan
hand-off, failsafe behaviour and the shutdown lock."""

from conftest import read_sysfs

from backend.config import FAN_FAILSAFE_PWM, FAN_MAX_PWM, FAN_MIN_PWM
from backend.hardware.fans import failsafe_release_fans, read_fans, set_fan_pwm
from backend.state import Z_STATE


def test_read_fans_reports_rpm(fake_hwmon):
    assert read_fans() == [1300, 820, 2800]


def test_read_fans_discards_spurious_spikes(fake_hwmon):
    with open(f"{fake_hwmon}/fan2_input", "w") as f:
        f.write("65535\n")
    assert read_fans()[1] == 0


def test_custom_pwms_are_clamped_to_floor_and_ceiling(fake_hwmon):
    assert set_fan_pwm("auto", custom_pwms={"pwm1": 10, "pwm2": 999})
    assert read_sysfs(fake_hwmon, "pwm1") == str(FAN_MIN_PWM)
    assert read_sysfs(fake_hwmon, "pwm2") == str(FAN_MAX_PWM)


def test_cpu_fan_left_to_firmware_when_not_controlled(fake_hwmon):
    set_fan_pwm("auto", custom_pwms={"pwm1": 100, "pwm2": 100}, ctrl_cpu_fan=False)
    assert read_sysfs(fake_hwmon, "pwm3_enable") == "2"
    assert read_sysfs(fake_hwmon, "pwm3") == "0"  # untouched


def test_cpu_fan_claimed_when_controlled(fake_hwmon):
    set_fan_pwm("auto", custom_pwms={"pwm1": 100, "pwm2": 100, "pwm3": 120}, ctrl_cpu_fan=True)
    assert read_sysfs(fake_hwmon, "pwm3_enable") == "1"
    assert read_sysfs(fake_hwmon, "pwm3") == "120"


def test_profile_mode_writes_preset(fake_hwmon):
    set_fan_pwm("balanced")
    assert read_sysfs(fake_hwmon, "pwm1") == "120"
    assert read_sysfs(fake_hwmon, "pwm2") == "120"


def test_manual_percentage_respects_floor(fake_hwmon):
    set_fan_pwm("manual", manual_pct=5)
    assert read_sysfs(fake_hwmon, "pwm1") == str(FAN_MIN_PWM)


def test_failsafe_pins_disk_fans_and_releases_cpu_fan(fake_hwmon):
    set_fan_pwm("auto", custom_pwms={"pwm1": 70, "pwm2": 70, "pwm3": 90}, ctrl_cpu_fan=True)
    assert failsafe_release_fans("test")
    # pwm1/2 have read-only enable files -> pinned at the failsafe PWM.
    assert read_sysfs(fake_hwmon, "pwm1") == str(FAN_FAILSAFE_PWM)
    assert read_sysfs(fake_hwmon, "pwm2") == str(FAN_FAILSAFE_PWM)
    assert read_sysfs(fake_hwmon, "pwm1_enable") == "1"
    # pwm3 supports firmware auto -> handed back.
    assert read_sysfs(fake_hwmon, "pwm3_enable") == "2"
    assert Z_STATE.fans_released is True


def test_control_resumes_after_watchdog_failsafe(fake_hwmon):
    failsafe_release_fans("watchdog")
    assert Z_STATE.fans_released
    assert set_fan_pwm("auto", custom_pwms={"pwm1": 100, "pwm2": 100})
    assert Z_STATE.fans_released is False
    assert read_sysfs(fake_hwmon, "pwm1") == "100"


def test_shutdown_lock_blocks_reclaiming(fake_hwmon):
    failsafe_release_fans("shutdown", lock=True)
    assert set_fan_pwm("auto", custom_pwms={"pwm1": 60, "pwm2": 60}) is False
    assert read_sysfs(fake_hwmon, "pwm1") == str(FAN_FAILSAFE_PWM)


def test_no_hwmon_is_harmless(fake_hwmon, monkeypatch):
    import backend.hardware.fans as fans

    monkeypatch.setattr(fans, "_find_hwmon", lambda: None)
    assert fans.set_fan_pwm("auto", custom_pwms={"pwm1": 100}) is False
    assert fans.failsafe_release_fans("test") is False
