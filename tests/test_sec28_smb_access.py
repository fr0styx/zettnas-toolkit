"""B11 (SEC-28, D11): since 1.12 SMB follows share access, and a two-factor account's password
no longer opens the network shares; it gets a separate SMB password instead."""

import os

import pytest

from backend import users_db
from backend.services import samba_engine, share_access
from backend.services.samba_engine import SambaShareConfig, access_lines
from backend.users_db import create_user, get_user_by_username, users_db_session


@pytest.fixture
def people():
    def make(name, role):
        return get_user_by_username(name) or create_user(name, name.title(), "GoodPass123!", role_id=role)

    return {"kim": make("smb_kim", "kid"), "sam": make("smb_sam", "share_user")}


def _lines(share="media", **kw):
    return access_lines(SambaShareConfig(name=share, path=f"/mnt/user/{share}", **kw))


def test_everyone_may_write_so_samba_needs_no_list(people):
    share_access.save_config({"default_level": "write", "shares": {}})
    assert _lines() == []


def test_people_kept_out_or_read_only_are_left_out_or_listed(people):
    share_access.save_config(
        {"default_level": "write", "shares": {"media": {"users": {"smb_kim": "none", "smb_sam": "read"}}}}
    )
    lines = _lines()
    valid = lines[0].split("=", 1)[1].split()
    assert "smb_kim" not in valid and "smb_sam" in valid and "admin" in valid
    assert lines[1] == "   read list = smb_sam"
    assert _lines(read_only=True) == lines[:1]  # read-only for everyone already


def test_a_new_install_default_lets_nobody_in_and_the_share_is_off(people):
    share_access.save_config({"default_level": "none", "shares": {}})
    assert _lines() == ["   available = no"]
    share_access.save_config({"default_level": "none", "shares": {"media": {"users": {"smb_sam": "write"}}}})
    assert _lines() == ["   valid users = smb_sam"]


def test_lists_set_on_the_share_and_guest_shares_are_kept(people):
    share_access.save_config({"default_level": "none", "shares": {}})
    assert _lines(valid_users="ann") == []
    assert _lines(guest_ok=True) == []


def test_the_lists_reach_smb_conf(people, tmp_path, monkeypatch):
    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(tmp_path / "smb.conf"))
    share_access.save_config({"default_level": "write", "shares": {"media": {"users": {"smb_kim": "none"}}}})
    engine = samba_engine.SambaEngine.__new__(samba_engine.SambaEngine)
    engine._shares = {"media": SambaShareConfig(name="media", path="/mnt/user/media")}
    monkeypatch.setattr(samba_engine, "validate_share", lambda s: None)
    conf = engine.generate_and_save_conf()
    section = conf.split("[media]", 1)[1]
    assert "valid users = " in section and "smb_kim" not in section.split("valid users = ", 1)[1].split("\n")[0]

    def broken(share):
        raise OSError("share access unreadable")

    monkeypatch.setattr(samba_engine, "access_lines", broken)
    assert "available = no" in engine.generate_and_save_conf().split("[media]", 1)[1]


def test_changes_rewrite_and_reload_only_where_zettnas_runs_samba(monkeypatch):
    calls = []

    class Engine:
        def __init__(self, shares):
            self.shares = shares

        def list_shares(self):
            return self.shares

        def generate_and_save_conf(self):
            calls.append("conf")

        def reload_service(self):
            calls.append("reload")

    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: Engine([]))
    samba_engine.refresh_access()
    assert calls == []
    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: Engine(["media"]))
    samba_engine.refresh_access()
    assert calls == ["conf", "reload"]


class _Passdb:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def sync_samba_user(self, username, password=None, delete=False):
        self.calls.append((username, password))
        return self.ok


@pytest.fixture
def passdb(monkeypatch):
    db = _Passdb()
    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: db)
    return db


def _two_factor(user, on=True):
    with users_db_session() as conn:
        conn.execute("UPDATE users SET mfa_enabled = ? WHERE id = ?", (1 if on else 0, user["id"]))


def test_a_two_factor_accounts_password_stays_out_of_samba(people, passdb):
    sam = people["sam"]
    _two_factor(sam)
    try:
        users_db.update_user_password(sam["id"], "NewPass123!x")
        assert passdb.calls == []
    finally:
        _two_factor(sam, on=False)
    users_db.update_user_password(sam["id"], "NewPass123!y")
    assert passdb.calls == [("smb_sam", "NewPass123!y")]


def test_turning_two_factor_on_replaces_the_smb_password(people, passdb):
    users_db.seal_smb_for_two_factor(people["sam"]["id"])
    ((name, password),) = passdb.calls
    assert name == "smb_sam" and len(password) >= 32
    users_db.seal_smb_for_two_factor("no-such-id")
    assert len(passdb.calls) == 1


def test_a_new_smb_password_is_easy_to_type_and_none_when_samba_refuses(people, passdb, monkeypatch):
    password = users_db.set_smb_password(people["sam"]["id"])
    assert len(password) == 23 and password.count("-") == 3
    assert users_db.set_smb_password("no-such-id") is None
    passdb.ok = False
    assert users_db.set_smb_password(people["sam"]["id"]) is None


def test_existing_two_factor_accounts_are_sealed_once(people, passdb, tmp_path):
    marker = str(tmp_path / "sealed")
    _two_factor(people["kim"])
    try:
        assert users_db.seal_smb_for_existing_two_factor(marker) >= 1
        assert os.path.exists(marker)
        assert users_db.seal_smb_for_existing_two_factor(marker) == 0
    finally:
        _two_factor(people["kim"], on=False)


def test_the_upgrade_step_uses_a_marker_in_the_data_folder(monkeypatch, tmp_path):
    from backend import config
    from backend.services import security_upgrade

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    seen = []
    monkeypatch.setattr(users_db, "seal_smb_for_existing_two_factor", lambda marker: seen.append(marker) or 2)
    assert security_upgrade.run_1_12_once() == 2
    assert seen == [str(tmp_path / security_upgrade.MARKER_1_12)]


def _login(client, name, password):
    r = client.post("/api/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"} if r.json().get("token") else {}


def test_the_endpoint_needs_the_password_and_two_factor(client, people, passdb, monkeypatch):
    from backend.api import auth as auth_api

    monkeypatch.setattr(auth_api, "_is_person_session", lambda user: True)
    sam = people["sam"]
    users_db.update_user_password(sam["id"], "GoodPass123!")  # an earlier test changed it
    passdb.calls.clear()
    client.cookies.clear()
    headers = _login(client, "smb_sam", "GoodPass123!")
    url = "/api/auth/me/smb-password"
    assert client.post(url, json={"current_password": "wrong"}, headers=headers).status_code == 403
    r = client.post(url, json={"current_password": "GoodPass123!"}, headers=headers)
    assert r.status_code == 400 and r.json()["error"] == "not_needed"
    _two_factor(sam)
    try:
        r = client.post(url, json={"current_password": "GoodPass123!"}, headers=headers)
        assert r.status_code == 200 and r.json()["username"] == "smb_sam" and r.json()["password"].count("-") == 3
        passdb.ok = False
        r = client.post(url, json={"current_password": "GoodPass123!"}, headers=headers)
        assert r.status_code == 503
    finally:
        _two_factor(sam, on=False)
    client.cookies.clear()
    assert client.post(url, json={"current_password": "x"}).status_code == 401
