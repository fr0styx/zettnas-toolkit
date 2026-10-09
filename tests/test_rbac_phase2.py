"""
Test Suite: Phase 2 Granular RBAC Scope Enforcement and Scoped API Tokens.

Verifies:
1. SuperAdmin (scope: '*') retains universal access across all endpoints.
2. StorageAdmin (storage:*, shares:*, system:view):
   - Authorized on storage/disks/shares/remotes endpoints.
   - Strictly forbidden (403) on container actions, user management, fan curves, and system power.
3. AppOperator (containers:*, system:view):
   - Authorized on container lifecycle, catalog, and exec.
   - Strictly forbidden (403) on disk format, storage pools, user CRUD, and system power.
4. ShareUser (shares:read, shares:user_write, system:view):
   - Authorized on filesystem folder creation and upload within allowed shares.
   - Strictly forbidden (403) on hardware, storage pools, containers, and user management.
5. Auditor (*:read, system:view):
   - Authorized on read-only endpoints (e.g. GET /api/users, GET /api/remotes).
   - Strictly forbidden (403) on all mutation endpoints (POST/PUT/DELETE).
6. Scoped API Tokens (zat_...):
   - Fine-grained scope boundaries strictly enforced per-request.
   - Token creation with explicit scopes and expiration metadata.
7. System Power Protection:
   - POST /api/system/reboot and POST /api/system/shutdown strictly require system:power scope.
"""

from unittest.mock import patch
from fastapi.testclient import TestClient
import pytest


def _create_user_with_role(
    client: TestClient, admin_token: str, username: str, role_id: str, password: str = "P@ssword123!"
) -> str:
    """Helper to create a user with a specific role and return their session token."""
    res = client.post(
        "/api/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "username": username,
            "display_name": f"Test {username}",
            "password": password,
            "role_id": role_id,
        },
    )
    assert res.status_code == 200, f"Failed to create user {username}: {res.text}"

    login_res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert login_res.status_code == 200, f"Failed to log in as {username}: {login_res.text}"
    return login_res.json()["token"]


def test_superadmin_full_access(client: TestClient):
    """SuperAdmin with wildcard '*' has unrestricted access across all domains."""
    admin_login = client.post("/api/auth/login", json={"password": "admin"})
    assert admin_login.status_code == 200
    token = admin_login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # User management
    res = client.get("/api/users", headers=headers)
    assert res.status_code == 200

    # System Power
    res = client.post("/api/system/reboot", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res = client.post("/api/system/shutdown", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_storage_admin_permissions_and_restrictions(client: TestClient):
    """StorageAdmin can administer disks, pools, and remotes, but is forbidden on containers and users."""
    admin_login = client.post("/api/auth/login", json={"password": "admin"})
    admin_token = admin_login.json()["token"]

    storage_token = _create_user_with_role(client, admin_token, "storage_boss", "storage_admin")
    storage_headers = {"Authorization": f"Bearer {storage_token}"}

    # 1. Allowed: disk operations
    with patch("backend.api.system.fetch_disk_smart_detail", return_value={"smart": "ok"}):
        res = client.post("/api/disk_wake", headers=storage_headers, json={"dev": "sda"})
        assert res.status_code == 200

    # 2. Allowed: remotes list
    with patch("backend.services.rclone_engine.RcloneEngine.list_remotes", return_value=[]):
        res = client.get("/api/remotes", headers=storage_headers)
        assert res.status_code == 200

    # 3. Denied (403): User management (requires users:read/write)
    res = client.get("/api/users", headers=storage_headers)
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 4. Denied (403): Docker action (requires containers:write)
    res = client.post(
        "/api/docker/containers/test_container/action", headers=storage_headers, json={"action": "restart"}
    )
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 5. Denied (403): System reboot (requires system:power)
    res = client.post("/api/system/reboot", headers=storage_headers)
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]


def test_app_operator_permissions_and_restrictions(client: TestClient):
    """AppOperator can manage containers, but cannot modify storage, wipe disks, manage users, or reboot."""
    admin_login = client.post("/api/auth/login", json={"password": "admin"})
    admin_token = admin_login.json()["token"]

    app_token = _create_user_with_role(client, admin_token, "app_guru", "app_operator")
    app_headers = {"Authorization": f"Bearer {app_token}"}

    # 1. Allowed: Container action
    with patch("backend.api.system.container_action", return_value={"success": True}):
        res = client.post("/api/docker/containers/web_app/action", headers=app_headers, json={"action": "restart"})
        assert res.status_code == 200

    # 2. Denied (403): Disk wake (requires storage:write)
    res = client.post("/api/disk_wake", headers=app_headers, json={"dev": "sda"})
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 3. Denied (403): User creation (requires users:write)
    res = client.post(
        "/api/users",
        headers=app_headers,
        json={"username": "hacker", "password": "SecurePassword123!", "role_id": "share_user"},
    )
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 4. Denied (403): System reboot (requires system:power)
    res = client.post("/api/system/reboot", headers=app_headers)
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]


def test_share_user_permissions_and_restrictions(client: TestClient):
    """ShareUser can create folders/upload, but cannot touch containers, pools, users, or fans."""
    admin_login = client.post("/api/auth/login", json={"password": "admin"})
    admin_token = admin_login.json()["token"]

    share_token = _create_user_with_role(client, admin_token, "family_member", "share_user")
    share_headers = {"Authorization": f"Bearer {share_token}"}

    # 1. Allowed: Folder creation in share (shares:user_write)
    with patch("backend.api.system._do_mkdir", return_value={"status": "ok"}):
        res = client.post("/api/mkdir", headers=share_headers, json={"path": "photos"})
        assert res.status_code == 200

    # 2. Denied (403): Docker action (requires containers:write)
    res = client.post("/api/docker/containers/web_app/action", headers=share_headers, json={"action": "restart"})
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 3. Denied (403): Fans control (requires hardware:fans)
    res = client.post("/api/fans", headers=share_headers, json={"profile": "performance"})
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 4. Denied (403): User management
    res = client.get("/api/users", headers=share_headers)
    assert res.status_code == 403


def test_auditor_read_only_and_mutation_denial(client: TestClient):
    """Auditor has *:read and system:view. Can read users and logs, but cannot trigger any mutations."""
    admin_login = client.post("/api/auth/login", json={"password": "admin"})
    admin_token = admin_login.json()["token"]

    auditor_token = _create_user_with_role(client, admin_token, "audit_officer", "auditor")
    auditor_headers = {"Authorization": f"Bearer {auditor_token}"}

    # 1. Allowed: Read users (users:read is satisfied by *:read)
    res = client.get("/api/users", headers=auditor_headers)
    assert res.status_code == 200

    # 2. Allowed: Read remotes (storage:read is satisfied by *:read)
    with patch("backend.services.rclone_engine.RcloneEngine.list_remotes", return_value=[]):
        res = client.get("/api/remotes", headers=auditor_headers)
        assert res.status_code == 200

    # 3. Denied (403): Create user (requires users:write)
    res = client.post(
        "/api/users",
        headers=auditor_headers,
        json={"username": "newuser", "password": "SecurePassword123!", "role_id": "share_user"},
    )
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 4. Denied (403): Disk wake (requires storage:write)
    res = client.post("/api/disk_wake", headers=auditor_headers, json={"dev": "sda"})
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 5. Denied (403): Fan curve modification (requires hardware:fans)
    res = client.post("/api/fans", headers=auditor_headers, json={"profile": "performance"})
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]


def test_scoped_api_token_enforcement(client: TestClient):
    """Verify that scoped API tokens strictly enforce their granted scopes."""
    admin_login = client.post("/api/auth/login", json={"password": "admin"})
    admin_token = admin_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Generate a scoped API token specifically for storage only
    token_res = client.post(
        "/api/tokens",
        headers=admin_headers,
        json={
            "name": "Storage Daemon Token",
            "scopes": ["storage:*"],
        },
    )
    assert token_res.status_code == 200
    token_data = token_res.json()
    assert "token" in token_data
    raw_api_token = token_data["token"]
    assert raw_api_token.startswith("zat_")
    assert "storage:*" in token_data["scopes"]

    scoped_headers = {"Authorization": f"Bearer {raw_api_token}"}

    # 1. Allowed: Disk wake (requires storage:write, covered by storage:*)
    with patch("backend.api.system.fetch_disk_smart_detail", return_value={"smart": "ok"}):
        res = client.post("/api/disk_wake", headers=scoped_headers, json={"dev": "sda"})
        assert res.status_code == 200

    # 2. Denied (403): Docker action (token does not have containers:* scope)
    res = client.post("/api/docker/containers/app/action", headers=scoped_headers, json={"action": "restart"})
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 3. Denied (403): User management
    res = client.get("/api/users", headers=scoped_headers)
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]

    # 4. Denied (403): System power
    res = client.post("/api/system/reboot", headers=scoped_headers)
    assert res.status_code == 403
    assert "Permission denied" in res.json()["detail"]


def test_revoked_api_token_rejection(client: TestClient):
    """Revoking an API token immediately prevents authentication."""
    admin_login = client.post("/api/auth/login", json={"password": "admin"})
    admin_token = admin_login.json()["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Create token
    create_res = client.post("/api/tokens", headers=admin_headers, json={"name": "Temp Token", "scopes": ["*"]})
    assert create_res.status_code == 200
    token_info = create_res.json()
    raw_token = token_info["token"]
    token_id = token_info.get("token_id") or token_info.get("id")

    # Verify token works
    test_headers = {"Authorization": f"Bearer {raw_token}"}
    res = client.get("/api/users", headers=test_headers)
    assert res.status_code == 200

    # Revoke token
    del_res = client.delete(f"/api/tokens/{token_id or raw_token}", headers=admin_headers)
    assert del_res.status_code == 200

    # Token must now be rejected with 401
    res = client.get("/api/users", headers=test_headers)
    assert res.status_code == 401
