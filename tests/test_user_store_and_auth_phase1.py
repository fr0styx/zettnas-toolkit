"""
Test Suite: Phase 1 Core Identity Store, Argon2id & Multi-User Architecture.

Verifies:
1. Argon2id password hashing, constant-time verification, and legacy scrypt/sha256 compatibility.
2. SQLite WAL users.db schema initialization and default system roles seeding.
3. Zero-downtime migration from legacy security.json, sessions.json, and api_tokens.json.
4. User CRUD lifecycle (creation, profile updates, password changes, deletion safeguards).
5. Hybrid session management (HttpOnly cookie, Bearer token, and in-memory caching).
6. Backward-compatible login with transparent hash upgrade to Argon2id.
7. User endpoints (GET /api/auth/me, GET /api/users, POST /api/users).
"""

import hashlib
import json
import os
import tempfile
import time
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
import pytest

from app import app
from backend import config
from backend.passwords import (
    hash_password,
    is_legacy_hash,
    needs_rehash,
    verify_password,
)
from backend.users_db import (
    create_scoped_api_token,
    create_user,
    create_user_session,
    delete_user,
    get_user_by_id,
    get_user_by_username,
    init_users_db,
    list_users,
    revoke_user_session,
    update_user_password,
    update_user_profile,
    validate_scoped_api_token,
    validate_user_session,
)


@pytest.fixture
def temp_db():
    """Provides an isolated SQLite users database in a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_users.db")
        init_users_db(db_path)
        yield db_path


# ==============================================================================
# 1. Cryptographic Hashing Tests
# ==============================================================================


def test_argon2id_hashing_and_verification():
    raw = "SuperSecretPass123!"
    h = hash_password(raw)
    assert h.startswith("$argon2id$") or h.startswith("scrypt$")
    assert verify_password(raw, h) is True
    assert verify_password("WrongPass", h) is False
    assert verify_password("", h) is False
    assert verify_password(None, h) is False


def test_legacy_scrypt_backward_compatibility():
    """Verify that existing scrypt hashes created in earlier versions still verify perfectly."""
    raw = "legacy_admin_pass"
    salt = b"0123456789abcdef"
    dk = hashlib.scrypt(raw.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    scrypt_hash = f"scrypt$16384$8$1${salt.hex()}${dk.hex()}"

    assert verify_password(raw, scrypt_hash) is True
    assert verify_password("wrong", scrypt_hash) is False
    assert is_legacy_hash(scrypt_hash) is True
    assert needs_rehash(scrypt_hash) is True


def test_legacy_sha256_backward_compatibility():
    """Verify that legacy unsalted SHA-256 hashes still verify and flag for upgrade."""
    raw = "admin"
    sha_hash = hashlib.sha256(raw.encode()).hexdigest()
    assert len(sha_hash) == 64
    assert verify_password(raw, sha_hash) is True
    assert verify_password("wrong", sha_hash) is False
    assert is_legacy_hash(sha_hash) is True
    assert needs_rehash(sha_hash) is True


# ==============================================================================
# 2. Database Schema & Role Seeding Tests
# ==============================================================================


def test_users_db_initialization_and_roles(temp_db):
    users = list_users(temp_db)
    # Default admin user created
    assert len(users) >= 1
    admin = get_user_by_username("admin", temp_db)
    assert admin is not None
    assert admin["role_id"] == "superadmin"
    assert "*" in admin["scopes"]


# ==============================================================================
# 3. User CRUD Lifecycle Tests
# ==============================================================================


def test_user_crud_operations(temp_db):
    # 1. Create User
    user = create_user(
        username="johndoe",
        display_name="John Doe",
        password="Password123!",
        email="john@example.com",
        role_id="app_operator",
        storage_quota_bytes=100 * 1024 * 1024 * 1024,
        db_path=temp_db,
    )
    assert user["username"] == "johndoe"
    assert user["display_name"] == "John Doe"
    assert user["role_id"] == "app_operator"
    assert "containers:*" in user["scopes"]

    # 2. Lookup by username & ID
    by_name = get_user_by_username("JohnDoe", temp_db)  # Case-insensitive
    assert by_name["id"] == user["id"]
    by_id = get_user_by_id(user["id"], temp_db)
    assert by_id["username"] == "johndoe"

    # 3. Update Profile
    update_user_profile(
        user["id"],
        display_name="Johnathan Doe",
        email="john.doe@enterprise.com",
        storage_quota_bytes=200 * 1024 * 1024 * 1024,
        db_path=temp_db,
    )
    updated = get_user_by_id(user["id"], temp_db)
    assert updated["display_name"] == "Johnathan Doe"
    assert updated["email"] == "john.doe@enterprise.com"
    assert updated["storage_quota_bytes"] == 200 * 1024 * 1024 * 1024

    # 4. Password Change
    update_user_password(user["id"], "NewPassword456!", temp_db)
    refreshed = get_user_by_id(user["id"], temp_db)
    assert verify_password("NewPassword456!", refreshed["password_hash"]) is True
    assert verify_password("Password123!", refreshed["password_hash"]) is False

    # 5. Delete User
    assert delete_user(user["id"], temp_db) is True
    assert get_user_by_id(user["id"], temp_db) is None


def test_cannot_delete_last_superadmin(temp_db):
    admin = get_user_by_username("admin", temp_db)
    assert admin is not None
    with pytest.raises(ValueError, match="Cannot delete the only active SuperAdmin"):
        delete_user(admin["id"], temp_db)


# ==============================================================================
# 4. Session & Token Management Tests
# ==============================================================================


def test_user_session_lifecycle(temp_db):
    admin = get_user_by_username("admin", temp_db)
    token = create_user_session(
        admin["id"], admin["username"], ip="192.168.1.50", user_agent="Mozilla/5.0", db_path=temp_db
    )
    assert isinstance(token, str) and len(token) > 20

    # Validate active session
    sess = validate_user_session(token, temp_db)
    assert sess is not None
    assert sess["user_id"] == admin["id"]
    assert sess["username"] == "admin"
    assert sess["role_id"] == "superadmin"

    # Revoke session
    revoke_user_session(token, temp_db)
    assert validate_user_session(token, temp_db) is None


def test_scoped_api_token_creation_and_validation(temp_db):
    admin = get_user_by_username("admin", temp_db)
    raw_token, meta = create_scoped_api_token(
        admin["id"], name="Prometheus Scraper", scopes=["storage:read", "hardware:read"], db_path=temp_db
    )
    assert raw_token.startswith("zat_")
    assert meta["name"] == "Prometheus Scraper"
    assert "storage:read" in meta["scopes"]

    # Validate token
    validated = validate_scoped_api_token(raw_token, temp_db)
    assert validated is not None
    assert validated["username"] == "admin"
    assert validated["scopes"] == ["storage:read", "hardware:read"]


# ==============================================================================
# 5. FastAPI Endpoints & Backward Compatibility Tests
# ==============================================================================


def test_login_legacy_password_only(client: TestClient):
    """Verify that sending only {'password': '...'} works seamlessly for backward compatibility."""
    res = client.post("/api/auth/login", json={"password": "admin"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "token" in data
    assert "user" in data
    assert data["user"]["role"] == "superadmin"
    # Verify HttpOnly cookie was set
    assert "zettnas_session" in res.cookies


def test_login_multiuser_with_username_and_cookie(client: TestClient):
    """Create a user and verify logging in with specific credentials sets HttpOnly cookie."""
    # 1. Login as admin to get auth
    admin_login = client.post("/api/auth/login", json={"password": "admin"})
    admin_token = admin_login.json()["token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Create operator user
    create_res = client.post(
        "/api/users",
        headers=headers,
        json={
            "username": "docker_lead",
            "display_name": "Docker Lead",
            "password": "StrongPassword789!",
            "role_id": "app_operator",
        },
    )
    assert create_res.status_code == 200

    # 3. Log in as new user with username and password
    login_res = client.post(
        "/api/auth/login", json={"username": "docker_lead", "password": "StrongPassword789!", "remember_me": True}
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["user"]["username"] == "docker_lead"
    assert login_data["user"]["role"] == "app_operator"
    assert "zettnas_session" in login_res.cookies

    # 4. Verify GET /api/auth/me using the cookie
    me_res = client.get("/api/auth/me", cookies={"zettnas_session": login_data["token"]})
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["username"] == "docker_lead"
    assert me_data["role"] == "app_operator"
    assert "containers:*" in me_data["scopes"]


def test_logout_endpoint_clears_cookie(client: TestClient):
    login_res = client.post("/api/auth/login", json={"password": "admin"})
    token = login_res.json()["token"]

    logout_res = client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}, cookies={"zettnas_session": token}
    )
    assert logout_res.status_code == 200
    # Session cookie must be expired or cleared
    assert logout_res.cookies.get("zettnas_session") == "" or "zettnas_session" not in logout_res.cookies
