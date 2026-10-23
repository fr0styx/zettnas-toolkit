"""SEC-02: WebDAV must never accept a default or legacy admin password."""

import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.api.webdav import WEBDAV_COOKIE_TTL, _get_webdav_portal_user, _sign_webdav_cookie, _verify_webdav_cookie
from backend.main import app
from backend.services import login_lockout
from backend.services.webdav_engine import WebdavEngine
from backend.users_db import create_user, init_users_db


@pytest.fixture(autouse=True)
def _webdav_enabled(webdav_on):
    """These tests use the portal, which answers only while WebDAV is on."""


PROXY = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", "services", "rclone_auth_proxy.py")


@pytest.fixture
def env(monkeypatch, tmp_path):
    db = str(tmp_path / "users_sec02.db")
    monkeypatch.setattr(config, "USERS_DB_PATH", db)
    init_users_db(db)  # creates admin/admin flagged "must change password"
    pool = str(tmp_path / "pool")
    os.makedirs(os.path.join(pool, "homes"), exist_ok=True)
    monkeypatch.setattr(config, "POOL_PATH", pool)
    return {"db": db, "pool": pool}


def _proxy(user, password, env):
    proc = subprocess.run(
        [sys.executable, PROXY],
        input=json.dumps({"user": user, "pass": password}),
        text=True,
        capture_output=True,
        env={**os.environ, "USERS_DB_PATH": env["db"], "POOL_PATH": env["pool"], "WEB_PASSWORD": ""},
    )
    return proc.returncode


def _force_change(db, username):
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE users SET must_change_password = 1 WHERE username = ?", (username,))


def test_proxy_rejects_default_admin_password(env):
    assert _proxy("admin", "admin", env) != 0
    login_lockout.clear("webdav:admin")


def test_proxy_rejects_account_that_must_change_password(env):
    name = f"chg{secrets.token_hex(3)}"
    create_user(name, name, "GoodPass123!", role_id="share_user", db_path=env["db"])
    assert _proxy(name, "GoodPass123!", env) == 0
    _force_change(env["db"], name)
    assert _proxy(name, "GoodPass123!", env) != 0


def test_proxy_locks_out_after_repeated_failures(env):
    name = f"lock{secrets.token_hex(3)}"
    create_user(name, name, "GoodPass123!", role_id="share_user", db_path=env["db"])
    for _ in range(login_lockout.FREE_ATTEMPTS):
        assert _proxy(name, "wrong-password", env) != 0
    # Locked now: even the right password is refused.
    assert _proxy(name, "GoodPass123!", env) != 0
    login_lockout.clear(f"webdav:{name}")
    assert _proxy(name, "GoodPass123!", env) == 0


def test_portal_rejects_default_admin_and_must_change(env):
    client = TestClient(app)
    res = client.post("/webdav/auth/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert res.status_code != 303
    assert "webdav_session" not in res.cookies
    login_lockout.clear("webdav:admin")

    name = f"pch{secrets.token_hex(3)}"
    create_user(name, name, "GoodPass123!", role_id="share_user", db_path=env["db"])
    _force_change(env["db"], name)
    res = client.post("/webdav/auth/login", data={"username": name, "password": "GoodPass123!"}, follow_redirects=False)
    assert res.status_code == 403


def test_portal_cookie_expires_and_dies_with_the_user(env):
    name = f"cok{secrets.token_hex(3)}"
    create_user(name, name, "GoodPass123!", role_id="share_user", db_path=env["db"])
    client = TestClient(app)
    res = client.post("/webdav/auth/login", data={"username": name, "password": "GoodPass123!"}, follow_redirects=False)
    assert res.status_code == 303
    cookie = res.cookies.get("webdav_session")
    assert cookie.count(":") == 3

    req = MagicMock()
    req.cookies = {"webdav_session": cookie}
    req.state.session = None
    assert _get_webdav_portal_user(req, {"auth_enabled": True})["username"] == name

    # Old non-expiring format and expired cookies are refused.
    assert _verify_webdav_cookie(cookie.rsplit(":", 2)[0] + ":" + cookie.rsplit(":", 1)[1]) is None
    old = _sign_webdav_cookie(name, "user", issued_at=int(time.time()) - WEBDAV_COOKIE_TTL - 10)
    assert _verify_webdav_cookie(old) is None

    # Disabled user: the still-valid cookie gives nothing (no admin-name fallback).
    with sqlite3.connect(env["db"]) as conn:
        conn.execute("UPDATE users SET status = 'disabled' WHERE username = ?", (name,))
    from backend.users_db import _SESSION_CACHE, _SESSION_CACHE_LOCK

    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()
    assert _get_webdav_portal_user(req, {"auth_enabled": True}) is None

    admin_cookie = _sign_webdav_cookie("admin-not-in-db", "admin")
    req.cookies = {"webdav_session": admin_cookie}
    assert _get_webdav_portal_user(req, {"auth_enabled": True}) is None


def test_webdav_is_off_by_default_and_fallback_mode_needs_a_real_password():
    engine = WebdavEngine.__new__(WebdavEngine)
    assert engine.get_default_config()["enabled"] is False
