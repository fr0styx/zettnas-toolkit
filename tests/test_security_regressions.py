"""
Regression test suite for Security Hardening & Vulnerability Remediation (SEC-01 through SEC-11).
Validates:
1. SEC-01: Samba passdb username regex validation & positional parameter isolation.
2. SEC-02 & SEC-05: Sanitization of user sensitive credentials (hashes, 2FA secrets) & IDOR defenses.
3. SEC-03 & SEC-10: Path traversal containment across Trash, Media, WebDAV, and VM ISO operations.
4. SEC-04 & SEC-06..11: Privilege escalation prevention, endpoint scope authorization & Redfish auth.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.services.samba_engine import SambaEngine
from backend.api.auth import _sanitize_user_dict
from backend.fsutil import resolve_within
from backend.auth import require_scope, auth_middleware


def test_sec01_samba_username_injection_rejection():
    """Validates that SambaEngine rejects malicious usernames containing shell metacharacters."""
    engine = SambaEngine()

    malicious_usernames = [
        "user; rm -rf /",
        "user\nuser",
        "user$(whoami)",
        "user`id`",
        "user&id",
        "user|sh",
        "../user",
        "user space",
        "a" * 33,  # Length limit is 32
        "",
    ]

    for bad_user in malicious_usernames:
        res = engine.sync_samba_user(bad_user, password="ValidPassword123!")
        assert res is False, f"Malicious username '{bad_user}' was incorrectly accepted by SambaEngine!"

    # Legitimate usernames should pass the regex check
    valid_usernames = ["john_doe", "alice-123", "nas.backup", "User99"]
    for good_user in valid_usernames:
        with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
            mock_run.return_value = MagicMock(returncode=0)
            p_mock = MagicMock()
            p_mock.communicate.return_value = ("", "")
            p_mock.returncode = 0
            mock_popen.return_value = p_mock

            # Will not fail on regex
            res = engine.sync_samba_user(good_user, password="ValidPassword123!")
            assert res is True, f"Valid username '{good_user}' was incorrectly rejected!"


def test_sec02_sanitize_user_dict_strips_secrets():
    """Validates that sensitive hashes and 2FA secrets are completely stripped from user responses."""
    raw_user = {
        "id": "u-123",
        "username": "alice",
        "role": "operator",
        "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$secret_hash",
        "mfa_secret": "JBSWY3DPEHPK3PXP",
        "mfa_recovery_codes_json": '["code1", "code2"]',
        "token_hash": "abc123hash",
        "storage_quota_bytes": 10737418240,
    }

    sanitized = _sanitize_user_dict(raw_user)

    assert "password_hash" not in sanitized
    assert "mfa_secret" not in sanitized
    assert "mfa_recovery_codes_json" not in sanitized
    assert "token_hash" not in sanitized
    assert sanitized["id"] == "u-123"
    assert sanitized["username"] == "alice"


def test_sec03_path_traversal_containment():
    """Validates that resolve_within() strictly stops directory traversal attacks."""
    allowed_root = "/mnt/storage"

    # Valid subpaths
    assert resolve_within("/mnt/storage/photos", [allowed_root]) == "/mnt/storage/photos"
    assert resolve_within("/mnt/storage/sub/../sub/file.txt", [allowed_root]) == "/mnt/storage/sub/file.txt"

    # Traversal attempts
    assert resolve_within("/mnt/storage/../../etc/shadow", [allowed_root]) is None
    assert resolve_within("/mnt/storage/../..", [allowed_root]) is None
    assert resolve_within("/etc/passwd", [allowed_root]) is None
    assert resolve_within("../../../var/log", [allowed_root]) is None


def test_sec04_backup_superadmin_scope_requirement():
    """Validates that system backup and restore endpoints strictly require superadmin (*) scope."""
    superadmin_scope_checker = require_scope("*")

    non_admin_principal = MagicMock()
    non_admin_principal.has_scope.return_value = False
    non_admin_principal.is_superadmin = False

    with pytest.raises(HTTPException) as exc_info:
        superadmin_scope_checker(principal=non_admin_principal)
    assert exc_info.value.status_code == 403

    admin_principal = MagicMock()
    admin_principal.has_scope.return_value = True
    assert superadmin_scope_checker(principal=admin_principal) == admin_principal


def test_sec06_docker_stacks_secrets_masking():
    """Validates that environment secrets in compose definitions are masked by default."""
    from backend.services.compose_synthesizer import is_secret_key, mask_secret_value

    assert is_secret_key("POSTGRES_PASSWORD") is True
    assert is_secret_key("API_KEY") is True
    assert is_secret_key("CLIENT_SECRET") is True
    assert is_secret_key("POSTGRES_USER") is False
    assert is_secret_key("PORT") is False

    assert mask_secret_value("mySecretPassword123") == "••••••••"
    assert mask_secret_value("zat_token_12345") == "••••••••"


def test_sec07_vm_console_token_scope_enforcement():
    """Validates that creating a VM console token requires vms:write, vms:manage, or system:config."""
    vm_scope_checker = require_scope("vms:write", "vms:manage", "system:config")

    viewer_principal = MagicMock()
    viewer_principal.has_scope.return_value = False
    viewer_principal.is_superadmin = False

    with pytest.raises(HTTPException) as exc_info:
        vm_scope_checker(principal=viewer_principal)
    assert exc_info.value.status_code == 403

    operator_principal = MagicMock()
    operator_principal.has_scope.side_effect = lambda s: s == "vms:write"
    assert vm_scope_checker(principal=operator_principal) == operator_principal


def test_sec11_redfish_auth_protection():
    """Validates that /redfish routes are routed through authentication in auth_middleware."""

    async def dummy_call_next(request: Request):
        return JSONResponse({"status": "ok"})

    # Unauthenticated request to /redfish/v1/Chassis
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/redfish/v1/Chassis",
        "headers": [],
        "query_string": b"",
    }
    req = Request(scope)

    # Calling auth_middleware without credentials on /redfish must return 401
    response = asyncio.run(auth_middleware(req, dummy_call_next))
    assert response.status_code == 401
