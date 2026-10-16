"""Unit tests for Tier 1 direct userspace MMIO fan controller."""

import pytest

from backend.config import FAN_FAILSAFE_PWM, FAN_MAX_PWM, FAN_MIN_PWM
from backend.hardware.fans import (
    ZettlabMmioFanController,
    failsafe_release_fans,
    read_fans,
    set_fan_pwm,
)
from backend.state import Z_STATE


class FakeMmap:
    """Mock memory-mapped buffer simulating physical memory at 0xFE0B0000."""

    def __init__(self, size=4096):
        self._buf = bytearray(size)

    def __getitem__(self, idx):
        return self._buf[idx]

    def __setitem__(self, idx, val):
        self._buf[idx] = val

    def close(self):
        pass


@pytest.fixture
def mock_mmio_controller(monkeypatch):
    ctrl = ZettlabMmioFanController()
    fake_mm = FakeMmap(4096)
    ctrl._mm = fake_mm
    ctrl._failed_previously = False

    # Force is_zettlab_appliance and is_zettlab_mmio_supported to True
    import backend.hardware.fans as fans_mod

    monkeypatch.setattr(fans_mod, "is_zettlab_appliance", lambda: True)
    monkeypatch.setattr(fans_mod, "is_zettlab_mmio_supported", lambda: True)
    monkeypatch.setattr(fans_mod, "get_mmio_fan_controller", lambda: ctrl)

    return ctrl, fake_mm


def test_mmio_read_fans_decodes_rpm(mock_mmio_controller):
    ctrl, fake_mm = mock_mmio_controller
    offset = ctrl._page_offset

    # Set Fan 1 RPM = 1250 (0x04E2)
    fake_mm[offset + 0] = 0x04
    fake_mm[offset + 1] = 0xE2

    # Set Fan 2 RPM = 830 (0x033E)
    fake_mm[offset + 3] = 0x03
    fake_mm[offset + 4] = 0x3E

    # Set Fan 3 RPM = 2400 (0x0960)
    fake_mm[offset + 6] = 0x09
    fake_mm[offset + 7] = 0x60

    rpms = ctrl.read_fans()
    assert rpms == [1250, 830, 2400]


def test_mmio_write_pwm_clamps_bounds(mock_mmio_controller):
    ctrl, fake_mm = mock_mmio_controller
    offset = ctrl._page_offset

    # Write Channel 1 normal
    assert ctrl.write_pwm(1, 100)
    assert fake_mm[offset + 2] == 100

    # Write Channel 2 above max hardware PWM (183 / 0xB7)
    assert ctrl.write_pwm(2, 255)
    assert fake_mm[offset + 5] == FAN_MAX_PWM

    # Write Channel 3 below 0
    assert ctrl.write_pwm(3, -50)
    assert fake_mm[offset + 8] == 0


def test_read_fans_falls_back_to_mmio(mock_mmio_controller, monkeypatch):
    ctrl, fake_mm = mock_mmio_controller
    offset = ctrl._page_offset

    # Set Fan 1 RPM = 1100
    fake_mm[offset + 0] = 0x04
    fake_mm[offset + 1] = 0x4C

    import backend.hardware.fans as fans_mod

    monkeypatch.setattr(fans_mod, "_find_hwmon", lambda: None)

    rpms = read_fans()
    assert rpms[0] == 1100
    assert Z_STATE.fan_driver_mode == "mmio"


def test_set_fan_pwm_mmio_fallback_profile(mock_mmio_controller, monkeypatch):
    ctrl, fake_mm = mock_mmio_controller
    offset = ctrl._page_offset

    import backend.hardware.fans as fans_mod

    monkeypatch.setattr(fans_mod, "_find_hwmon", lambda: None)

    # Apply balanced profile (PWM 120) with CPU fan left to firmware auto
    assert set_fan_pwm("balanced", ctrl_cpu_fan=False)
    assert fake_mm[offset + 2] == 120  # Fan 1
    assert fake_mm[offset + 5] == 120  # Fan 2
    assert fake_mm[offset + 8] == 0  # Fan 3 handed back to firmware auto (0)
    assert Z_STATE.fan_driver_mode == "mmio"


def test_set_fan_pwm_mmio_cpu_fan_controlled(mock_mmio_controller, monkeypatch):
    ctrl, fake_mm = mock_mmio_controller
    offset = ctrl._page_offset

    import backend.hardware.fans as fans_mod

    monkeypatch.setattr(fans_mod, "_find_hwmon", lambda: None)

    # CPU fan controlled manually at custom PWM 95
    assert set_fan_pwm("auto", custom_pwms={"pwm1": 70, "pwm2": 70, "pwm3": 95}, ctrl_cpu_fan=True)
    assert fake_mm[offset + 2] == 70
    assert fake_mm[offset + 5] == 70
    assert fake_mm[offset + 8] == 95


def test_set_fan_pwm_mmio_zero_rpm_and_cpu_inviolability(mock_mmio_controller, monkeypatch):
    ctrl, fake_mm = mock_mmio_controller
    offset = ctrl._page_offset

    import backend.hardware.fans as fans_mod

    monkeypatch.setattr(fans_mod, "_find_hwmon", lambda: None)

    # Disk fans allowed zero RPM (e.g. spun down drives)
    assert set_fan_pwm(
        "auto",
        custom_pwms={"pwm1": 0, "pwm2": 0, "pwm3": 0},
        ctrl_cpu_fan=True,
        zero_rpm_allowed=True,
    )
    assert fake_mm[offset + 2] == 0
    assert fake_mm[offset + 5] == 0
    # CPU fan must NEVER be 0 when ctrl_cpu_fan=True -> clamped to FAN_MIN_PWM (58)
    assert fake_mm[offset + 8] == FAN_MIN_PWM


def test_failsafe_release_fans_mmio(mock_mmio_controller, monkeypatch):
    ctrl, fake_mm = mock_mmio_controller
    offset = ctrl._page_offset

    import backend.hardware.fans as fans_mod

    monkeypatch.setattr(fans_mod, "_find_hwmon", lambda: None)

    assert failsafe_release_fans("shutdown_test")
    assert fake_mm[offset + 2] == FAN_FAILSAFE_PWM
    assert fake_mm[offset + 5] == FAN_FAILSAFE_PWM
    assert fake_mm[offset + 8] == 0  # CPU fan handed to firmware auto
    assert Z_STATE.fans_released is True
