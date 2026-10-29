"""COMP-13: a family account can have sign-in hours; outside them it can't sign in and an open
session stops working until they start again."""

from datetime import datetime, timedelta

import pytest

from backend import signin_hours as sh
from backend import users_db

PW = "a-Long-unique-pw-91"


def test_normalize():
    assert sh.normalize({"days": [4, 0, 0, "2"], "start": "07:00", "end": "20:30"}) == {
        "days": [0, 2, 4],
        "start": "07:00",
        "end": "20:30",
    }
    assert sh.normalize(None) is None and sh.normalize({}) is None


@pytest.mark.parametrize(
    "bad",
    [
        {"days": [], "start": "07:00", "end": "20:00"},
        {"days": [7], "start": "07:00", "end": "20:00"},
        {"days": [1], "start": "7:00", "end": "20:00"},
        {"days": [1], "start": "07:00", "end": "24:00"},
        {"days": [1], "start": "08:00", "end": "08:00"},
        "weekdays",
    ],
)
def test_bad_hours_are_refused(bad):
    with pytest.raises(ValueError):
        sh.normalize(bad)


def test_stored_garbage_means_no_limit():
    assert sh.from_json("not json") is None and sh.from_json("") is None
    assert sh.from_json('{"days": [1], "start": "07:00", "end": "20:00"}')["days"] == [1]


SCHOOL = {"days": [0, 1, 2, 3, 4], "start": "07:00", "end": "20:00"}


def test_daytime_hours():
    mon = datetime(2026, 11, 2)  # a Monday
    assert sh.allowed(SCHOOL, mon.replace(hour=7))
    assert sh.allowed(SCHOOL, mon.replace(hour=19, minute=59))
    assert not sh.allowed(SCHOOL, mon.replace(hour=20))
    assert not sh.allowed(SCHOOL, mon.replace(hour=6, minute=59))
    assert not sh.allowed(SCHOOL, (mon + timedelta(days=5)).replace(hour=12))  # Saturday
    assert sh.allowed(None, mon)


def test_hours_past_midnight_belong_to_the_day_they_start():
    late = {"days": [4], "start": "21:00", "end": "01:00"}  # Friday night
    fri = datetime(2026, 11, 6)
    assert sh.allowed(late, fri.replace(hour=23))
    assert sh.allowed(late, (fri + timedelta(days=1)).replace(hour=0, minute=30))  # Saturday 00:30
    assert not sh.allowed(late, (fri + timedelta(days=1)).replace(hour=1))
    assert not sh.allowed(late, fri.replace(hour=0, minute=30))  # Friday 00:30 belongs to Thursday
    assert not sh.allowed(late, fri.replace(hour=20))


def test_describe():
    assert sh.describe(SCHOOL) == "Mon-Fri 07:00-20:00"
    assert sh.describe({"days": list(range(7)), "start": "08:00", "end": "21:00"}) == "every day 08:00-21:00"
    assert sh.describe({"days": [5, 6], "start": "09:00", "end": "22:00"}) == "Sat, Sun 09:00-22:00"


# --- through the API ---


def _not_now():
    """Hours that exclude this moment: every day but today."""
    today = datetime.now().weekday()
    return {"days": [d for d in range(7) if d != today], "start": "00:00", "end": "23:59"}


def _around_now():
    now = datetime.now()
    return {
        "days": list(range(7)),
        "start": (now - timedelta(hours=1)).strftime("%H:%M"),
        "end": (now + timedelta(hours=1)).strftime("%H:%M"),
    }


@pytest.fixture
def kid(client):
    user = users_db.create_user("kim", "Kim", PW, role_id="kid")
    yield user
    users_db.delete_user(user["id"]) if hasattr(users_db, "delete_user") else None


def _login(client, password=PW):
    return client.post("/api/auth/login", json={"username": "kim", "password": password})


def test_an_admin_sets_hours_and_they_are_shown(client, auth_headers, kid):
    r = client.put(f"/api/users/{kid['id']}", json={"signin_hours": SCHOOL}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["signin_hours"] == SCHOOL
    assert "signin_hours_json" not in r.json()["user"]
    r = client.put(f"/api/users/{kid['id']}", json={"signin_hours": {}}, headers=auth_headers)
    assert r.json()["user"]["signin_hours"] is None


def test_bad_hours_are_a_400(client, auth_headers, kid):
    r = client.put(
        f"/api/users/{kid['id']}",
        json={"signin_hours": {"days": [], "start": "07:00", "end": "08:00"}},
        headers=auth_headers,
    )
    assert r.status_code == 400 and r.json()["error"] == "bad_signin_hours"


def test_an_account_that_manages_people_cannot_be_limited(client, auth_headers):
    me = client.get("/api/auth/me", headers=auth_headers).json()
    uid = (me.get("user") or me)["id"]
    r = client.put(f"/api/users/{uid}", json={"signin_hours": SCHOOL}, headers=auth_headers)
    assert r.status_code == 400 and "family accounts" in r.json()["detail"]


def test_outside_the_hours_sign_in_is_refused(client, auth_headers, kid):
    client.put(f"/api/users/{kid['id']}", json={"signin_hours": _not_now()}, headers=auth_headers)
    client.cookies.clear()
    r = _login(client)
    assert r.status_code == 403 and r.json()["error"] == "outside_signin_hours"
    assert r.json()["signin_hours"]["start"] == "00:00"


def test_inside_the_hours_sign_in_works(client, auth_headers, kid):
    client.put(f"/api/users/{kid['id']}", json={"signin_hours": _around_now()}, headers=auth_headers)
    client.cookies.clear()
    assert _login(client).status_code == 200


def test_an_open_session_stops_at_the_end_of_the_hours(client, auth_headers, kid):
    client.cookies.clear()
    r = _login(client)
    assert r.status_code == 200, r.text
    kid_headers = {"Authorization": f"Bearer {r.json()['token']}"}
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=kid_headers).status_code == 200
    assert (
        client.put(f"/api/users/{kid['id']}", json={"signin_hours": _not_now()}, headers=auth_headers).status_code
        == 200
    )
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=kid_headers).status_code == 401
    client.put(f"/api/users/{kid['id']}", json={"signin_hours": {}}, headers=auth_headers)
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=kid_headers).status_code == 200  # the session itself was kept


def test_a_person_cannot_change_their_own_hours(client, auth_headers, kid):
    client.put(f"/api/users/{kid['id']}", json={"signin_hours": _around_now()}, headers=auth_headers)
    client.cookies.clear()
    kid_headers = {"Authorization": f"Bearer {_login(client).json()['token']}"}
    client.cookies.clear()
    r = client.put(f"/api/users/{kid['id']}", json={"signin_hours": {}}, headers=kid_headers)
    assert r.status_code == 403
