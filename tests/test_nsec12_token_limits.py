"""NSEC-1 and NSEC-2: a token keeps its folder limit in tickets, and gets only the rights its app needs."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import tickets
from backend.api import system


def test_a_ticket_keeps_the_tokens_folders():
    t = tickets.create_stream_ticket(
        "u1", "mia", ["files:read"], "share_user", folders=["/mnt/user/Docs"], token_id="tk1"
    )
    got = tickets.validate_and_consume_stream_ticket(t)
    assert got["folders"] == ["/mnt/user/Docs"] and got["token_id"] == "tk1" and got["is_stream_ticket"]
    assert tickets.validate_and_consume_stream_ticket(t) is None  # single use
    plain = tickets.create_stream_ticket("u1", "mia", ["files:read"], "share_user")
    assert tickets.validate_and_consume_stream_ticket(plain)["folders"] == []


def test_the_request_user_keeps_the_tokens_folders(monkeypatch):
    from backend.api import auth

    monkeypatch.setattr(auth, "get_user_by_id", lambda uid: {"id": uid, "username": "mia", "status": "active"})
    user = auth._credential_user(
        {
            "user_id": "u1",
            "scopes": ["files:read"],
            "folders": ["/mnt/user/Docs"],
            "token_id": "tk1",
            "is_api_token": True,
        }
    )
    assert user["folders"] == ["/mnt/user/Docs"] and user["token_id"] == "tk1" and user["is_api_token"]


def _req(**kw):
    return system.TokenCreateRequest(name="app", **kw)


ADMIN = SimpleNamespace(scopes=["*"])
PARENT = SimpleNamespace(scopes=["shares:read", "files:read", "shares:user_write", "files:write", "system:view"])


def test_presets():
    assert system.token_scopes(_req(preset="files-read"), ADMIN) == ["shares:read", "files:read"]
    assert system.token_scopes(_req(preset="monitoring"), PARENT) == ["system:view"]  # only what the creator holds
    assert system.token_scopes(_req(preset="full"), ADMIN) == ["*"]
    with pytest.raises(HTTPException):
        system.token_scopes(_req(preset="root"), ADMIN)
    with pytest.raises(HTTPException, match="don't hold"):
        system.token_scopes(_req(preset="mcp"), SimpleNamespace(scopes=["hardware:read"]))


def test_folder_limited_tokens_stay_inside_folders():
    assert system.token_scopes(_req(folders=["/mnt/user/Docs"]), ADMIN) == system.TOKEN_PRESETS["files-write"]
    for wide in (_req(folders=["/x"], preset="full"), _req(folders=["/x"], scopes=["containers:exec"])):
        with pytest.raises(HTTPException) as e:
            system.token_scopes(wide, ADMIN)
        assert e.value.status_code == 400 and "reach past any folder" in e.value.detail


def test_no_choice_without_folders_keeps_the_old_behaviour():
    assert system.token_scopes(_req(), PARENT) == PARENT.scopes
    assert system.token_scopes(_req(scopes=["system:view"]), PARENT) == ["system:view"]


def test_the_api(client, auth_headers):
    r = client.post("/api/tokens", headers=auth_headers, json={"name": "ha", "preset": "monitoring"})
    assert r.status_code == 200 and r.json()["scopes"] == system.TOKEN_PRESETS["monitoring"]
    bad = client.post(
        "/api/tokens", headers=auth_headers, json={"name": "x", "preset": "full", "folders": ["/mnt/user"]}
    )
    assert bad.status_code in (400, 403)
