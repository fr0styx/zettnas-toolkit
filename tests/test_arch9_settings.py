"""ARCH-9: typed settings from the environment."""

import os

from backend import config
from backend.settings import Settings, load_settings, markdown


def test_defaults_without_environment():
    s, problems = load_settings({})
    assert s == Settings() and problems == []
    assert s.port == 8082 and s.trusted_proxies == ("127.0.0.1", "::1") and s.enable_fb is True


def test_values_are_converted():
    s, problems = load_settings(
        {
            "PORT": "9000",
            "ENABLE_API_DOCS": "yes",
            "TRUSTED_PROXIES": "10.0.0.1, 10.0.0.2",
            "LCD_FORMAT": "PNG",
            "FAN_KICKSTART_SECS": "1.5",
        }
    )
    assert problems == []
    assert (s.port, s.enable_api_docs, s.trusted_proxies, s.lcd_format, s.fan_kickstart_secs) == (
        9000,
        True,
        ("10.0.0.1", "10.0.0.2"),
        "png",
        1.5,
    )


def test_unusable_values_keep_the_default_and_say_why():
    s, problems = load_settings(
        {"NUT_PORT": "abc", "LCD_FPS": "500", "UPDATE_CHANNEL": "nightly", "SHOW_OS_DISK": "maybe"}
    )
    assert (s.nut_port, s.lcd_fps, s.update_channel, s.show_os_disk) == (3493, 5, "stable", True)
    assert len(problems) == 4 and all("can't be used" in p for p in problems)
    assert any(p.startswith("NUT_PORT=") and "expected a number" in p for p in problems)


def test_old_variable_names_still_work():
    s, _ = load_settings({"ZERO_RPM_TEMP": "30", "ZERO_RPM_NVME": "45"})
    assert s.zero_rpm_stop_temp == 30 and s.zero_rpm_nvme_ceiling == 45


def test_config_reads_from_settings():
    assert config.SETTINGS.port == config.PORT
    assert list(config.SETTINGS.trusted_proxies) == config.TRUSTED_PROXIES
    assert config.SETTINGS.max_body_mb * 1024 * 1024 == config.MAX_BODY_BYTES


def test_configuration_page_is_generated_from_the_declarations():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "CONFIGURATION.md")
    with open(path, encoding="utf-8") as f:
        assert f.read() == markdown(), "run: python -m backend.settings --markdown > docs/CONFIGURATION.md"
