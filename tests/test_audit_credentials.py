"""Credentials, sessions and two-factor: regression tests for the 2026-10 security audit.

F02 scoped tokens and tickets act with their own scopes, F03 one admin login,
F05/F16 WebDAV portal, F07 cached sessions follow role changes, F08 2FA step-up,
F11 console tickets, F14 AI tools and confirmations.
"""

import secrets
import time
from unittest.mock import MagicMock

import pytest

from backend import config
from backend.api import auth as auth_api
from backend.passwords import hash_password, verify_password
from backend.totp import generate_totp_code, generate_totp_secret
from backend.users_db import (
    create_scoped_api_token,
    create_user,
    delete_user,
    enable_user_mfa,
    get_user_by_id,
    update_user_password,
    update_user_profile,
)

ADMIN = auth_api.ADMIN_USER_ID


def _name(prefix):
    return f"{prefix}{secrets.token_hex(3)}"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_scoped_token_acts_with_its_own_scopes(client, auth_headers):
    other = create_user(_name("tv"), "Other", "GoodPass123!", role_id="share_user")
    raw, _ = create_scoped_api_token(ADMIN, "view only", ["system:view"])

    assert client.get(f"/api/users/{other['id']}", headers=auth_headers).status_code == 200  # control
    assert client.get(f"/api/users/{other['id']}", headers=_bearer(raw)).status_code == 403
    r = client.put(f"/api/users/{other['id']}", headers=_bearer(raw), json={"role_id": "auditor"})
    assert r.status_code == 403
    assert get_user_by_id(other["id"])["role_id"] == "share_user"

    r = client.post("/api/auth/ticket", headers=_bearer(raw))
    assert r.status_code == 200
    ticket = r.json()["ticket"]
    assert auth_api._STREAM_TICKETS[ticket]["scopes"] == ["system:view"]
    # A ticket cannot be traded for another ticket.
    assert client.post("/api/auth/ticket", headers=_bearer(ticket)).status_code == 403


def test_token_cannot_create_a_token_with_more_scopes(client):
    raw, _ = create_scoped_api_token(ADMIN, "token admin", ["users:write"])
    r = client.post("/api/tokens", headers=_bearer(raw), json={"name": "wide", "scopes": ["*"]})
    assert r.status_code == 403


def test_other_superadmins_password_never_becomes_the_admin_login(client, auth_headers):
    name = _name("sa")
    other = create_user(name, "Second admin", "Dummy-Start-1x", role_id="superadmin")
    before = config.STORED_PASSWORD_HASH
    r = client.post(f"/api/users/{other['id']}/password", headers=auth_headers, json={"new_password": "Dummy-Other-77"})
    assert r.status_code == 200, r.text
    assert before == config.STORED_PASSWORD_HASH
    delete_user(other["id"])

    assert client.post("/api/auth/login", json={"username": "admin", "password": "Dummy-Other-77"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 200


def test_an_old_copy_of_the_admin_hash_is_not_a_login(client):
    config.STORED_PASSWORD_HASH = hash_password("Copied-Elsewhere-9")
    r = client.post("/api/auth/login", json={"username": "admin", "password": "Copied-Elsewhere-9"})
    assert r.status_code == 401
    auth_api.align_admin_password_mirror()
    assert verify_password("admin", config.STORED_PASSWORD_HASH)


def test_role_and_status_changes_reach_cached_sessions_and_tokens(client):
    from backend.auth import get_current_session

    name = _name("dm")
    user = create_user(name, "Demoted", "GoodPass123!", role_id="superadmin")
    session = _login(client, name, "GoodPass123!")
    raw, _ = create_scoped_api_token(user["id"], "t", ["system:view"])
    assert get_current_session(session)["role_id"] == "superadmin"  # now cached
    assert get_current_session(raw)

    update_user_profile(user["id"], role_id="share_user")
    assert get_current_session(session)["role_id"] == "share_user"
    assert "*" not in get_current_session(session)["scopes"]

    update_user_profile(user["id"], status="disabled")
    assert get_current_session(raw) is None
    assert get_current_session(session) is None


def test_second_factor_needs_the_password_and_a_signed_in_person(client):
    name = _name("mf")
    user = create_user(name, "Two factor", "GoodPass123!", role_id="share_user")
    session = _login(client, name, "GoodPass123!")
    secret = generate_totp_secret()
    body = {"secret": secret, "code": generate_totp_code(secret)}

    assert client.post("/api/auth/mfa/enable", headers=_bearer(session), json=body).status_code == 403
    raw, _ = create_scoped_api_token(user["id"], "t", ["*"])
    with_pw = {**body, "current_password": "GoodPass123!"}
    assert client.post("/api/auth/mfa/enable", headers=_bearer(raw), json=with_pw).status_code == 403
    assert client.post("/api/auth/mfa/setup", headers=_bearer(raw)).status_code == 403

    r = client.post("/api/auth/mfa/enable", headers=_bearer(session), json=with_pw)
    assert r.status_code == 200, r.text

    # Replacing the authenticator needs a code from the current one.
    new_secret = generate_totp_secret()
    replace = {"secret": new_secret, "code": generate_totp_code(new_secret), "current_password": "GoodPass123!"}
    assert client.post("/api/auth/mfa/enable", headers=_bearer(session), json=replace).status_code == 403
    replace["current_code"] = generate_totp_code(secret)
    assert client.post("/api/auth/mfa/enable", headers=_bearer(session), json=replace).status_code == 200


def test_console_tickets_only_open_their_vm_console(client, auth_headers, monkeypatch):
    import backend.api.vms as vms_api

    monkeypatch.setattr(vms_api, "_load_vms", lambda: [{"id": "vm-dummy"}])
    r = client.post("/api/vms/vm-dummy/console/token", headers=auth_headers)
    assert r.status_code == 200, r.text
    ticket = r.json()["ticket"]
    assert vms_api._CONSOLE_TICKETS[ticket]["user_id"] == ADMIN

    # Not an API credential.
    assert client.post("/api/auth/ticket", headers=_bearer(ticket)).status_code == 401
    assert client.get("/api/users", headers=_bearer(ticket)).status_code == 401
    # Not another VM's console.
    assert vms_api._validate_console_ticket(ticket, "vm-other") is False

    vms_api._CONSOLE_TICKETS["zct_fresh"] = {"vm_id": "vm-dummy", "user_id": ADMIN, "expires_at": time.time() + 60}
    assert vms_api._validate_console_ticket("zct_fresh", "vm-dummy") is True


def test_ai_tools_follow_the_credentials_scopes():
    from backend.auth import AuthenticatedPrincipal
    from backend.services import ai_actions, ai_chat_agent

    token = AuthenticatedPrincipal(
        {
            "user_id": ADMIN,
            "username": "admin",
            "role_id": "superadmin",
            "scopes": ["system:view"],
            "is_api_token": True,
        }
    )
    person = AuthenticatedPrincipal({"user_id": ADMIN, "username": "admin", "role_id": "superadmin", "scopes": ["*"]})
    assert not ai_chat_agent._has_write_permission(token, ("containers:manage",))
    assert ai_chat_agent._has_write_permission(person, ("containers:manage",))

    action_id = ai_actions.propose_action("set_fan_profile", {"profile": "quiet"}, person)["action_id"]
    assert ai_actions.confirm_action(action_id, token)["status"] == "not_found"
    assert action_id in ai_actions._pending  # still waiting for the person


@pytest.fixture
def portal_user():
    name = _name("wd")
    user = create_user(name, "Portal", "GoodPass123!", role_id="share_user")
    return name, user


def test_webdav_portal_is_closed_while_webdav_is_off(client, portal_user, monkeypatch):
    from backend.services.webdav_engine import WebdavEngine

    real = WebdavEngine.load_config
    monkeypatch.setattr(WebdavEngine, "load_config", lambda self: {**real(self), "enabled": False})
    name, _ = portal_user
    r = client.post("/webdav/auth/login", data={"username": name, "password": "GoodPass123!"}, follow_redirects=False)
    assert r.status_code == 404
    assert client.get("/webdav/", follow_redirects=False).status_code == 404


def test_webdav_portal_refuses_two_factor_accounts(client, portal_user, webdav_on):
    name, user = portal_user
    enable_user_mfa(user["id"], generate_totp_secret(), [])
    r = client.post("/webdav/auth/login", data={"username": name, "password": "GoodPass123!"}, follow_redirects=False)
    assert r.status_code == 403
    assert "webdav_session" not in r.cookies


def test_webdav_cookie_ends_with_a_password_change(client, portal_user, webdav_on):
    from backend.api.webdav import _get_webdav_portal_user

    name, user = portal_user
    r = client.post("/webdav/auth/login", data={"username": name, "password": "GoodPass123!"}, follow_redirects=False)
    assert r.status_code == 303
    req = MagicMock()
    req.cookies = {"webdav_session": r.cookies.get("webdav_session")}
    req.state.session = None
    assert _get_webdav_portal_user(req, {"auth_enabled": True})["username"] == name

    update_user_password(user["id"], "NewGoodPass456!")
    assert _get_webdav_portal_user(req, {"auth_enabled": True}) is None


def test_api_token_does_not_open_the_webdav_portal(portal_user):
    from backend.api.webdav import _get_webdav_portal_user

    raw, _ = create_scoped_api_token(ADMIN, "view", ["system:view"])
    req = MagicMock()
    req.cookies = {}
    req.state.session = {
        "user_id": ADMIN,
        "username": "admin",
        "role_id": "superadmin",
        "scopes": ["system:view"],
        "is_api_token": True,
    }
    assert _get_webdav_portal_user(req, {"auth_enabled": True}) is None
