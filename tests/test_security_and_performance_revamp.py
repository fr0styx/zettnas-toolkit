"""
Tests verifying the complete implementation of the Enterprise Security & High-Throughput Performance Revamp.
Covers:
- Backup manifest extraction path jail (app_backup.py)
- Multi-user and appdata path isolation (fs.py)
- CSWSH and Origin verification (auth.py)
- Dual-policy SSRF Guard (ssrf_guard.py)
- SQLite recursive CTE skip-scan & composite indexes (db.py)
- Hardware subprocess TTL caching (pal_storage.py)
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.fs import check_user_path_access
from backend.auth import AuthenticatedPrincipal, validate_websocket_origin
from backend.services.app_backup import (
    FORBIDDEN_RESTORE_PREFIXES,
    SYSTEM_MOUNT_PREFIXES,
    is_safe_restore_target_path,
)
from backend.services.ssrf_guard import (
    is_loopback_or_metadata,
    validate_notification_url,
    validate_public_url,
)

# ============================================================================
# 1. Backup Manifest Path Jail
# ============================================================================


def test_backup_restore_target_jail():
    # Sensitive system paths must be strictly rejected
    assert is_safe_restore_target_path("/etc") is False
    assert is_safe_restore_target_path("/etc/shadow") is False
    assert is_safe_restore_target_path("/root") is False
    assert is_safe_restore_target_path("/root/.ssh") is False
    assert is_safe_restore_target_path("/bin") is False
    assert is_safe_restore_target_path("/usr/bin") is False
    assert is_safe_restore_target_path("/sys") is False
    assert is_safe_restore_target_path("/proc") is False
    assert is_safe_restore_target_path("/dev") is False
    assert is_safe_restore_target_path("/var/run/docker.sock") is False
    assert is_safe_restore_target_path("/") is False
    assert is_safe_restore_target_path("") is False

    # Valid application data directories should be allowed
    assert is_safe_restore_target_path("/mnt/user/appdata/plex") is True
    assert is_safe_restore_target_path("/mnt/cache/appdata/nextcloud") is True
    assert is_safe_restore_target_path("/volume1/docker/vaultwarden") is True


# ============================================================================
# 2. Multi-User and Appdata Path Isolation
# ============================================================================


def test_check_user_path_access_fail_closed():
    # None principal must raise 401
    with pytest.raises(HTTPException) as exc:
        check_user_path_access("/mnt/user/documents", None)
    assert exc.value.status_code == 401


def test_check_user_path_access_appdata_isolation():
    share_user = AuthenticatedPrincipal(
        {
            "user_id": "usr_share",
            "username": "guest",
            "role_id": "share_user",
            "scopes": ["shares:read", "shares:write"],
        }
    )

    # share_user accessing /mnt/user/appdata must raise 403
    with pytest.raises(HTTPException) as exc:
        check_user_path_access("/mnt/user/appdata", share_user)
    assert exc.value.status_code == 403
    assert "appdata requires storage:admin" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        check_user_path_access("/mnt/user/appdata/plex/config", share_user)
    assert exc.value.status_code == 403

    # share_user accessing /boot must raise 403
    with pytest.raises(HTTPException) as exc:
        check_user_path_access("/boot/config", share_user)
    assert exc.value.status_code == 403

    # Admin principal can access appdata freely
    admin = AuthenticatedPrincipal(
        {
            "user_id": "usr_admin",
            "username": "admin",
            "role_id": "admin",
            "scopes": ["storage:admin"],
        }
    )
    # Should not raise
    check_user_path_access("/mnt/user/appdata/plex", admin)


def test_check_user_path_access_home_isolation():
    user_alice = AuthenticatedPrincipal(
        {
            "user_id": "usr_alice",
            "username": "alice",
            "role_id": "share_user",
            "scopes": ["shares:read", "shares:write"],
        }
    )

    # Alice can access her own home directory
    check_user_path_access("/mnt/user/homes/alice/notes.txt", user_alice)

    # Alice cannot access Bob's home directory
    with pytest.raises(HTTPException) as exc:
        check_user_path_access("/mnt/user/homes/bob/secrets.txt", user_alice)
    assert exc.value.status_code == 403
    assert "Access denied to another user home folder" in exc.value.detail


# ============================================================================
# 3. CSWSH and Origin Header Verification
# ============================================================================


def test_validate_websocket_origin():
    # Cookie auth without Origin must be rejected (CSWSH vector)
    ws_no_origin = MagicMock()
    ws_no_origin.headers = {}
    assert validate_websocket_origin(ws_no_origin, is_cookie_auth=True) is False

    # Token/ticket auth without Origin is permitted (cannot be forged via CSWSH)
    assert validate_websocket_origin(ws_no_origin, is_cookie_auth=False) is True

    # Matching Host header is permitted
    ws_matching = MagicMock()
    ws_matching.headers = {
        "origin": "http://192.168.1.50:8082",
        "host": "192.168.1.50:8082",
    }
    assert validate_websocket_origin(ws_matching, is_cookie_auth=True) is True

    # Matching X-Forwarded-Host behind reverse proxy is permitted
    ws_proxy = MagicMock()
    ws_proxy.headers = {
        "origin": "https://nas.homelab.local",
        "host": "127.0.0.1:8082",
        "x-forwarded-host": "nas.homelab.local",
    }
    assert validate_websocket_origin(ws_proxy, is_cookie_auth=True) is True

    # Foreign cross-origin attacker domain must be strictly rejected
    ws_attacker = MagicMock()
    ws_attacker.headers = {
        "origin": "https://evil-attacker.com",
        "host": "192.168.1.50:8082",
    }
    assert validate_websocket_origin(ws_attacker, is_cookie_auth=True) is False


# ============================================================================
# 4. Context-Aware SSRF Guard
# ============================================================================


def test_ssrf_guard_public_vs_notification_policies():
    # 1. Cloud metadata must be blocked across BOTH policies
    ok_pub, _ = validate_public_url("http://169.254.169.254/latest/meta-data")
    assert ok_pub is False

    ok_notif, _ = validate_notification_url("http://169.254.169.254/api/webhook")
    assert ok_notif is False

    # 2. Loopback must be blocked across BOTH policies
    ok_pub, _ = validate_public_url("http://127.0.0.1:8082/api/stats")
    assert ok_pub is False

    ok_notif, _ = validate_notification_url("http://127.0.0.1:8082/webhook")
    assert ok_notif is False

    # 3. RFC-1918 Private LAN:
    # BLOCKED in public AI web search context to prevent internal subnet port-scanning
    ok_pub, _ = validate_public_url("http://192.168.1.100:8123/api/states")
    assert ok_pub is False

    # ALLOWED in admin notification context (Home Assistant, local ntfy server)
    ok_notif, err = validate_notification_url("http://192.168.1.100:8123/api/webhook/nas-alert")
    assert ok_notif is True

    # 4. Legitimate public HTTPS URLs must pass both
    ok_pub, _ = validate_public_url("https://api.github.com/repos/test")
    assert ok_pub is True

    ok_notif, _ = validate_notification_url("https://discord.com/api/webhooks/123/abc")
    assert ok_notif is True


# ============================================================================
# 5. SQLite Recursive CTE Skip-Scan
# ============================================================================


def test_sqlite_recursive_cte_skip_scan():
    from backend.db import query_all_smart_velocities

    # Execute query to verify skip_scan_sql executes cleanly without SQLite syntax error
    summary = query_all_smart_velocities()
    assert isinstance(summary, dict)


# ============================================================================
# 6. PAL Storage Subprocess TTL Caching
# ============================================================================


def test_pal_storage_busy_caching(monkeypatch):
    from backend.hardware.pal_storage import GenericLinuxStorageAdapter

    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")

    # Disable test mode to test real 10s TTL caching behavior
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("ZETTNAS_TEST_MODE", raising=False)

    call_count = 0

    def mock_check():
        nonlocal call_count
        call_count += 1
        return False

    adapter._check_is_storage_busy_uncached = mock_check

    # First call must invoke uncached check
    val1 = adapter.is_storage_busy()
    assert val1 is False
    assert call_count == 1

    # Second immediate call within 10s must hit cache (call_count remains 1)
    val2 = adapter.is_storage_busy()
    assert val2 is False
    assert call_count == 1
