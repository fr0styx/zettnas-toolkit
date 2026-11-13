"""An invite carries shared folders and sign-in hours (Users decision 11, SET-19 stage 2)."""

import json

import pytest

from backend.services import share_access
from backend.users_db import get_user_by_username, invite_extras

HOURS = {"days": [0, 1, 2, 3, 4], "start": "07:00", "end": "20:00"}


@pytest.fixture
def folders(monkeypatch, tmp_path):
    monkeypatch.setattr(share_access, "_file", lambda: str(tmp_path / "share_access.json"))
    monkeypatch.setattr(
        share_access,
        "known_shares",
        lambda: [
            {"name": "family", "path": "/x/family", "samba": None},
            {"name": "media", "path": "/x/media", "samba": None},
        ],
    )
    refreshed = []
    monkeypatch.setattr("backend.services.samba_engine.refresh_access", lambda: refreshed.append(1))
    return refreshed


def _invite(client, headers, **extra):
    return client.post("/api/invites", json={"role_id": "kid", "days": 3, **extra}, headers=headers)


def test_the_invited_kid_gets_the_folders_and_the_hours(client, auth_headers, folders):
    r = _invite(client, auth_headers, shares={"family": "write", "media": "read"}, signin_hours=HOURS)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["invite"]["shares"] == {"family": "write", "media": "read"}
    listed = next(
        i
        for i in client.get("/api/invites", headers=auth_headers).json()["invites"]
        if i["id"] == r.json()["invite"]["id"]
    )
    assert listed["shares"] == {"family": "write", "media": "read"} and listed["signin_hours"] == HOURS
    assert "shares_json" not in listed
    info = client.get(f"/api/invite/{token}").json()
    assert info["shares"] == {"family": "write", "media": "read"} and info["signin_hours"] == HOURS
    ok = client.post(f"/api/invite/{token}/accept", json={"username": "inv_mia", "password": "Mia-Pass-12345"})
    assert ok.status_code == 200, ok.text
    user = get_user_by_username("inv_mia")
    assert json.loads(user["signin_hours_json"]) == HOURS
    cfg = share_access.load_config()
    assert cfg["shares"]["family"]["users"]["inv_mia"] == "write"
    assert cfg["shares"]["media"]["users"]["inv_mia"] == "read"
    assert folders  # SMB follows


def test_an_invite_without_extras_works_as_before(client, auth_headers, folders):
    r = _invite(client, auth_headers)
    assert r.status_code == 200 and r.json()["invite"]["shares"] == {} and r.json()["invite"]["signin_hours"] is None
    ok = client.post(
        f"/api/invite/{r.json()['token']}/accept", json={"username": "inv_plain", "password": "Plain-Pass-12345"}
    )
    assert ok.status_code == 200
    assert not get_user_by_username("inv_plain").get("signin_hours_json")


def test_what_an_invite_may_not_give(client, auth_headers, folders):
    assert _invite(client, auth_headers, shares={"nowhere": "read"}).status_code == 400
    assert _invite(client, auth_headers, shares={"family": "own"}).status_code == 422
    bad = _invite(client, auth_headers, signin_hours={"days": [], "start": "07:00", "end": "20:00"})
    assert bad.status_code == 400 and "day" in bad.json()["detail"]
    operator = client.post(
        "/api/invites", json={"role_id": "backup_operator", "signin_hours": HOURS}, headers=auth_headers
    )
    assert operator.status_code in (200, 400)  # hours only for roles that don't manage people


def test_unreadable_extras_count_as_none():
    assert invite_extras({"shares_json": "{not json", "signin_hours_json": "[1]"}) == {
        "shares": {},
        "signin_hours": None,
    }
    assert invite_extras({}) == {"shares": {}, "signin_hours": None}


def test_a_folder_that_could_not_be_given_leaves_the_account(client, auth_headers, folders, monkeypatch):
    token = _invite(client, auth_headers, shares={"family": "read"}).json()["token"]

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(share_access, "grant", broken)
    ok = client.post(f"/api/invite/{token}/accept", json={"username": "inv_lou", "password": "Lou-Pass-12345"})
    assert ok.status_code == 200 and get_user_by_username("inv_lou")
