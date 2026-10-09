from unittest.mock import patch, MagicMock
from backend.services.notifications import (
    build_apprise_urls,
    mask_notification_config,
    unmask_notification_config,
    DEFAULT_NOTIFICATION_CONFIG,
    MASK_PLACEHOLDER,
)


def test_build_apprise_urls_synthesis():
    cfg = {
        "discord_enabled": True,
        "discord_webhook_url": "https://discord.com/api/webhooks/12345/abcdef",
        "telegram_enabled": True,
        "telegram_bot_token": "123:TOKEN",
        "telegram_chat_id": "-1009999",
        "email_enabled": True,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "alert_user@example.com",
        "smtp_pass": "secret#pass",
        "smtp_tls": True,
        "email_from": "nas@example.com",
        "email_to": "admin@example.com",
        "ntfy_enabled": True,
        "ntfy_url": "https://ntfy.sh",
        "ntfy_topic": "my_nas_alerts",
        "ntfy_token": "tk_123",
        "webhook_enabled": True,
        "webhook_url": "https://hooks.slack.com/services/T00/B00/X00",
        "apprise_urls": ["pover://userkey@apptoken"],
    }

    urls = build_apprise_urls(cfg)
    assert "https://discord.com/api/webhooks/12345/abcdef" in urls
    assert "tgram://123:TOKEN/-1009999" in urls
    assert any("mailtos://" in u and "smtp.example.com:587" in u and "to=admin%40example.com" in u for u in urls)
    assert any("ntfys://ntfy.sh/my_nas_alerts?token=tk_123" in u for u in urls)
    assert "https://hooks.slack.com/services/T00/B00/X00" in urls
    assert "pover://userkey@apptoken" in urls


def test_mask_and_unmask_notification_config():
    cfg = {
        "smtp_pass": "super_secret_smtp",
        "telegram_bot_token": "secret_tg_bot",
        "ntfy_token": "secret_ntfy_tk",
        "discord_webhook_url": "https://discord.com/api/webhooks/123/abc",
    }

    masked = mask_notification_config(cfg)
    assert masked["smtp_pass"] == MASK_PLACEHOLDER
    assert masked["telegram_bot_token"] == MASK_PLACEHOLDER
    assert masked["ntfy_token"] == MASK_PLACEHOLDER
    assert masked["discord_webhook_url"] == "https://discord.com/api/webhooks/123/abc"

    # Simulated incoming payload from UI with masked secrets preserved
    incoming = dict(masked)
    incoming["discord_webhook_url"] = "https://discord.com/api/webhooks/updated/url"

    unmasked = unmask_notification_config(incoming, cfg)
    assert unmasked["smtp_pass"] == "super_secret_smtp"
    assert unmasked["telegram_bot_token"] == "secret_tg_bot"
    assert unmasked["ntfy_token"] == "secret_ntfy_tk"
    assert unmasked["discord_webhook_url"] == "https://discord.com/api/webhooks/updated/url"


def test_api_get_and_post_notifications(client, auth_headers, tmp_path):
    with patch("backend.services.notifications.NOTIFICATIONS_FILE", str(tmp_path / "notifications.json")):
        # GET config
        res = client.get("/api/notifications/config", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "discord_enabled" in data
        assert "telegram_enabled" in data
        assert "email_enabled" in data

        # POST config
        update_payload = dict(data)
        update_payload["enabled"] = True
        update_payload["discord_enabled"] = True
        update_payload["discord_webhook_url"] = "https://discord.com/api/webhooks/999/xyz"
        update_payload["email_enabled"] = True
        update_payload["smtp_host"] = "smtp.mailgun.org"
        update_payload["smtp_pass"] = "mypassword123"

        post_res = client.post("/api/notifications/config", json=update_payload, headers=auth_headers)
        assert post_res.status_code == 200
        saved = post_res.json()["config"]
        assert saved["enabled"] is True
        assert saved["discord_enabled"] is True
        assert saved["smtp_pass"] == MASK_PLACEHOLDER  # Masked on return


def test_api_test_channel_endpoint(client, auth_headers):
    with patch("backend.services.notifications._dispatch_apprise", return_value=True):
        req = {
            "channel": "discord",
            "config": {
                "discord_webhook_url": "https://discord.com/api/webhooks/123/fake",
            },
        }
        res = client.post("/api/notifications/test-channel", json=req, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["success"] is True
        assert "latency_ms" in data
