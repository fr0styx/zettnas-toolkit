import json
from unittest.mock import MagicMock, patch

import pytest

from backend.services.notifications import (
    _alert_history,
    _dispatch_ntfy,
    _dispatch_unraid,
    _dispatch_webhook,
    load_notification_config,
    save_notification_config,
    send_notification,
)
from backend.services.notifications import (
    test_notification as run_test_notification,
)


@pytest.fixture(autouse=True)
def reset_alert_history(tmp_path, monkeypatch):
    _alert_history.clear()
    cfg_file = str(tmp_path / "notifications.json")
    monkeypatch.setattr("backend.services.notifications.NOTIFICATIONS_FILE", cfg_file)


def test_default_notification_config():
    cfg = load_notification_config()
    assert cfg["enabled"] is False
    assert cfg["unraid_notify"] is True
    assert cfg["notify_on_smart"] is True
    assert cfg["notify_on_temp"] is True
    assert cfg["cooldown_seconds"] == 1800


def test_save_and_load_notification_config():
    save_notification_config({"enabled": True, "ntfy_topic": "zettnas-test"})
    loaded = load_notification_config()
    assert loaded["enabled"] is True
    assert loaded["ntfy_topic"] == "zettnas-test"
    # Defaults preserved
    assert loaded["notify_on_fan"] is True


def test_send_notification_disabled_by_default():
    res = send_notification("Test", "Message")
    assert res["dispatched"] is False
    assert res["reason"] == "disabled"


def test_send_notification_event_type_toggle():
    save_notification_config({"enabled": True, "notify_on_smart": False})
    res = send_notification("SMART Fail", "Drive broken", level="critical", event_type="smart")
    assert res["dispatched"] is False
    assert res["reason"] == "smart_disabled"


def test_notification_deduplication_and_escalation():
    save_notification_config({"enabled": True, "cooldown_seconds": 600})

    with (
        patch("backend.services.notifications._dispatch_unraid", return_value=True),
        patch("backend.services.notifications._find_unraid_notify", return_value="/mock/notify"),
    ):
        # First send succeeds
        r1 = send_notification("Drive Hot", "sda is 45C", level="warning", event_type="temp", dedup_key="sda_temp")
        assert r1["dispatched"] is True

        # Second send within cooldown suppressed
        r2 = send_notification("Drive Hot", "sda is 45C", level="warning", event_type="temp", dedup_key="sda_temp")
        assert r2["dispatched"] is False
        assert r2["reason"] == "cooldown"

        # Escalation to critical bypasses cooldown
        r3 = send_notification(
            "Drive Critical", "sda is 60C", level="critical", event_type="temp", dedup_key="sda_temp"
        )
        assert r3["dispatched"] is True


def test_dispatch_unraid_arguments():
    with patch("subprocess.run") as mock_run:
        ok = _dispatch_unraid("/mock/notify", "Drive Alert", "sdb failed", "critical")
        assert ok is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["/mock/notify", "-e", "ZettNAS", "-s", "Drive Alert", "-d", "sdb failed", "-i", "alert"]


def test_dispatch_ntfy():
    cfg = {"ntfy_url": "https://ntfy.sh", "ntfy_topic": "homelab-nas", "ntfy_token": "secret123"}
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client.post.return_value = mock_resp
    with patch("backend.services.notifications.get_http_client", return_value=mock_client):
        ok = _dispatch_ntfy(cfg, "CPU Warning", "High Temp", "warning")
        assert ok is True

        mock_client.post.assert_called_once()
        args, kwargs = mock_client.post.call_args
        assert args[0] == "https://ntfy.sh/homelab-nas"
        assert kwargs["headers"]["Title"] == "CPU Warning"
        assert kwargs["headers"]["Priority"] == "4"
        assert kwargs["headers"]["Authorization"] == "Bearer secret123"


def test_dispatch_webhook_discord():
    cfg = {"webhook_url": "https://discord.com/api/webhooks/123/token"}
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_client.post.return_value = mock_resp
    with patch("backend.services.notifications.get_http_client", return_value=mock_client):
        ok = _dispatch_webhook(cfg, "System Alert", "Fan Stopped", "critical")
        assert ok is True

        mock_client.post.assert_called_once()
        args, kwargs = mock_client.post.call_args
        assert args[0] == "https://discord.com/api/webhooks/123/token"
        payload = kwargs["json"]
        assert payload["username"] == "ZettNAS"
        assert payload["embeds"][0]["title"] == "System Alert"
        assert payload["embeds"][0]["color"] == 0xEF4444


def test_test_notification_dry_run():
    cfg = {"unraid_notify": False, "ntfy_enabled": True, "ntfy_topic": "test", "webhook_enabled": False}
    with patch("backend.services.notifications._dispatch_ntfy", return_value=True):
        res = run_test_notification(cfg)
        assert res["status"] == "ok"
        assert res["tested_channels"]["ntfy"] is True
