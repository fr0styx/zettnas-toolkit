"""B10 / SEC-26, SEC-27: no taking over a stronger account; turning off two-factor needs more than a session."""

import pytest
from fastapi import HTTPException

from backend.api import auth, invites


class _Provisioner:
    """A token that may manage users and nothing else."""

    username = "provisioner"
    user_id = "prov"
    scopes = ["users:read", "users:write", "users:delete"]


def test_rights_are_compared_before_acting_on_an_account():
    assert not auth._role_within(_Provisioner.scopes, "superadmin")
    assert not auth._role_within(_Provisioner.scopes, "app_operator")
    assert auth._role_within(["*"], "superadmin")


def test_an_invite_cannot_hand_out_more_than_its_creator_can_do():
    with pytest.raises(HTTPException) as e:
        invites.new_invite(invites.InviteIn(role_id="app_operator"), _Provisioner())
    assert e.value.status_code == 403
    owner = type("Owner", (), {"username": "owner", "user_id": "o", "scopes": ["*"]})()
    assert invites.new_invite(invites.InviteIn(role_id="app_operator"), owner)["token"]


def test_a_provisioning_token_cannot_delete_or_reset_a_superadmin(client, auth_headers):
    from backend.users_db import create_user, get_user_by_username

    create_user("boss2", "Boss", "Boss-Pass-123", role_id="superadmin")
    boss = get_user_by_username("boss2")
    res = auth.delete_user_endpoint(boss["id"], _Req(), _Provisioner())
    assert res.status_code == 403 and get_user_by_username("boss2")


class _Req:
    client = None
    state = type("S", (), {"session": None})()


def test_turning_off_two_factor_needs_password_and_code_and_is_rate_limited(client, auth_headers, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(auth, "get_user_mfa", lambda uid: {"mfa_enabled": True, "mfa_secret": "S"})
    monkeypatch.setattr(auth, "verify_totp_code", lambda secret, code, user_id=None: code == "123456")
    monkeypatch.setattr(auth, "consume_user_recovery_code", lambda uid, code: False)
    monkeypatch.setattr(auth, "disable_user_mfa", lambda uid: calls.__setitem__("n", calls["n"] + 1) or True)
    monkeypatch.setattr(auth, "_is_person_session", lambda user: True)
    url = "/api/auth/mfa/disable"
    assert client.post(url, json={"password": "admin"}, headers=auth_headers).status_code == 401  # no code
    assert client.post(url, json={"code": "123456"}, headers=auth_headers).status_code == 401  # no password
    assert calls["n"] == 0
    statuses = [
        client.post(url, json={"password": "wrong", "code": "000000"}, headers=auth_headers).status_code
        for _ in range(15)
    ]
    assert 429 in statuses  # guessing is locked out
    assert calls["n"] == 0
