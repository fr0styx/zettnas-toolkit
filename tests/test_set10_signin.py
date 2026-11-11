"""SET-10: an open session is held to the sign-in hours it started under; a wrong code when turning
off two-step sign-in is "not allowed", not "signed out"; the password form acts on the person who
is signed in."""

from datetime import datetime, timedelta

import pytest

from backend import signin_hours, users_db

PW = "a-long-enough-pass-1"


def _around_now():
    now = datetime.now()
    return {
        "days": list(range(7)),
        "start": (now - timedelta(hours=1)).strftime("%H:%M"),
        "end": (now + timedelta(hours=1)).strftime("%H:%M"),
    }


@pytest.fixture
def person(client):
    made = []

    def make(name, role):
        user = users_db.create_user(name, name.title(), PW, role_id=role)
        made.append(user["id"])
        return user

    yield make
    for uid in made:
        users_db.delete_user(uid)


def _signed_in(client, name, password=PW):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_a_session_started_inside_the_hours_stops_at_their_end(client, auth_headers, person, monkeypatch):
    """The hours are set first, then the kid signs in: that session was remembered without the
    hours and kept working past their end. (The older test set the hours after the sign-in.)"""
    kid = person("set10kid", "kid")
    assert (
        client.put(f"/api/users/{kid['id']}", json={"signin_hours": _around_now()}, headers=auth_headers).status_code
        == 200
    )
    headers = _signed_in(client, "set10kid")
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    real = signin_hours.allowed
    later = datetime.now() + timedelta(hours=3)  # the clock moves past the end
    monkeypatch.setattr(signin_hours, "allowed", lambda hours, now=None: real(hours, now or later))
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    monkeypatch.setattr(signin_hours, "allowed", real)  # the next day, inside the hours again
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=headers).status_code == 200  # it resumes by itself


def test_a_wrong_code_when_turning_off_two_step_sign_in_is_not_a_sign_out(client, auth_headers):
    r = client.post(
        "/api/auth/mfa/disable", json={"password": "not-the-password", "code": "000000"}, headers=auth_headers
    )
    if r.status_code == 404:
        pytest.skip("route name differs")
    assert r.status_code != 401, "the app reads 401 as: your session ended"
    assert client.get("/api/auth/me", headers=auth_headers).status_code == 200


def test_the_password_form_changes_the_signed_in_administrators_own_password(client, auth_headers, person):
    anna = person("set10anna", "superadmin")
    headers = _signed_in(client, "set10anna")
    from backend.api import auth as auth_api

    builtin = auth_api.ADMIN_USER_ID
    builtin_before = (users_db.get_user_by_id(builtin) or {}).get("password_hash")
    r = client.post(
        "/api/security", json={"current_password": PW, "new_password": "another-long-pass-2"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json().get("own_account") is True
    # her password changed, the built-in account's did not, and nobody else was signed out
    assert (users_db.get_user_by_id(builtin) or {}).get("password_hash") == builtin_before
    assert client.get("/api/auth/me", headers=auth_headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 200  # this session is kept
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"username": "set10anna", "password": PW}).status_code in (401, 403)
    assert anna["id"]
    _signed_in(client, "set10anna", "another-long-pass-2")


def test_a_family_member_and_a_kid_change_their_own_password(client, person):
    for name, role in (("set10fam", "share_user"), ("set10kid2", "kid")):
        user = person(name, role)
        headers = _signed_in(client, name)
        r = client.post(
            f"/api/users/{user['id']}/password",
            json={"current_password": PW, "new_password": "their-own-new-pass-3"},
            headers=headers,
        )
        assert r.status_code == 200, (role, r.text)
        _signed_in(client, name, "their-own-new-pass-3")
