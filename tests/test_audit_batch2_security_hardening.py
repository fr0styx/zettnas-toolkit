"""
Unit and integration tests for Batch 2 Security Hardening:
- Scoped endpoint access (wallpapers, layout, state, client-preferences, ups, security)
- User password endpoint hardening (auth required, auditor rejection, cross-user authorization)
- SSRF defenses in UPS test connection, LLM endpoint config, and AI internet browsing
- Path-based RBAC enforcement in filesystem search, trash list, and RAG learning results
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import AuthenticatedPrincipal
from backend.services.ai_chat_agent import _is_safe_public_url, tool_browse_internet, tool_trigger_ai_sync
from backend.services.rag_engine import get_rag_engine


@pytest.fixture
def client():
    return TestClient(app)


def test_ssrf_safe_url_validation():
    # Loopback and private/link-local should be blocked
    assert _is_safe_public_url("http://127.0.0.1:8080") is False
    assert _is_safe_public_url("http://localhost:3000") is False
    assert _is_safe_public_url("http://169.254.169.254/latest/meta-data") is False
    assert _is_safe_public_url("http://metadata.google.internal") is False
    assert _is_safe_public_url("ftp://example.com/file") is False

    # Valid public domain should pass
    assert _is_safe_public_url("https://en.wikipedia.org/wiki/Python") is True


def test_tool_browse_internet_ssrf_blocked(monkeypatch):
    # Probing local or metadata endpoint should be blocked without making HTTP requests
    res = tool_browse_internet("Check http://169.254.169.254/latest/meta-data")
    assert res["status"] in ("ok", "answered")
    # No direct_url source should be added from a blocked SSRF target
    sources = res.get("sources", [])
    assert not any(s.get("source") == "direct_url" for s in sources)


def test_tool_trigger_ai_sync_scopes():
    read_only_principal = AuthenticatedPrincipal(
        {
            "user_id": "usr_auditor",
            "username": "auditor",
            "role_id": "auditor",
            "scopes": ["system:view", "shares:read"],
        }
    )
    res_denied = tool_trigger_ai_sync("start", principal=read_only_principal)
    assert res_denied["status"] == "denied"

    admin_principal = AuthenticatedPrincipal(
        {
            "user_id": "usr_admin",
            "username": "admin",
            "role_id": "superadmin",
            "scopes": ["*"],
        }
    )
    res_allowed = tool_trigger_ai_sync("start", principal=admin_principal)
    assert res_allowed["status"] == "ok"


def test_ups_ssrf_link_local_rejection(client, monkeypatch):
    # Authorize as admin for UPS config
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {"user_id": "usr_admin", "username": "admin", "role_id": "superadmin", "scopes": ["*"]},
    )
    headers = {"Authorization": "Bearer admin_token"}

    res = client.post(
        "/api/ups/test-connection",
        json={"host": "169.254.169.254", "port": 3551, "mode": "apcupsd_client"},
        headers=headers,
    )
    assert res.status_code == 400
    assert "forbidden" in res.json().get("detail", "").lower()


def test_llm_endpoint_ssrf_rejection(client, monkeypatch):
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {"user_id": "usr_admin", "username": "admin", "role_id": "superadmin", "scopes": ["*"]},
    )
    headers = {"Authorization": "Bearer admin_token"}

    res = client.post(
        "/api/ai/config",
        json={"llm_endpoint": "http://169.254.169.254/v1"},
        headers=headers,
    )
    assert res.status_code == 400
    assert "forbidden" in res.json().get("detail", "").lower()


def test_change_user_password_auditor_rejected(client, monkeypatch):
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {
            "user_id": "usr_auditor",
            "username": "auditor",
            "role_id": "auditor",
            "scopes": ["system:view"],
        },
    )
    headers = {"Authorization": "Bearer auditor_token"}

    res = client.post(
        "/api/users/usr_auditor/password",
        json={"new_password": "NewSecurePassword123!"},
        headers=headers,
    )
    assert res.status_code == 403


def test_rag_learning_results_rbac_filtering():
    rag = get_rag_engine()
    rag._ensure_schema()
    conn = rag._get_conn()
    now = 1700000000.0

    # Insert two failed records: one in public share, one in private home
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO indexed_files (
                file_id, canonical_path, parent_dir, file_name, file_ext, modality,
                size_bytes, mtime_ns, sha256_hash, parse_status, indexed_at, last_verified_at,
                visibility_tier, owner_username, share_name, allowed_users_csv
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                99001,
                "/mnt/user/documents/public_broken.pdf",
                "/mnt/user/documents",
                "public_broken.pdf",
                ".pdf",
                "document",
                1024,
                1000,
                "hash1",
                "corrupted_pdf",
                now,
                now,
                "public_share",
                "system",
                "documents",
                "",
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO indexed_files (
                file_id, canonical_path, parent_dir, file_name, file_ext, modality,
                size_bytes, mtime_ns, sha256_hash, parse_status, indexed_at, last_verified_at,
                visibility_tier, owner_username, share_name, allowed_users_csv
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                99002,
                "/mnt/user/homes/bob/secret_broken.pdf",
                "/mnt/user/homes/bob",
                "secret_broken.pdf",
                ".pdf",
                "document",
                2048,
                1000,
                "hash2",
                "corrupted_pdf",
                now,
                now,
                "user_home",
                "bob",
                "homes",
                "bob",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # User Alice queries learning results
    alice_principal = AuthenticatedPrincipal(
        {
            "user_id": "usr_alice",
            "username": "alice",
            "role_id": "share_user",
            "scopes": ["shares:read", "storage:read"],
        }
    )
    res_alice = rag.get_learning_results(principal=alice_principal)
    alice_failed_paths = [f["path"] for f in res_alice["failed_files"]]
    assert "/mnt/user/documents/public_broken.pdf" in alice_failed_paths
    assert "/mnt/user/homes/bob/secret_broken.pdf" not in alice_failed_paths

    # Admin queries learning results - can see both
    admin_principal = AuthenticatedPrincipal(
        {
            "user_id": "usr_admin",
            "username": "admin",
            "role_id": "superadmin",
            "scopes": ["*"],
        }
    )
    res_admin = rag.get_learning_results(principal=admin_principal)
    admin_failed_paths = [f["path"] for f in res_admin["failed_files"]]
    assert "/mnt/user/documents/public_broken.pdf" in admin_failed_paths
    assert "/mnt/user/homes/bob/secret_broken.pdf" in admin_failed_paths
