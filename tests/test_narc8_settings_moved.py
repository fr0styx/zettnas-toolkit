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
    monkeypatch.setattr(alert_rules, "add_event", lambda level, title, msg: None)
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
