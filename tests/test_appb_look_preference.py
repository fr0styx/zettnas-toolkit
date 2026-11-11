"""A person's look is kept on their account and checked field by field (APP-B)."""

import pytest
from pydantic import ValidationError

from backend.api.auth import LookPreference, MyPreferences
from backend.users_db import create_user, get_user_by_username


def test_a_look_is_kept_as_sent():
    prefs = MyPreferences(
        look={"mode": "auto", "theme": "heather", "tint": 0.4, "trueBlack": True, "accent": "#33cdb8"}
    )
    assert prefs.model_dump()["look"] == {
        "mode": "auto",
        "theme": "heather",
        "tint": 0.4,
        "trueBlack": True,
        "accent": "#33cdb8",
    }


def test_missing_fields_take_the_default_look():
    assert LookPreference().model_dump() == {
        "mode": "dark",
        "theme": "lagoon",
        "tint": 0,
        "trueBlack": False,
        "accent": "",
    }


@pytest.mark.parametrize(
    "bad",
    [{"theme": "sapphire"}, {"mode": "sepia"}, {"tint": 1.5}, {"tint": -0.1}, {"accent": "red"}, {"accent": "#12345"}],
    ids=["old-theme-name", "unknown-mode", "tint-too-high", "tint-below-zero", "accent-word", "accent-short"],
)
def test_a_look_outside_the_choices_is_refused(bad):
    with pytest.raises(ValidationError):
        LookPreference(**bad)


def test_the_look_is_saved_on_the_account(client):
    if not get_user_by_username("look_lou"):
        create_user("look_lou", "Lou", "GoodPass123!", role_id="share_user")
    token = client.post("/api/auth/login", json={"username": "look_lou", "password": "GoodPass123!"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = client.put(
        "/api/auth/me/preferences", json={"look": {"theme": "fjord", "mode": "light", "tint": 0.25}}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["preferences"]["look"]["theme"] == "fjord"
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["preferences"]["look"] == {
        "mode": "light",
        "theme": "fjord",
        "tint": 0.25,
        "trueBlack": False,
        "accent": "",
    }
