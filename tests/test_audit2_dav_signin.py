"""WebDAV/SFTP sign-in: two-factor accounts and stored hashes (audit pass 2)."""

import json
import os
import subprocess
import sys

import pytest

from backend import config
from backend.passwords import hash_password
from backend.totp import generate_totp_secret
from backend.users_db import create_user, enable_user_mfa, init_users_db

PROXY = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend", "services", "rclone_auth_proxy.py")


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / "u.db")
    monkeypatch.setattr(config, "USERS_DB_PATH", db)
    init_users_db(db)
    (tmp_path / "data" / "sftp").mkdir(parents=True)
    return {
        "db": db,
        "data": tmp_path / "data",
        "env": {"USERS_DB_PATH": db, "DATA_DIR": str(tmp_path / "data"), "POOL_PATH": str(tmp_path / "pool")},
    }


def _signin(env, user, pw):
    p = subprocess.run(
        [sys.executable, PROXY],
        input=json.dumps({"user": user, "pass": pw}),
        text=True,
        capture_output=True,
        env={**os.environ, **env["env"]},
    )
    return p.returncode == 0


def test_two_factor_account_needs_a_dedicated_account(env):
    plain = create_user("davplain", "P", "GoodPass123!", role_id="share_user", db_path=env["db"])
    two = create_user("davtwo", "T", "GoodPass123!", role_id="share_user", db_path=env["db"])
    enable_user_mfa(two["id"], generate_totp_secret(), [], db_path=env["db"])
    assert plain and _signin(env, "davplain", "GoodPass123!")
    assert not _signin(env, "davtwo", "GoodPass123!")


def test_stored_hash_is_not_a_password(env):
    stored = hash_password("SftpPass-123")
    (env["data"] / "sftp" / "users.json").write_text(
        json.dumps(
            [
                {"username": "sftpu", "password": stored, "enabled": True},
                {"username": "oldu", "password": "Legacy-Plain-1", "enabled": True},
            ]
        )
    )
    assert _signin(env, "sftpu", "SftpPass-123")
    assert not _signin(env, "sftpu", stored)
    assert _signin(env, "oldu", "Legacy-Plain-1")  # entries saved before hashing still work
