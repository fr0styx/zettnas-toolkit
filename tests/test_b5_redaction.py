"""B5: a diagnostics bundle never carries a secret, whatever kind and wherever it was planted."""

import io
import json
import zipfile

import pytest

# Fake secrets are put together here, so secret scanners don't take this file for a leak
SLACK = "https://hooks." + "slack.com/services/"
DISCORD = "https://discord.com/api/" + "webhooks/"
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
TG = "123456789:" + "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"

# (what it is, the secret part, how it appears in the source)
SECRETS = [
    ("password in key=value", "hunter2-Secret-9", "login failed password=hunter2-Secret-9 for admin"),
    (
        "bearer token",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlMTIz",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlMTIz",
    ),
    (
        "ZettNAS API token",
        "zat_Q2xhdWRlU2VjcmV0VG9rZW4xMjM0NTY3",
        "used zat_Q2xhdWRlU2VjcmV0VG9rZW4xMjM0NTY3 from cron",
    ),
    (
        "Discord webhook",
        "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-SecretHook",
        DISCORD + "1234567890/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-SecretHook",
    ),
    ("Slack webhook", "T00000000/B00000000/" + "X" * 24, SLACK + "T00000000/B00000000/" + "X" * 24),
    ("Telegram bot token", TG, "tgram://bot" + TG + "/12345"),
    ("AWS key", AWS, "rclone s3 access_key_id " + AWS),
    (
        "private key",
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7",
        "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\n-----END PRIVATE KEY-----",
    ),
    (
        "password hash",
        "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA",
        "user row $argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA",
    ),
    ("basic auth", "YWRtaW46c3VwZXJzZWNyZXQ=", "Authorization: Basic YWRtaW46c3VwZXJzZWNyZXQ="),
    ("credentials in a URL", "pa55w0rd-InUrl", "fetching https://backup:pa55w0rd-InUrl@nas.example/repo"),
    (
        "WireGuard key",
        "yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk=",
        "PrivateKey = yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk=",
    ),
    ("token in a query string", "qs-secret-77abc", "GET /share?token=qs-secret-77abc"),
    ("container env password", "mysql-root-Secret", "MYSQL_ROOT_PASSWORD=mysql-root-Secret"),
    (
        "data key",
        "ZmVybmV0LWtleS1zZWNyZXQtMzItYnl0ZXMtbG9uZw==",
        "ZETTNAS_DATA_KEY=ZmVybmV0LWtleS1zZWNyZXQtMzItYnl0ZXMtbG9uZw==",
    ),
]


@pytest.fixture
def planted(monkeypatch, tmp_path):
    from backend.api import diagnostics
    from backend.state import Z_STATE

    lines = [s[2] for s in SECRETS]
    monkeypatch.setattr(diagnostics, "get_recent_logs", lambda max_lines=1000: lines)
    monkeypatch.setattr(
        diagnostics,
        "read_docker_containers",
        lambda: [
            {"name": "db", "image": "mariadb", "env": [s[2] for s in SECRETS if "=" in s[2]], "labels": {"x": lines[1]}}
        ],
    )
    monkeypatch.setattr(
        Z_STATE, "event_log", [{"title": "Webhook", "message": lines[3]}, {"title": "Token", "message": lines[2]}]
    )
    notif = tmp_path / "notifications.json"
    notif.write_text(
        json.dumps(
            {
                "enabled": True,
                "urls": [lines[3], lines[5]],
                "discord_webhook": lines[3],
                "telegram_token": SECRETS[5][1],
            }
        )
    )
    monkeypatch.setattr(diagnostics, "NOTIFICATIONS_FILE", str(notif))
    return {
        "frontend_logs": [{"level": "error", "message": line, "stack": lines[1]} for line in lines],
        "client_environment": {"url": SECRETS[12][2], "auth": lines[1]},
    }


def test_no_secret_survives_into_the_bundle(planted):
    from backend.api import diagnostics

    data = diagnostics._build_bundle_sync(planted)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        text = "\n".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())
    leaked = [kind for kind, secret, _ in SECRETS if secret in text]
    assert not leaked, f"secrets left in the diagnostics bundle: {leaked}"
    assert "recent_logs.log" in zipfile.ZipFile(io.BytesIO(data)).namelist()
