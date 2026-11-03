"""NUX-3: the built-in system alerts carry their translation keys, for the log and the push."""

import pytest

from backend.services import alert_rules


@pytest.fixture
def sent(monkeypatch):
    out = {"events": [], "pushes": []}
    monkeypatch.setattr(alert_rules, "add_event", lambda level, title, msg, details=None: out["events"].append(details))
    monkeypatch.setattr("backend.services.notifications.send_notification", lambda n: out["pushes"].append(n))
    monkeypatch.setattr("backend.config.APP_MEMORY_WARN_MB", 0, raising=False)
    monkeypatch.setattr("backend.services.ups_watchdog.is_simulation_active", lambda: False)
    monkeypatch.setattr(
        "backend.hardware.ups.load_ups_config", lambda: {"battery_threshold_pct": 20, "runtime_threshold_min": 5}
    )
    alert_rules.reset_failsafe_state()
    yield out
    alert_rules.reset_failsafe_state()


def keys(out):
    return [e["title_key"] for e in out["events"] if e]


def test_unraid_and_ups_alerts_and_their_end(sent):
    alert_rules.evaluate_system_alerts({"available": True, "state": "error"}, {})
    alert_rules.evaluate_system_alerts(
        {}, {"available": True, "status": "OB LB", "battery_charge_pct": 12, "time_left_min": 3}
    )
    assert keys(sent) == ["alert.unraid_error.title", "alert.ups_onbatt.title", "alert.ups_critical.title"]
    assert sent["events"][2]["params"] == {"charge": 12, "runtime": 3}
    assert sent["pushes"][1]["text"]["msg_key"] == "alert.ups_onbatt.msg"
    alert_rules.evaluate_system_alerts({}, {"available": True, "status": "OL"})
    assert keys(sent)[-2:] == ["alert.ups_power_back.title", "alert.ups_recovering.title"]
    assert sent["pushes"][-1]["text"]["title_key"] == "alert.ups_recovering.title"


def test_unknown_runtime_says_so(sent):
    alert_rules.evaluate_system_alerts({}, {"available": True, "status": "OB"})
    assert sent["events"][0]["params"] == {"runtime": "?"}


def test_memory_alert_and_its_end(monkeypatch, sent):
    from backend import config

    monkeypatch.setattr(config, "APP_MEMORY_WARN_MB", 100, raising=False)
    alert_rules.check_app_memory(1000.0, measure=lambda: 150.4)
    alert_rules.check_app_memory(2000.0, measure=lambda: 60.0)
    assert keys(sent) == ["alert.app_memory.title", "alert.app_memory_ok.title"]
    assert sent["events"][0]["params"] == {"mb": "150", "warn": 100}
