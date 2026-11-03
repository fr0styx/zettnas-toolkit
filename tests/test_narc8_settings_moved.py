"""NARC-8: settings that moved into backend.settings are read from SETTINGS."""

import dataclasses

import pytest

from backend import config
from backend.services import alert_rules, thumbs


def test_thumb_cache_limit_comes_from_settings_with_a_floor(monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", dataclasses.replace(config.SETTINGS, thumb_cache_mb=8))
    assert thumbs.cache_limit_bytes() == 16 * 1024 * 1024
    monkeypatch.setattr(config, "SETTINGS", dataclasses.replace(config.SETTINGS, thumb_cache_mb=100))
    assert thumbs.cache_limit_bytes() == 100 * 1024 * 1024


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr("backend.services.notifications.send_notification", lambda n: sent.append(n))
    monkeypatch.setattr(alert_rules, "add_event", lambda level, title, msg, *a: None)
    monkeypatch.setattr(alert_rules, "check_app_memory", lambda now: None)
    monkeypatch.setattr("backend.services.ups_watchdog.is_simulation_active", lambda: False)

    def broken():
        raise OSError("no ups config")

    monkeypatch.setattr("backend.hardware.ups.load_ups_config", broken)
    alert_rules.reset_failsafe_state()
    yield sent
    alert_rules.reset_failsafe_state()


def _on_battery(charge, minutes):
    return {"available": True, "status": "OB", "battery_charge_pct": charge, "time_left_min": minutes}


def test_ups_thresholds_fall_back_to_settings_when_the_ups_config_is_unreadable(alerts, monkeypatch):
    s = dataclasses.replace(config.SETTINGS, ups_failsafe_battery_min=30.0, ups_failsafe_runtime_min=1.0)
    monkeypatch.setattr(alert_rules, "SETTINGS", s)
    alert_rules.evaluate_system_alerts({}, _on_battery(25, 60))
    assert "ups_critical" in alert_rules._active_alerts


def test_ups_fallback_thresholds_not_crossed_means_no_critical_alert(alerts, monkeypatch):
    s = dataclasses.replace(config.SETTINGS, ups_failsafe_battery_min=20.0, ups_failsafe_runtime_min=5.0)
    monkeypatch.setattr(alert_rules, "SETTINGS", s)
    alert_rules.evaluate_system_alerts({}, _on_battery(25, 60))
    assert "ups_onbatt" in alert_rules._active_alerts
    assert "ups_critical" not in alert_rules._active_alerts


def test_observer_mode_setting_makes_an_unknown_host_an_observer(monkeypatch):
    from unittest.mock import patch

    from backend.hardware.pal import detect

    for var in ("ZETTNAS_PLATFORM", "ZETTNAS_OBSERVER_ADAPTER", "ZETTNAS_PAL_MODE"):
        monkeypatch.delenv(var, raising=False)
    with (
        patch("backend.hardware.pal.base._find_emhttp_dir", return_value=None),
        patch("os.path.isfile", return_value=False),
        patch("os.path.exists", return_value=False),
        patch("os.path.isdir", return_value=False),
    ):
        monkeypatch.setattr(detect, "SETTINGS", dataclasses.replace(config.SETTINGS, observer_mode=True))
        assert detect.StoragePlatformDetector.detect() == detect.PlatformType.GENERIC_OBSERVER
        monkeypatch.setattr(detect, "SETTINGS", dataclasses.replace(config.SETTINGS, observer_mode=False))
        assert detect.StoragePlatformDetector.detect() == detect.PlatformType.GENERIC_LINUX


def test_sqlite_vec_path_setting_is_tried_first_when_the_package_is_missing(monkeypatch):
    import sys

    from backend.services import rag_embeddings

    monkeypatch.setitem(sys.modules, "sqlite_vec", None)  # import fails
    tried = []

    class Conn:
        def load_extension(self, path):
            tried.append(path)
            if path != "/opt/vec0.so":
                raise OSError("not here")

    monkeypatch.setattr(
        rag_embeddings, "SETTINGS", dataclasses.replace(config.SETTINGS, sqlite_vec_path="/opt/vec0.so")
    )
    assert rag_embeddings.load_sqlite_vec_extension(Conn()) is True
    assert tried == ["/opt/vec0.so"]


def test_auto_ingest_env_setting_starts_a_copy_without_the_ui_switch(monkeypatch):
    from backend.services import copy_engine

    monkeypatch.setattr("backend.fsutil.read_json", lambda path, default: {})
    monkeypatch.setattr(config, "SETTINGS", dataclasses.replace(config.SETTINGS, auto_ingest_enabled=False))
    monkeypatch.setattr(copy_engine.Z_STATE, "pending_ingest", {"slot": "sd"}, raising=False)
    copy_engine._maybe_trigger_auto_ingest("sd")
    assert copy_engine.Z_STATE.pending_ingest is None  # off: a pending ingest for the slot is dropped


def test_push_contact_and_host_etc_come_from_settings():
    from backend.hardware import host_telemetry
    from backend.services import web_push

    assert config.SETTINGS.push_contact == web_push.CONTACT
    assert config.SETTINGS.host_etc == host_telemetry.HOST_ETC
