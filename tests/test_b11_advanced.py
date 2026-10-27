"""B11 (UX-23): Advanced is each person's setting on the server: off for family roles and new
accounts, on for accounts that had everything before B11, and their own choice once made."""

import json
import time

from backend.api.auth import advanced_for
from backend.services import install_defaults
from backend.users_db import create_user, get_user_by_username


def _upgraded(at):
    with open(install_defaults._marker(), "w") as f:
        json.dump({"existing": at is not None, "at": at or time.time()}, f)


def test_family_roles_start_without_advanced():
    _upgraded(time.time())
    for role in ("kid", "guest", "share_user"):
        assert advanced_for({"role_id": role, "created_at": 1.0, "preferences": {}}) is False


def test_an_admin_who_had_everything_keeps_it_and_a_new_one_starts_without():
    now = time.time()
    _upgraded(now)
    assert advanced_for({"role_id": "superadmin", "created_at": now - 86400, "preferences": {}}) is True
    assert advanced_for({"role_id": "superadmin", "created_at": now + 60, "preferences": {}}) is False


def test_on_a_new_install_every_account_starts_without():
    _upgraded(None)
    assert install_defaults.upgraded_at() is None
    assert advanced_for({"role_id": "superadmin", "created_at": 1.0, "preferences": {}}) is False


def test_the_person_s_choice_wins():
    _upgraded(time.time())
    assert advanced_for({"role_id": "kid", "created_at": 1.0, "preferences": {"advanced": True}}) is True
    assert advanced_for({"role_id": "superadmin", "created_at": 1.0, "preferences": {"advanced": False}}) is False


def test_the_api_saves_it_for_the_person(client):
    if not get_user_by_username("adv_ann"):
        create_user("adv_ann", "Ann", "GoodPass123!", role_id="share_user")
    token = client.post("/api/auth/login", json={"username": "adv_ann", "password": "GoodPass123!"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).json()["advanced"] is False
    res = client.put("/api/auth/me/preferences", json={"advanced": True}, headers=headers)
    assert res.status_code == 200 and res.json()["advanced"] is True
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["advanced"] is True and me["preferences"]["advanced"] is True
