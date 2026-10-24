import io
import json
import logging
import zipfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import AuthenticatedPrincipal
from backend.logging_config import (
    LOG_RING_BUFFER,
    JSONLogFormatter,
    RingBufferHandler,
    correlation_id_ctx,
    get_recent_logs,
    sanitize_dict,
    sanitize_string,
)
from backend.main import app


def test_json_formatter_structured_output():
    formatter = JSONLogFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="User authenticated successfully for zat_1234567890abcdef12345",
        args=(),
        exc_info=None,
    )

    # Format without correlation ID
    output = formatter.format(record)
    data = json.loads(output)
    assert data["level"] == "INFO"
    assert data["logger"] == "test_logger"
    assert data["line"] == 42
    assert "zat_[REDACTED]" in data["message"]
    assert "zat_1234567890abcdef12345" not in data["message"]

    # Format with correlation ID
    token = correlation_id_ctx.set("corr-trace-xyz-789")
    try:
        output_with_corr = formatter.format(record)
        data_corr = json.loads(output_with_corr)
        assert data_corr["correlation_id"] == "corr-trace-xyz-789"
    finally:
        correlation_id_ctx.reset(token)


def test_ring_buffer_handler():
    handler = RingBufferHandler()
    handler.setFormatter(JSONLogFormatter())
    record = logging.LogRecord(
        name="ring_test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=10,
        msg="Test ring buffer entry",
        args=(),
        exc_info=None,
    )

    initial_len = len(LOG_RING_BUFFER)
    handler.emit(record)
    assert len(LOG_RING_BUFFER) == initial_len + 1

    recent = get_recent_logs(max_lines=5)
    assert any("Test ring buffer entry" in line for line in recent)


def test_sanitization_patterns():
    # 1. Private key block
    priv_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
    assert sanitize_string(priv_key) == "[REDACTED_PRIVATE_KEY_BLOCK]"

    # 2. Discord webhook
    discord_url = "https://discord.com/api/webhooks/123456789/SuperSecretWebhookToken12345"
    assert sanitize_string(discord_url) == "https://discord.com/api/webhooks/123456789/[REDACTED_WEBHOOK]"

    # 3. Telegram bot token
    telegram_url = "https://api.telegram.org/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendMessage"
    assert "[REDACTED_BOT_TOKEN]" in sanitize_string(telegram_url)

    # 4. Apprise URLs
    tgram_apprise = "tgram://123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/987654321"
    assert sanitize_string(tgram_apprise) == "tgram://[REDACTED]"

    discord_apprise = "discord://123456789/AbCdEfGhIjKlMnOpQrStUvWxYz"
    assert sanitize_string(discord_apprise) == "discord://[REDACTED]"

    # 5. Credential in URL
    mail_url = "mailto://admin:SuperSecretPass123@smtp.mailprovider.com:587"
    assert sanitize_string(mail_url) == "mailto://admin:[REDACTED]@smtp.mailprovider.com:587"

    # 6. Bearer token
    bearer_str = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    assert sanitize_string(bearer_str) == "Authorization: Bearer [REDACTED]"

    # 7. ZAT token
    zat_str = "Token is zat_9876543210fedcba9876"
    assert sanitize_string(zat_str) == "Token is zat_[REDACTED]"

    # 8. URL query parameter
    url_param = "https://example.com/api?secret=super_secret_token&user=test"
    assert sanitize_string(url_param) == "https://example.com/api?secret=[REDACTED]&user=test"


def test_sanitize_dict_recursive():
    raw_dict = {
        "status": "ok",
        "password": "plain_password_123",
        "smtp_pass": "smtp_secret_456",
        "api_key": "key_xyz_789",
        "config": {
            "auth_token": "token_abc_000",
            "safe_field": "visible_value",
            "webhook_url": "https://discord.com/api/webhooks/999/tokenSecret",
        },
        "items": [
            {"secret": "nested_secret_1"},
            {"name": "harmless_item"},
            "mailto://bot:mypassword@smtp.org",
        ],
    }

    clean = sanitize_dict(raw_dict)
    assert clean["status"] == "ok"
    assert clean["password"] == "[REDACTED]"
    assert clean["smtp_pass"] == "[REDACTED]"
    assert clean["api_key"] == "[REDACTED]"
    assert clean["config"]["auth_token"] == "[REDACTED]"
    assert clean["config"]["safe_field"] == "visible_value"
    assert "[REDACTED_WEBHOOK]" in clean["config"]["webhook_url"]
    assert clean["items"][0]["secret"] == "[REDACTED]"
    assert clean["items"][1]["name"] == "harmless_item"
    assert "[REDACTED]" in clean["items"][2]
    assert "mypassword" not in clean["items"][2]


def test_correlation_id_middleware(client, monkeypatch):
    import time

    from backend.state import Z_STATE

    # a fresh collector heartbeat, so health is 200 however long the suite has run
    monkeypatch.setattr(Z_STATE, "collector_heartbeat", time.time())
    # 1. Without header: server generates a correlation ID
    res = client.get("/api/health")
    assert res.status_code == 200
    corr_id = res.headers.get("X-Correlation-ID")
    assert corr_id is not None
    assert len(corr_id) >= 8

    # 2. With header: server propagates incoming correlation ID
    custom_id = "tracing-req-batch6-xyz123"
    res2 = client.get("/api/health", headers={"X-Correlation-ID": custom_id})
    assert res2.status_code == 200
    assert res2.headers.get("X-Correlation-ID") == custom_id


def test_diagnostics_bundle_endpoint(client, auth_headers):
    res = client.get("/api/system/diagnostics-bundle", headers=auth_headers)
    assert res.status_code == 200
    assert res.headers.get("Content-Type") == "application/zip"
    disposition = res.headers.get("Content-Disposition", "")
    assert "attachment" in disposition
    assert "zettnas_diagnostics_" in disposition
    assert disposition.endswith('.zip"') or disposition.endswith(".zip")

    # Read zip bytes and inspect archive contents
    zip_bytes = io.BytesIO(res.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        namelist = zf.namelist()
        required_files = [
            "system_summary.json",
            "hardware_telemetry.json",
            "storage_and_smart.json",
            "network_topology.json",
            "container_manifests.json",
            "notifications_summary.json",
            "system_events.json",
            "recent_logs.log",
        ]
        for f in required_files:
            assert f in namelist, f"Missing {f} in diagnostics zip"

        # Check system_summary.json
        summary_raw = zf.read("system_summary.json").decode("utf-8")
        summary = json.loads(summary_raw)
        assert "toolkit_version" in summary
        assert "platform" in summary
        assert "chassis_model" in summary
        assert "uptime_seconds" in summary

        # Check hardware_telemetry.json
        telemetry_raw = zf.read("hardware_telemetry.json").decode("utf-8")
        telemetry = json.loads(telemetry_raw)
        assert "fan_state_tracker" in telemetry
        assert "ups_status" in telemetry

        # Check recent_logs.log
        logs_text = zf.read("recent_logs.log").decode("utf-8")
        assert isinstance(logs_text, str)
        # Ensure no raw passwords/tokens exist in logs text
        assert "zat_" not in logs_text or "zat_[REDACTED]" in logs_text


def test_env_var_and_secret_sanitization():
    # Docker inspect Env list sanitization
    env_list = [
        "MYSQL_ROOT_PASSWORD=superSecretPassword123",
        "POSTGRES_PASSWORD=my_database_password",
        "API_SECRET_KEY=secret_token_value_456",
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "PORT=8080",
    ]
    cleaned = sanitize_dict(env_list)
    assert cleaned[0] == "MYSQL_ROOT_PASSWORD=[REDACTED]"
    assert cleaned[1] == "POSTGRES_PASSWORD=[REDACTED]"
    assert cleaned[2] == "API_SECRET_KEY=[REDACTED]"
    assert cleaned[3] == "PATH=/usr/local/bin:/usr/bin:/bin"
    assert cleaned[4] == "PORT=8080"

    # WireGuard private key
    wg_str = "PrivateKey = YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY3ODk="
    assert sanitize_string(wg_str) == "PrivateKey = [REDACTED_KEY]"

    # AWS access key
    aws_str = "Credentials with AKIAIOSFODNN7EXAMPLE key"
    assert sanitize_string(aws_str) == "Credentials with [REDACTED_AWS_KEY] key"


def test_diagnostics_bundle_with_client_telemetry(client, auth_headers):
    payload = {
        "client_environment": {
            "browser": {"user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            "screen_geometry": {"viewport_width": 1920, "viewport_height": 1080},
            "gpu_telemetry": {"renderer": "Apple M1", "hardware_accelerated": True},
        },
        "frontend_logs": [
            {
                "ts": "2026-10-13T12:00:00Z",
                "level": "error",
                "source": "console.error",
                "message": "Sample frontend error with zat_1234567890abcdef12345",
            }
        ],
    }

    res = client.post("/api/system/diagnostics-bundle", json=payload, headers=auth_headers)
    assert res.status_code == 200
    assert res.headers.get("Content-Type") == "application/zip"

    zip_bytes = io.BytesIO(res.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        namelist = zf.namelist()
        assert "client_environment.json" in namelist
        assert "frontend_console_errors.log" in namelist
        assert "kernel_telemetry.json" in namelist
        assert "docker_diagnostics.json" in namelist
        assert "vm_hypervisor.json" in namelist

        client_env = json.loads(zf.read("client_environment.json").decode("utf-8"))
        assert client_env["browser"]["user_agent"] == "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

        f_log = zf.read("frontend_console_errors.log").decode("utf-8")
        assert "Sample frontend error" in f_log
        assert "zat_[REDACTED]" in f_log


def test_diagnostics_summary_endpoint(client, auth_headers):
    res = client.get("/api/system/diagnostics-summary", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "toolkit_version" in data
    assert "platform" in data
    assert "chassis" in data
    assert "uptime_hours" in data
    assert "memory" in data
    assert "storage" in data
    assert "docker" in data
    assert "vms" in data
    assert "support_markdown" in data
    assert "### ZettNAS Toolkit Support Diagnostics" in data["support_markdown"]
