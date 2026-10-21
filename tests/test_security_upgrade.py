"""v1.9.2 first-boot hardening (backend/services/security_upgrade.py)."""

import os
import sqlite3

import pytest

from backend import config
from backend.services import security_upgrade
from backend.services.webdav_engine import get_webdav_engine
from backend.users_db import (
    create_scoped_api_token,
    create_user,
    create_user_session,
    get_user_by_username,
    init_users_db,
)


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    db = str(tmp_path / "users_upgrade.db")
    monkeypatch.setattr(config, "USERS_DB_PATH", db)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SESSIONS_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(config, "WEBDAV_CONFIG_FILE", str(tmp_path / "webdav_config.json"))
    init_users_db(db)
    return tmp_path, db


def _count(db, table):
    with sqlite3.connect(db) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_first_boot_revokes_flags_admins_and_disables_webdav(sandbox):
    tmp, db = sandbox
    create_user("boss", "Boss", "StrongPass123!", role_id="superadmin", db_path=db)
    create_user("alice", "Alice", "StrongPass123!", role_id="share_user", db_path=db)
    admin, user = get_user_by_username("boss"), get_user_by_username("alice")
    create_user_session(admin["id"], "boss", db_path=db)
    create_user_session(user["id"], "alice", db_path=db)
    create_scoped_api_token(admin["id"], "ci", ["*"], db_path=db)
    (tmp / "sessions.json").write_text("{}")
    get_webdav_engine().save_config({"enabled": True, "auth_enabled": False, "password": ""})

    assert security_upgrade.run_once() is True

    assert _count(db, "sessions") == 0
    assert _count(db, "api_tokens") == 0
    assert not (tmp / "sessions.json").exists()
    assert get_user_by_username("boss")["must_change_password"]
    assert not get_user_by_username("alice")["must_change_password"]
    cfg = get_webdav_engine().load_config()
    assert cfg["enabled"] is False and cfg["auth_enabled"] is True
    assert os.path.exists(tmp / security_upgrade.MARKER_NAME)

    # Runs only once.
    create_user_session(user["id"], "alice", db_path=db)
    assert security_upgrade.run_once() is False
    assert _count(db, "sessions") == 1


def test_webdav_with_dedicated_password_stays_on(sandbox):
    get_webdav_engine().save_config({"enabled": True, "auth_enabled": True, "password": "a-real-webdav-pass"})
    security_upgrade.run_once()
    assert get_webdav_engine().load_config()["enabled"] is True
