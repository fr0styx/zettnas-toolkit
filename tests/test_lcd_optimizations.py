import json
from unittest.mock import mock_open, patch

from backend.hardware.screen import (
    discover_backlight_dir,
    get_effective_brightness,
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

        # Night mode active
        state_file.write_text(
            json.dumps(
                {
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


def test_set_screen_brightness(tmp_path):
    bl_dir = tmp_path / "intel_backlight"
    bl_dir.mkdir(parents=True)
    br_file = bl_dir / "brightness"
    max_file = bl_dir / "max_brightness"
    br_file.write_text("0\n")
    max_file.write_text("1000\n")

    with patch("backend.hardware.screen.discover_backlight_dir", return_value=str(bl_dir)):
        success = set_screen_brightness(50)
        assert success is True
        assert br_file.read_text().strip() == "500"

        # Clamping
        set_screen_brightness(150)
        assert br_file.read_text().strip() == "1000"

        set_screen_brightness(-20)
        assert br_file.read_text().strip() == "0"
