"""SET-01: deleting one SFTP user leaves the passwords of the others alone.

A delete used to save the list as it is shown, with every password replaced by its mask. The mask
then signed in as any of the other users, over SFTP and WebDAV.
"""

import json

from backend.passwords import verify_password
from backend.services import rclone_auth_proxy, sftp_engine
from backend.users_db import create_user


def _engine(tmp_path, monkeypatch):
    monkeypatch.setattr(sftp_engine, "SFTP_DIR", str(tmp_path))
    monkeypatch.setattr(sftp_engine, "SFTP_USERS_FILE", str(tmp_path / "users.json"))
    (tmp_path / "users.json").write_text("[]")
    return sftp_engine.SFTPEngine.__new__(sftp_engine.SFTPEngine)


def _stored(tmp_path):
    return {u["username"]: u.get("password") for u in json.loads((tmp_path / "users.json").read_text())}


def test_a_delete_keeps_the_other_passwords(tmp_path, monkeypatch):
    engine = _engine(tmp_path, monkeypatch)
    for name in ("anna", "ben", "mia"):
        engine.add_user({"username": name, "password": f"{name}-Secret-1"})
    assert engine.delete_user("ben") is True
    stored = _stored(tmp_path)
    assert set(stored) == {"anna", "mia"}
    for name in ("anna", "mia"):
        assert stored[name] != sftp_engine.PASSWORD_MASK
        assert verify_password(f"{name}-Secret-1", stored[name])
    assert engine.delete_user("nobody") is False


def test_the_list_that_is_shown_is_still_masked(tmp_path, monkeypatch):
    engine = _engine(tmp_path, monkeypatch)
    shown = engine.add_user({"username": "anna", "password": "anna-Secret-1"})
    assert shown["password"] == sftp_engine.PASSWORD_MASK
    assert [u["password"] for u in engine.list_users()] == [sftp_engine.PASSWORD_MASK]


def test_a_damaged_list_is_cleared_and_logged(tmp_path, monkeypatch):
    engine = _engine(tmp_path, monkeypatch)
    logged = []
    monkeypatch.setattr("backend.users_db.log_security_event", lambda *a, **k: logged.append((a, k)))
    (tmp_path / "users.json").write_text(
        json.dumps([{"username": "anna", "password": "********"}, {"username": "key-only", "password": None}])
    )
    users = engine.list_users()
    assert [u.get("password") for u in users] == [None, None]
    assert _stored(tmp_path) == {"anna": None, "key-only": None}
    assert logged and logged[0][0][0] == "sftp.password_cleared" and logged[0][1]["details"] == {"users": ["anna"]}
    logged.clear()
    engine.list_users()
    assert not logged  # cleared once, not on every read


def test_the_mask_never_signs_in():
    assert rclone_auth_proxy._sftp_password_ok("********", "********") is False
    assert rclone_auth_proxy._sftp_password_ok("", "") is False
    assert rclone_auth_proxy._sftp_password_ok("old-plain-pw", "old-plain-pw") is True  # saved before hashing


def test_only_people_who_manage_shares_read_the_sign_in_names(client, auth_headers):
    create_user("fam_sftp", "Fam", "GoodPass123!", role_id="share_user")
    res = client.post("/api/auth/login", json={"username": "fam_sftp", "password": "GoodPass123!"})
    family = {"Authorization": f"Bearer {res.json()['token']}"}
    assert client.get("/api/sftp/users", headers=family).status_code == 403
    assert client.get("/api/sftp/users", headers=auth_headers).status_code == 200
