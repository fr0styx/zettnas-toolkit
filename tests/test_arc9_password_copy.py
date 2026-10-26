"""ARC-9: one copy of the admin password, and no unsalted SHA-256 hash left on disk."""

import hashlib
import json

import pytest

from backend import config, passwords
from backend.api.auth import ADMIN_USER_ID
from backend.users_db import (
    create_user,
    get_user_by_id,
    init_users_db,
    retire_weak_hashes,
    users_db_session,
)


def _sha(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def test_a_wrapped_sha256_hash_still_verifies_and_asks_for_an_upgrade():
    wrapped = passwords.wrap_unsalted_sha256(_sha("old-pass-1"))
    assert wrapped.startswith(passwords.WRAPPED_SHA256)
    assert _sha("old-pass-1") not in wrapped
    assert passwords.verify_password("old-pass-1", wrapped)
    assert not passwords.verify_password("wrong", wrapped)
    assert passwords.needs_rehash(wrapped) and passwords.is_legacy_hash(wrapped)
    with pytest.raises(ValueError):
        passwords.wrap_unsalted_sha256("$argon2id$not-sha")


@pytest.fixture
def own_db(tmp_path, monkeypatch):
    db = str(tmp_path / "users.db")
    monkeypatch.setattr(config, "USERS_DB_PATH", db)
    monkeypatch.setattr(config, "SECURITY_FILE", str(tmp_path / "security.json"))
    monkeypatch.setattr(config, "STORED_PASSWORD_HASH", config.STORED_PASSWORD_HASH)
    monkeypatch.setenv("ZETTNAS_ALLOW_DEFAULT_PASSWORD", "1")
    init_users_db(db)
    return db


def test_sha256_accounts_are_wrapped_and_must_choose_a_new_password(own_db):
    weak = create_user("weakling", "Weak", "Placeholder-123", role_id="share_user")
    strong = create_user("strongling", "Strong", "Placeholder-456", role_id="share_user")
    with users_db_session(own_db) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?", (_sha("pw-1"), weak["id"])
        )
        conn.execute("UPDATE users SET idp_type = 'ldap', password_hash = ? WHERE id = ?", (_sha("dir"), strong["id"]))
    assert retire_weak_hashes(own_db) == 1
    row = get_user_by_id(weak["id"])
    assert row["password_hash"].startswith(passwords.WRAPPED_SHA256)
    assert passwords.verify_password("pw-1", row["password_hash"])
    assert row["must_change_password"] in (1, True)
    assert get_user_by_id(strong["id"])["password_hash"] == _sha("dir")  # directory accounts left alone
    assert retire_weak_hashes(own_db) == 0  # nothing left to do


def test_the_security_json_copy_moves_into_the_admin_account_then_goes(own_db, tmp_path):
    from backend.api import auth as auth_api

    copy = passwords.hash_password("From-The-Old-File-7")
    with users_db_session(own_db) as conn:
        conn.execute("UPDATE users SET password_hash = '' WHERE id = ?", (ADMIN_USER_ID,))
    (tmp_path / "security.json").write_text(json.dumps({"password_hash": copy, "username": "admin", "email": ""}))
    config.STORED_PASSWORD_HASH = copy
    auth_api.retire_admin_password_copy()
    assert get_user_by_id(ADMIN_USER_ID)["password_hash"] == copy
    assert "password_hash" not in json.loads((tmp_path / "security.json").read_text())
    assert copy == config.STORED_PASSWORD_HASH  # the in-memory mirror follows the account
    auth_api.retire_admin_password_copy()  # a second start changes nothing
    assert get_user_by_id(ADMIN_USER_ID)["password_hash"] == copy


def test_a_sha256_admin_is_wrapped_at_startup_and_upgraded_at_sign_in(client):
    from backend.api import auth as auth_api

    with users_db_session(None) as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_sha("Legacy-Admin-9"), ADMIN_USER_ID))
    auth_api.retire_admin_password_copy()
    stored = get_user_by_id(ADMIN_USER_ID)["password_hash"]
    assert stored.startswith(passwords.WRAPPED_SHA256)
    r = client.post("/api/auth/login", json={"username": "admin", "password": "Legacy-Admin-9"})
    assert r.status_code == 200, r.text
    assert get_user_by_id(ADMIN_USER_ID)["password_hash"].startswith("$argon2id$")
