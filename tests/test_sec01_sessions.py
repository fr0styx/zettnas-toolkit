"""SEC-01: a revoked, disabled or deleted user's session must never turn into superadmin."""

import json
import os
import secrets
import time

import pytest
from fastapi.testclient import TestClient

from backend import auth, config


def _admin_headers(client):
    res = client.post("/api/auth/login", json={"password": "admin"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _make_user(client, admin_h, username, role="share_user", password="P@ssword123!"):
    res = client.post(
        "/api/users",
        headers=admin_h,
        json={"username": username, "display_name": username, "password": password, "role_id": role},
    )
    assert res.status_code == 200, res.text
    users = client.get("/api/users", headers=admin_h).json()
    users = users.get("users", users) if isinstance(users, dict) else users
    uid = next(u["id"] for u in users if u["username"] == username)
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    return uid, {"Authorization": f"Bearer {login.json()['token']}"}


def _is_rejected(client, headers):
    # /api/users needs users:read, which only admins have; the exploit made this return 200.
    return client.get("/api/users", headers=headers).status_code in (401, 403)


def test_disabled_user_session_does_not_become_admin(client: TestClient):
    admin_h = _admin_headers(client)
    uid, user_h = _make_user(client, admin_h, f"sec01-dis-{secrets.token_hex(3)}")
    assert _is_rejected(client, user_h)  # share user cannot list users

    res = client.put(f"/api/users/{uid}", headers=admin_h, json={"status": "disabled"})
    assert res.status_code == 200, res.text

    assert client.get("/api/users", headers=user_h).status_code in (401, 403)
    assert client.get("/api/auth/me", headers=user_h).status_code == 401


def test_deleted_user_session_is_dead(client: TestClient):
    admin_h = _admin_headers(client)
    uid, user_h = _make_user(client, admin_h, f"sec01-del-{secrets.token_hex(3)}")
    assert client.delete(f"/api/users/{uid}", headers=admin_h).status_code == 200
    assert client.get("/api/auth/me", headers=user_h).status_code == 401
    assert _is_rejected(client, user_h)


def test_revoked_session_is_dead(client: TestClient):
    admin_h = _admin_headers(client)
    _uid, user_h = _make_user(client, admin_h, f"sec01-rev-{secrets.token_hex(3)}")
    token = user_h["Authorization"].split(" ", 1)[1]
    auth.revoke_session(token)
    assert auth.get_current_session(token) is None
    assert auth.validate_session(token) is False
    assert client.get("/api/auth/me", headers=user_h).status_code == 401


def test_legacy_sessions_file_is_ignored_and_purged():
    token = secrets.token_urlsafe(32)
    path = config.SESSIONS_FILE
    with open(path, "w") as f:
        json.dump({token: {"user": "admin", "created": time.time(), "expires": time.time() + 3600}}, f)
    with open(path + ".bak", "w") as f:
        f.write("{}")

    assert auth.get_current_session(token) is None
    assert auth.validate_session(token) is False

    auth.purge_legacy_session_files()
    assert not os.path.exists(path)
    assert not os.path.exists(path + ".bak")


def test_create_session_refuses_unknown_user():
    with pytest.raises(ValueError):
        auth.create_session(f"nobody-{secrets.token_hex(4)}")
