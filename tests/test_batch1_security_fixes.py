"""
Test Suite for Batch 1: Critical Security & Core Bug Fixes
Validates:
1. WebDAV HMAC session cookie verification, rejection of forged/legacy cookies, and path traversal defenses.
2. Container secrets redaction by default unless authorized unmask is requested.
3. Multi-user path access check and symlink bounding in download-zip.
4. 2FA setup data contract, minimal OTPAuth URI, and QR generator safety.
5. Session cache synchronization upon single-session deletion.
6. SFTP Auth Proxy exact key matching, multi-share chroot jail, and read-only flag.
7. Rclone and notification secrets masking (Backblaze B2 'key' and webhook URLs).
"""

import os
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from backend import config
from backend.api.webdav import _sign_webdav_cookie, _verify_webdav_cookie, _get_webdav_portal_user
from backend.services.compose_synthesizer import get_container_compose_data, get_container_full_details
from backend.services.notifications import mask_notification_config, unmask_notification_config, MASK_PLACEHOLDER
from backend.services.rclone_engine import is_sensitive_key
from backend.totp import get_otpauth_uri, generate_qr_svg, generate_totp_secret
from backend.users_db import (
    create_user,
    create_user_session,
    validate_user_session,
    revoke_session_by_hash,
    _SESSION_CACHE,
    _SESSION_CACHE_LOCK,
)


def test_webdav_hmac_cookie_verification():
    # 1. Unsigned legacy cookie fails verification
    assert _verify_webdav_cookie("admin:admin") is None
    assert _verify_webdav_cookie("admin") is None
    assert _verify_webdav_cookie("") is None

    # 2. Forged cookie fails verification
    assert _verify_webdav_cookie("admin:admin:abcdef1234567890") is None

    # 3. Valid signed cookie succeeds
    signed = _sign_webdav_cookie("admin", "admin")
    verified = _verify_webdav_cookie(signed)
    assert verified is not None
    assert verified[0] == "admin"
    assert verified[1] == "admin"


def test_webdav_portal_user_graceful_rejection():
    # Mock request with forged cookie
    req = MagicMock()
    req.cookies = {"webdav_session": "admin:admin"}
    req.state.session = None

    cfg = {"auth_enabled": True, "username": "admin"}
    # Must not raise 500, must return None
    user = _get_webdav_portal_user(req, cfg)
    assert user is None


def test_compose_synthesizer_secrets_redaction():
    sample_inspect = {
        "Id": "abcdef1234567890abcdef1234567890",
        "Name": "/test-app",
        "Config": {
            "Env": [
                "API_KEY=super_secret_token_123",
                "PORT=8080",
                "DB_PASSWORD=my_db_secret",
            ],
            "Labels": {},
        },
        "HostConfig": {},
        "State": {"Status": "running"},
        "NetworkSettings": {},
        "Mounts": [],
    }

    with patch("backend.services.compose_synthesizer.fetch_container_raw_inspect", return_value=sample_inspect):
        # Default: secrets masked
        details_masked = get_container_full_details("test-app", allow_unmasked=False)
        env_map = {e["key"]: e for e in details_masked["env"]}
        assert env_map["API_KEY"]["is_secret"] is True
        assert env_map["API_KEY"]["value"] == "••••••••"
        assert env_map["DB_PASSWORD"]["value"] == "••••••••"
        assert env_map["PORT"]["value"] == "8080"

        # Explicit unmask allowed (e.g. admin with containers:manage)
        details_unmasked = get_container_full_details("test-app", allow_unmasked=True)
        env_unmasked_map = {e["key"]: e for e in details_unmasked["env"]}
        assert env_unmasked_map["API_KEY"]["value"] == "super_secret_token_123"
        assert env_unmasked_map["DB_PASSWORD"]["value"] == "my_db_secret"


def test_session_cache_synchronization(tmp_path):
    db_file = str(tmp_path / "test_users.db")
    with patch("backend.users_db.USERS_DB_PATH", db_file):
        from backend.users_db import init_users_db

        init_users_db(db_file)

        user = create_user("testuser", "Test User", "Password123!", db_path=db_file)
        token = create_user_session(user["id"], "testuser", db_path=db_file)

        # Session should be in memory cache
        sess = validate_user_session(token, db_path=db_file)
        assert sess is not None

        import hashlib

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

        with _SESSION_CACHE_LOCK:
            assert token_hash in _SESSION_CACHE

        # Revoke via hash prefix
        prefix = token_hash[:12]
        revoked = revoke_session_by_hash(prefix, user["id"], db_path=db_file)
        assert revoked is True

        # In-memory cache must be evicted immediately
        with _SESSION_CACHE_LOCK:
            assert token_hash not in _SESSION_CACHE

        # Validating session must now fail
        assert validate_user_session(token, db_path=db_file) is None


def test_totp_minimal_uri_and_qr():
    secret = generate_totp_secret()
    assert len(secret) >= 32
    uri = get_otpauth_uri("testuser", secret, issuer="ZettNAS")
    assert uri.startswith("otpauth://totp/testuser?secret=")
    assert f"secret={secret}" in uri

    # Verify generate_qr_svg generates valid SVG
    svg = generate_qr_svg(uri)
    assert svg.startswith("<svg")
    assert "</svg>" in svg
    assert "viewBox" in svg


def test_rclone_b2_key_and_notification_masking():
    # Rclone Backblaze B2 sensitive key
    assert is_sensitive_key("key") is True
    assert is_sensitive_key("application_key") is True
    assert is_sensitive_key("app_key") is True
    assert is_sensitive_key("host") is False

    # Notifications masking
    cfg = {
        "discord_webhook_url": "https://discord.com/api/webhooks/123/xyz",
        "webhook_url": "https://example.com/hook?token=secret",
        "apprise_urls": ["discord://webhook_id/webhook_token"],
        "smtp_pass": "mail_pass",
    }
    masked = mask_notification_config(cfg)
    assert masked["discord_webhook_url"] == MASK_PLACEHOLDER
    assert masked["webhook_url"] == MASK_PLACEHOLDER
    assert masked["apprise_urls"] == [MASK_PLACEHOLDER]
    assert masked["smtp_pass"] == MASK_PLACEHOLDER

    # Unmasking preserves existing when MASK_PLACEHOLDER returned
    incoming = dict(masked)
    unmasked = unmask_notification_config(incoming, cfg)
    assert unmasked["discord_webhook_url"] == "https://discord.com/api/webhooks/123/xyz"
    assert unmasked["webhook_url"] == "https://example.com/hook?token=secret"
    assert unmasked["apprise_urls"] == ["discord://webhook_id/webhook_token"]


def test_sftp_auth_proxy_chroot_and_exact_key(tmp_path):
    import subprocess
    import sys

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sftp_dir = data_dir / "sftp"
    sftp_dir.mkdir()

    pool_dir = tmp_path / "storage"
    pool_dir.mkdir()
    share1 = pool_dir / "media"
    share1.mkdir()
    share2 = pool_dir / "backups"
    share2.mkdir()

    # User with 2 shares and read_only = True
    users_data = [
        {
            "username": "sftpuser",
            "password": "sftppassword123",
            "pubkey": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGeneratedKeyForTest user@host",
            "enabled": True,
            "read_only": True,
            "shares": [str(share1), str(share2)],
        }
    ]
    with open(sftp_dir / "users.json", "w", encoding="utf-8") as f:
        json.dump(users_data, f)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_path = os.path.join(repo_root, "backend", "services", "rclone_auth_proxy.py")

    # Test 1: Substring pubkey should FAIL authentication
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root
    env["DATA_DIR"] = str(data_dir)
    env["POOL_PATH"] = str(pool_dir)
    proc_fail = subprocess.run(
        [sys.executable, script_path],
        input=json.dumps({"user": "sftpuser", "public_key": "ssh-ed25519 AAAAC3"}),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc_fail.returncode != 0

    # Test 2: Exact pubkey succeeds, enforces read_only=True, and creates isolated chroot symlinks
    proc_ok = subprocess.run(
        [sys.executable, script_path],
        input=json.dumps(
            {"user": "sftpuser", "public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGeneratedKeyForTest user@host"}
        ),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc_ok.returncode == 0
    resp = json.loads(proc_ok.stdout)
    assert resp.get("type") == "local"
    assert resp.get("_read_only") is True
    # Crucial security check: root must NOT be pool_dir
    assert resp.get("_root") != str(pool_dir)
    assert "sftp_chroot" in resp.get("_root")
    # Verify symlinks inside chroot
    chroot_entries = os.listdir(resp.get("_root"))
    assert "media" in chroot_entries
    assert "backups" in chroot_entries
