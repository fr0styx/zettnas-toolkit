import json
from unittest.mock import mock_open, patch

from backend.hardware.screen import (
    discover_backlight_dir,
    find_fb_device,
    get_effective_brightness,
    save_screen_state,
    set_fb_blank,
    set_screen_brightness,
)
from backend.services.lcd_renderer import discover_fb_geometry


def test_discover_fb_geometry_default():
    with patch("os.path.exists", return_value=False):
        w, h, stride = discover_fb_geometry()
        assert w == 172
        assert h == 640
        assert stride == 704


def test_discover_fb_geometry_from_sysfs():
    def fake_exists(p):
        return p in [
            "/sys/class/graphics/fb0/stride",
            "/sys/class/graphics/fb0/virtual_size",
        ]

    def fake_open(p, *args, **kwargs):
        if p == "/sys/class/graphics/fb0/stride":
            return mock_open(read_data="704\n")()
        if p == "/sys/class/graphics/fb0/virtual_size":
            return mock_open(read_data="172,640\n")()
        return mock_open()()

    with patch("os.path.exists", side_effect=fake_exists), patch("builtins.open", side_effect=fake_open):
        w, h, stride = discover_fb_geometry()
        assert w == 172
        assert h == 640
        assert stride == 704


def test_discover_backlight_dir_fallback():
    with patch("os.path.exists", return_value=False), patch("os.path.isdir", return_value=False):
        assert discover_backlight_dir() is None


def test_discover_backlight_dir_found():
    def fake_exists(p):
        return p == "/sys/class/backlight/custom_bl/brightness"

    with (
        patch("backend.hardware.screen.glob.glob", return_value=["/sys/class/backlight/custom_bl"]),
        patch("os.path.isdir", return_value=True),
        patch("os.path.exists", side_effect=fake_exists),
    ):
        found = discover_backlight_dir()
        assert found == "/sys/class/backlight/custom_bl"


def test_get_effective_brightness(tmp_path):
    state_file = tmp_path / "screen_state.json"
    with patch("backend.hardware.screen.SCREEN_STATE_FILE", str(state_file)):
        # Default state
        assert get_effective_brightness() == 100

        # Custom daytime brightness
        state_file.write_text(json.dumps({"brightness": 80, "night_mode": False}))
        assert get_effective_brightness() == 80

        # Explicit power off overrides daytime brightness
        state_file.write_text(json.dumps({"power": False, "brightness": 80, "night_mode": False}))
        assert get_effective_brightness() == 0

        # String "off" also turns screen off
        state_file.write_text(json.dumps({"power": "off", "brightness": 95}))
        assert get_effective_brightness() == 0

        # Night mode active
        state_file.write_text(
            json.dumps(
                {
                    "power": True,
                    "brightness": 80,
                    "night_mode": True,
                    "night_start": "22:00",
                    "night_end": "06:00",
                    "night_brightness": 15,
                }
            )
        )
        with patch("backend.hardware.screen.is_in_time_window", return_value=True):
            assert get_effective_brightness() == 15

        with patch("backend.hardware.screen.is_in_time_window", return_value=False):
            assert get_effective_brightness() == 80


def test_set_screen_brightness_and_bl_power(tmp_path):
    bl_dir = tmp_path / "intel_backlight"
    bl_dir.mkdir(parents=True)
    br_file = bl_dir / "brightness"
    max_file = bl_dir / "max_brightness"
    power_file = bl_dir / "bl_power"
    br_file.write_text("0\n")
    max_file.write_text("1000\n")
    power_file.write_text("4\n")

    with patch("backend.hardware.screen.discover_backlight_dir", return_value=str(bl_dir)):
        success = set_screen_brightness(50)
        assert success is True
        assert br_file.read_text().strip() == "500"
        assert power_file.read_text().strip() == "0"

        # Clamping high
        set_screen_brightness(150)
        assert br_file.read_text().strip() == "1000"
        assert power_file.read_text().strip() == "0"

        # Turning off (0% or negative) blanks bl_power to 4 (FB_BLANK_POWERDOWN)
        set_screen_brightness(0)
        assert br_file.read_text().strip() == "0"
        assert power_file.read_text().strip() == "4"

        set_screen_brightness(-20)
        assert br_file.read_text().strip() == "0"
        assert power_file.read_text().strip() == "4"


def test_save_screen_state_power_toggle(tmp_path):
    state_file = tmp_path / "screen_state.json"
    bl_dir = tmp_path / "intel_backlight"
    bl_dir.mkdir(parents=True)
    br_file = bl_dir / "brightness"
    max_file = bl_dir / "max_brightness"
    power_file = bl_dir / "bl_power"
    br_file.write_text("1000\n")
    max_file.write_text("1000\n")
    power_file.write_text("0\n")

    with (
        patch("backend.hardware.screen.SCREEN_STATE_FILE", str(state_file)),
        patch("backend.hardware.screen.discover_backlight_dir", return_value=str(bl_dir)),
    ):
        # Turn screen off while preserving brightness=85
        saved = save_screen_state({"power": False, "brightness": 85})
        assert saved["power"] is False
        assert saved["brightness"] == 85
        assert br_file.read_text().strip() == "0"
        assert power_file.read_text().strip() == "4"

        # Updating brightness > 0 without explicit power=False auto-wakes the screen
        saved2 = save_screen_state({"brightness": 70})
        assert saved2["power"] is True
        assert saved2["brightness"] == 70
        assert br_file.read_text().strip() == "700"
        assert power_file.read_text().strip() == "0"


def test_find_fb_device_none():
    with patch("os.path.exists", return_value=False):
        assert find_fb_device() is None


def test_find_fb_device_prefers_dev_fb0():
    def fake_exists(p):
        return p == "/dev/fb0"

    with patch("os.path.exists", side_effect=fake_exists), patch("builtins.open", mock_open()):
        assert find_fb_device() == "/dev/fb0"


def test_find_fb_device_falls_back_to_host_dev_fb0():
    def fake_exists(p):
        return p == "/host/dev/fb0"

    with patch("os.path.exists", side_effect=fake_exists), patch("builtins.open", mock_open()):
        assert find_fb_device() == "/host/dev/fb0"


def test_find_fb_device_permission_error():
    def fake_exists(p):
        return p == "/host/dev/fb0"

    def fake_open(p, mode="r"):
        if p == "/host/dev/fb0" and ("w" in mode or "+" in mode):
            raise PermissionError("[Errno 1] Operation not permitted")
        return mock_open()()

    with patch("os.path.exists", side_effect=fake_exists), patch("builtins.open", side_effect=fake_open):
        # Writable only returns None because permission is denied
        assert find_fb_device(writable_only=True) is None
        # Non-writable returns the path
        assert find_fb_device(writable_only=False) == "/host/dev/fb0"


def test_find_fb_device_env_override():
    with (
        patch.dict("os.environ", {"FRAMEBUFFER": "/dev/fb99"}),
        patch("os.path.exists", side_effect=lambda p: p == "/dev/fb99"),
        patch("builtins.open", mock_open()),
    ):
        assert find_fb_device() == "/dev/fb99"


def test_set_fb_blank():
    with (
        patch("os.path.exists", side_effect=lambda p: p == "/sys/class/graphics/fb0/blank"),
        patch("builtins.open", mock_open()) as m_open,
    ):
        assert set_fb_blank(True) is True
        m_open().write.assert_called_with("0\n")

        assert set_fb_blank(False) is True
        m_open().write.assert_called_with("4\n")
