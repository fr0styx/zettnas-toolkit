"""A lost phone or tablet (Users decision 8, SET-19 stage 2): an administrator signs someone out
everywhere and can turn off their two-step code, with their own password; the person is told."""

import pytest

from backend.users_db import create_user, enable_user_mfa, get_user_by_username, get_user_mfa


def _kid(client, name="ld_kid"):
    user = get_user_by_username(name) or create_user(name, "Kid", "Kid-Pass-123!", role_id="kid")
    token = client.post("/api/auth/login", json={"username": name, "password": "Kid-Pass-123!"}).json()["token"]
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def told(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "backend.services.notifications.notify_person",
        lambda who, title, msg, level="warning": sent.append((who, title, msg)) or True,
    )
    return sent


def test_an_administrator_sees_where_someone_is_signed_in_without_the_secret(client, auth_headers):
    kid, _ = _kid(client)
    r = client.get(f"/api/users/{kid['id']}/sessions", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()["sessions"]
    assert rows and all(len(s["id"]) == 12 for s in rows)
    assert all("session_id_hash" not in s for s in rows)


def test_signing_out_everywhere_needs_the_own_password_and_tells_the_person(client, auth_headers, told):
    kid, kid_headers = _kid(client)
    assert client.get("/api/auth/me", headers=kid_headers).status_code == 200
    wrong = client.post(f"/api/users/{kid['id']}/lost-device", json={"current_password": "nope"}, headers=auth_headers)
    assert wrong.status_code == 403 and wrong.json()["error"] == "invalid_credentials"
    assert client.get("/api/auth/me", headers=kid_headers).status_code == 200  # nothing happened
    r = client.post(f"/api/users/{kid['id']}/lost-device", json={"current_password": "admin"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessions_ended"] >= 1 and body["two_step_off"] is False and body["told"] is True
    assert client.get("/api/auth/me", headers=kid_headers).status_code == 401
    assert told and told[-1][0] == "ld_kid" and "signed you out on every device" in told[-1][2]


def test_turning_off_the_two_step_code_for_a_new_phone(client, auth_headers, told):
    kid, _ = _kid(client, "ld_kid2")
    enable_user_mfa(kid["id"], "JBSWY3DPEHPK3PXP", [])
    assert get_user_mfa(kid["id"])["mfa_enabled"]
    r = client.post(
        f"/api/users/{kid['id']}/lost-device",
        json={"current_password": "admin", "sign_out": False, "turn_off_two_step": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["two_step_off"] is True and r.json()["sessions_ended"] == 0
    assert not get_user_mfa(kid["id"])["mfa_enabled"]
    assert "set it up on a new phone" in told[-1][2]


def test_the_wrong_turns_are_refused(client, auth_headers):
    kid, _ = _kid(client, "ld_kid3")
    nothing = client.post(
        f"/api/users/{kid['id']}/lost-device",
        json={"current_password": "admin", "sign_out": False},
        headers=auth_headers,
    )
    assert nothing.status_code == 400 and nothing.json()["error"] == "nothing_chosen"
    me = client.get("/api/auth/me", headers=auth_headers).json()
    own = client.post(f"/api/users/{me['id']}/lost-device", json={"current_password": "admin"}, headers=auth_headers)
    assert own.status_code == 400 and own.json()["error"] == "own_account"
    assert (
        client.post(
            "/api/users/nobody-at-all/lost-device", json={"current_password": "admin"}, headers=auth_headers
        ).status_code
        == 404
    )
    assert client.get("/api/users/nobody-at-all/sessions", headers=auth_headers).status_code == 404


def test_a_kid_cannot_do_this_for_anyone(client):
    kid, kid_headers = _kid(client, "ld_kid4")
    other, _ = _kid(client, "ld_kid5")
    assert client.get(f"/api/users/{other['id']}/sessions", headers=kid_headers).status_code == 403
    r = client.post(
        f"/api/users/{other['id']}/lost-device", json={"current_password": "Kid-Pass-123!"}, headers=kid_headers
    )
    assert r.status_code == 403


def test_nobody_acts_for_someone_with_more_rights(client, auth_headers):
    """SEC-26: an administrator below the owner can't sign the owner out."""
    if not get_user_by_username("ld_helper"):
        create_user("ld_helper", "Helper", "Help-Pass-123!", role_id="admin")
    tok = client.post("/api/auth/login", json={"username": "ld_helper", "password": "Help-Pass-123!"}).json()["token"]
    me = client.get("/api/auth/me", headers=auth_headers).json()
    r = client.post(
        f"/api/users/{me['id']}/lost-device",
        json={"current_password": "Help-Pass-123!"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


def test_the_person_not_told_when_nothing_was_done(client, auth_headers, told):
    """An account that had no sessions and no code: logged, nothing to tell."""
    kid = get_user_by_username("ld_kid6") or create_user("ld_kid6", "Kid", "Kid-Pass-123!", role_id="kid")
    r = client.post(
        f"/api/users/{kid['id']}/lost-device",
        json={"current_password": "admin", "turn_off_two_step": True},
        headers=auth_headers,
    )
    assert r.status_code == 200 and r.json() == {
        "status": "ok",
        "sessions_ended": 0,
        "two_step_off": False,
        "told": False,
    }
    assert not told
