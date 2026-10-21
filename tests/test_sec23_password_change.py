"""SEC-23 / SEC-13: password-change enforcement and re-authentication."""

import secrets

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.main import app
from backend.users_db import create_user, get_user_by_username, init_users_db

PWD = "GoodPass123!"


@pytest.fixture
def client(monkeypatch, tmp_path):
    db = str(tmp_path / "users_sec23.db")
    monkeypatch.setattr(config, "USERS_DB_PATH", db)
    monkeypatch.setattr(config, "ENFORCE_PASSWORD_CHANGE", True)
    init_users_db(db)
    return TestClient(app), db


def _login(c, username, password):
    res = c.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _user(db, role="share_user", must_change=False):
    import sqlite3

    name = f"u{secrets.token_hex(3)}"
    create_user(name, name, PWD, role_id=role, db_path=db)
    if must_change:
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE users SET must_change_password = 1 WHERE username = ?", (name,))
    return name, get_user_by_username(name)["id"]


def test_must_change_session_is_limited_to_password_change(client):
    c, db = client
    name, uid = _user(db, must_change=True)
    h = _login(c, name, PWD)

    assert c.get("/api/auth/me", headers=h).status_code == 200
    blocked = c.get("/api/auth/sessions", headers=h)
    assert blocked.status_code == 403
    assert blocked.json().get("error") == "password_change_required"
    # Someone else's password route is not on the allow-list either.
    assert c.post("/api/users/other-id/password", json={"new_password": "Another123!"}, headers=h).status_code == 403

    res = c.post(
        f"/api/users/{uid}/password",
        json={"current_password": PWD, "new_password": "NewGoodPass456!"},
        headers=h,
    )
    assert res.status_code == 200, res.text
    # Same session, now unrestricted.
    assert c.get("/api/auth/sessions", headers=h).status_code == 200


def test_default_admin_is_gated(client):
    c, _db = client
    h = _login(c, "admin", "admin")
    res = c.get("/api/users", headers=h)
    assert res.status_code == 403
    assert res.json().get("error") == "password_change_required"


def test_self_change_requires_current_password(client):
    c, db = client
    name, uid = _user(db)
    h = _login(c, name, PWD)
    for body in ({"new_password": "NewGoodPass456!"}, {"new_password": "NewGoodPass456!", "current_password": "nope"}):
        res = c.post(f"/api/users/{uid}/password", json=body, headers=h)
        assert res.status_code == 403
    assert c.post("/api/auth/login", json={"username": name, "password": PWD}).status_code == 200


def test_change_revokes_other_sessions_but_keeps_the_callers(client):
    c, db = client
    name, uid = _user(db)
    h1 = _login(c, name, PWD)
    h2 = _login(c, name, PWD)
    res = c.post(
        f"/api/users/{uid}/password",
        json={"current_password": PWD, "new_password": "NewGoodPass456!"},
        headers=h1,
    )
    assert res.status_code == 200, res.text
    assert c.get("/api/auth/me", headers=h1).status_code == 200
    assert c.get("/api/auth/me", headers=h2).status_code == 401


def test_admin_reset_signs_target_out_and_users_cannot_reset_others(client, monkeypatch):
    c, db = client
    # The suite runs with the master password "admin", which gates every superadmin.
    monkeypatch.setattr(config, "is_using_default_password", lambda: False)
    admin, _ = _user(db, role="superadmin")
    victim, vid = _user(db)
    other, _ = _user(db)
    hv = _login(c, victim, PWD)
    ho = _login(c, other, PWD)

    assert c.post(f"/api/users/{vid}/password", json={"new_password": "Hijack12345!"}, headers=ho).status_code == 403

    ha = _login(c, admin, PWD)
    assert c.post(f"/api/users/{vid}/password", json={"new_password": "Reset12345!"}, headers=ha).status_code == 200
    assert c.get("/api/auth/me", headers=hv).status_code == 401
