"""Two-step sign-in required by role: someone in such a role who hasn't set it up can sign in
only to set it up; an administrator can't lock themselves out by requiring it for their own role."""

import pytest

from backend.services import mfa_policy
from backend.totp import generate_totp_secret
from backend.users_db import create_user, enable_user_mfa

PW = "GoodPass123!"


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setattr(mfa_policy, "POLICY_FILE", str(tmp_path / "mfa_policy.json"))
    mfa_policy.set_required_roles([])
    yield mfa_policy
    mfa_policy.set_required_roles([])


def _signin(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text
    return r.json(), {"Authorization": f"Bearer {r.json()['token']}"}


def test_a_role_that_requires_it_can_only_set_it_up(client, policy):
    person = create_user("mfa_must", "Must", PW, role_id="share_user")
    policy.set_required_roles(["share_user"])
    body, h = _signin(client, "mfa_must")
    assert body["mfa_setup_required"] is True
    blocked = client.get("/api/system/info", headers=h)
    assert blocked.status_code == 403 and blocked.json()["error"] == "mfa_setup_required"
    assert client.get("/api/auth/mfa/status", headers=h).status_code == 200  # setting it up still works
    assert client.get("/api/auth/me", headers=h).json()["mfa_setup_required"] is True
    enable_user_mfa(person["id"], generate_totp_secret(), [])
    policy.forget(person["id"])  # what turning it on through the API does
    assert client.get("/api/system/info", headers=h).json().get("error") != "mfa_setup_required"
    assert client.get("/api/auth/me", headers=h).json()["mfa_setup_required"] is False


def test_other_roles_and_a_lifted_policy_are_left_alone(client, policy):
    create_user("mfa_free", "Free", PW, role_id="share_user")
    policy.set_required_roles(["kid"])
    body, h = _signin(client, "mfa_free")
    assert body["mfa_setup_required"] is False
    assert client.get("/api/system/info", headers=h).json().get("error") != "mfa_setup_required"
    policy.set_required_roles(["share_user"])
    assert client.get("/api/system/info", headers=h).json()["error"] == "mfa_setup_required"
    policy.set_required_roles([])
    assert client.get("/api/system/info", headers=h).json().get("error") != "mfa_setup_required"


def test_an_admin_cannot_require_it_of_their_own_role_before_turning_it_on(client, auth_headers, policy):
    r = client.put("/api/security/mfa-policy", json={"required_roles": ["superadmin"]}, headers=auth_headers)
    assert r.status_code == 409 and "yourself first" in r.text
    assert (
        client.put("/api/security/mfa-policy", json={"required_roles": ["nope"]}, headers=auth_headers).status_code
        == 400
    )
    create_user("mfa_count", "Count", PW, role_id="backup_operator")
    r = client.put("/api/security/mfa-policy", json={"required_roles": ["backup_operator"]}, headers=auth_headers)
    assert r.status_code == 200, r.text
    view = client.get("/api/security/mfa-policy", headers=auth_headers).json()
    assert view["required_roles"] == ["backup_operator"]
    assert view["without_two_step"]["backup_operator"] >= 1


def test_directory_sign_ins_are_left_to_their_provider(policy):
    policy.set_required_roles(["share_user"])
    assert policy.account_needs_setup({"role_id": "share_user", "mfa_enabled": 0, "password_hash": "x"})
    assert not policy.account_needs_setup({"role_id": "share_user", "mfa_enabled": 0, "idp_type": "oidc"})
    assert not policy.account_needs_setup({"role_id": "share_user", "mfa_enabled": 1, "password_hash": "x"})
    assert not policy.setup_pending({"role_id": "share_user", "is_system": True}, lambda _id: None)
