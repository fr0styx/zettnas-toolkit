"""SET-04: a key made for an app works on the address for apps and nowhere else.

The page said "a key can do nothing else". Every route that only asks for a sign-in took it: its
owner's data export and erase, MCP, their Immich connection. The sign-in check now refuses the key
on every address but its own. The walk below goes over every route the server has."""

import re

import pytest

from backend import auth
from backend.main import app
from backend.services import ai_apps
from backend.users_db import create_scoped_api_token, get_user_by_username, revoke_scoped_api_token

METHODS = ("get", "post", "put", "patch", "delete")


@pytest.fixture
def app_key(client, auth_headers):
    admin = get_user_by_username("admin")
    raw, meta = create_scoped_api_token(user_id=admin["id"], name="set04 app key", scopes=[ai_apps.SCOPE])
    yield {"Authorization": f"Bearer {raw}"}
    revoke_scoped_api_token(meta["token_id"])


def _routes():
    for path, item in app.openapi()["paths"].items():
        for method in METHODS:
            if method in item:
                yield method, re.sub(r"\{[^}]+\}", "x", path)


def test_the_two_names_of_the_scope_agree():
    assert auth.APP_KEY_SCOPE == ai_apps.SCOPE


def test_the_key_is_refused_on_every_route_that_needs_a_sign_in(client, app_key):
    walked, taken = 0, []
    for method, path in _routes():
        if not path.startswith(("/api/", "/redfish")):  # the pages themselves need no sign-in
            continue
        if auth.is_public_path(path) or path.startswith("/api/v1/ai/openai/"):
            continue
        walked += 1
        r = client.request(method.upper(), path, headers=app_key)
        if r.status_code != 403 or r.json().get("error") != "app_key_only":
            taken.append(f"{method.upper()} {path} -> {r.status_code}")
    assert walked > 500  # the walk really went over the server's routes
    assert taken == []


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/api/user/data/export"),
        ("POST", "/api/mcp"),
        ("GET", "/api/immich/connection"),
        ("GET", "/api/fs/list"),
        ("GET", "/redfish/v1/Systems"),
    ],
)
def test_the_addresses_the_review_named(client, app_key, method, path):
    r = client.request(method, path, headers=app_key)
    assert r.status_code == 403 and r.json()["error"] == "app_key_only"


def test_the_key_still_works_on_its_own_address(client, app_key):
    for path in ("/api/v1/ai/openai/models", "/api/ai/openai/models"):
        r = client.get(path, headers=app_key)
        assert r.status_code == 200, r.text


def test_a_token_with_other_scopes_is_an_ordinary_token(client):
    admin = get_user_by_username("admin")
    raw, meta = create_scoped_api_token(user_id=admin["id"], name="set04 mixed", scopes=[ai_apps.SCOPE, "system:view"])
    try:
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code != 403 or r.json().get("error") != "app_key_only"
    finally:
        revoke_scoped_api_token(meta["token_id"])


def test_the_check_also_holds_without_the_middleware():
    """get_current_principal() is the second place: a route reached with no middleware in front."""
    from fastapi import HTTPException
    from starlette.requests import Request

    sess = {"user_id": "u", "username": "u", "scopes": [ai_apps.SCOPE], "is_api_token": True}
    req = Request({"type": "http", "path": "/api/user/data/export", "headers": [], "state": {"session": sess}})
    with pytest.raises(HTTPException) as e:
        auth.get_current_principal(req)
    assert e.value.status_code == 403
    req = Request({"type": "http", "path": "/api/v1/ai/openai/models", "headers": [], "state": {"session": sess}})
    assert auth.get_current_principal(req).scopes == [ai_apps.SCOPE]
