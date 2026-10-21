"""TOTP seeds are encrypted at rest (SEC-14 follow-up)."""

import sqlite3

import pytest

from backend import config, secret_box
from backend.users_db import create_user, enable_user_mfa, get_user_by_username, get_user_mfa, init_users_db

SEED = "JBSWY3DPEHPK3PXP"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "users_totp.db")
    monkeypatch.setattr(config, "USERS_DB_PATH", path)
    init_users_db(path)
    create_user("mfauser", "M", "GoodPass123!", db_path=path)
    return path, get_user_by_username("mfauser", db_path=path)["id"]


def _stored(path, uid):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT mfa_secret FROM users WHERE id = ?", (uid,)).fetchone()[0]


def test_new_seeds_are_sealed_and_read_back(db):
    path, uid = db
    enable_user_mfa(uid, SEED, [], db_path=path)
    stored = _stored(path, uid)
    assert stored.startswith("enc1:") and SEED not in stored
    assert get_user_mfa(uid, db_path=path)["mfa_secret"] == SEED


def test_legacy_plaintext_is_migrated(db):
    path, uid = db
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE users SET mfa_enabled = 1, mfa_secret = ? WHERE id = ?", (SEED, uid))
    assert get_user_mfa(uid, db_path=path)["mfa_secret"] == SEED  # readable before migration
    assert secret_box.migrate_plaintext_mfa_secrets(path) == 1
    assert _stored(path, uid).startswith("enc1:")
    assert get_user_mfa(uid, db_path=path)["mfa_secret"] == SEED
    assert secret_box.migrate_plaintext_mfa_secrets(path) == 0


def test_wrong_key_does_not_crash(db, monkeypatch):
    path, uid = db
    enable_user_mfa(uid, SEED, [], db_path=path)
    monkeypatch.setattr(config, "SECRET_KEY", "a-different-key")
    assert get_user_mfa(uid, db_path=path)["mfa_secret"] == ""
    with pytest.raises(secret_box.SecretBoxError):
        secret_box.unseal(_stored(path, uid))
