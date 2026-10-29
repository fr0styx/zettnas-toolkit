"""SEC-33: kids and guests see the desktop, not the machine. /api/stats and its stream give
them the server's name, status, storage use, uptime and their own layout, nothing else."""

import json

from backend.api import stats as stats_api
from backend.auth import AuthenticatedPrincipal
from backend.users_db import create_user

FULL = {
    "name": "nas",
    "status": "-- OK",
    "ip": "192.0.2.10",
    "storage": {"used": "1TB", "total": "4TB", "pct": 25, "engine": "ZFS", "pools": ["tank"]},
    "system": {"uptime_str": "2d", "uptime_sec": 172800, "hostname": "nas", "kernel": "6.12", "distro": "Debian"},
    "disks": [{"serial": "WD-123"}],
    "docker": {"running": 3},
    "events": [{"msg": "admin signed in"}],
    "security": {"is_default_password": True},
    "copy_state": {"active": True},
    "uptime": "2d",
    "layout": {"order": ["clock"]},
    "client_preferences": {"lcd_theme": "dark"},
    "remotes_event": {"timestamp": 5, "remote": "gdrive", "mountpoint": "/mnt/remotes/gdrive"},
}


def _login(client, username, role_id, password="GoodPass123!"):
    create_user(username, username, password, role_id=role_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_the_family_view_keeps_only_the_desktop():
    view = stats_api.family_view(FULL)
    assert set(view) == {
        "name",
        "status",
        "storage",
        "system",
        "uptime",
        "layout",
        "client_preferences",
        "remotes_event",
    }
    assert view["storage"] == {"used": "1TB", "total": "4TB", "pct": 25}
    assert view["system"] == {"uptime_str": "2d", "uptime_sec": 172800, "hostname": "nas"}
    assert view["remotes_event"] == {"timestamp": 5}
    text = json.dumps(view)
    for secret in ("192.0.2.10", "WD-123", "admin signed in", "is_default_password", "gdrive", "6.12"):
        assert secret not in text


def test_who_sees_everything():
    assert stats_api.sees_full_stats(AuthenticatedPrincipal(scopes=["*"]))
    assert stats_api.sees_full_stats(AuthenticatedPrincipal(scopes=["system:view"]))
    assert stats_api.sees_full_stats(AuthenticatedPrincipal(scopes=["*:read"]))
    assert stats_api.sees_full_stats(AuthenticatedPrincipal(is_system=True))
    assert not stats_api.sees_full_stats(AuthenticatedPrincipal(scopes=["shares:read", "shares:user_write"]))
    assert not stats_api.sees_full_stats(AuthenticatedPrincipal(scopes=["shares:read"]))


def test_stream_frames_are_cut_down_and_empty_ones_dropped():
    frame = f"data: {json.dumps(FULL)}\n\n"
    out = stats_api.family_payload(frame)
    assert out is not None and out.startswith("data: ")
    assert json.loads(out[6:]) == stats_api.family_view(FULL)
    assert stats_api.family_payload(frame) is out  # the same frame is only parsed once
    assert stats_api.family_payload('data: {"docker": {"running": 4}}\n\n') is None
    assert stats_api.family_payload("data: not json\n\n") is None
    assert stats_api.family_payload(": keepalive\n\n") == ": keepalive\n\n"
    assert stats_api.family_payload("data: [1]\n\n") is None


def test_a_kid_and_a_guest_get_the_reduced_stats(client, monkeypatch):
    monkeypatch.setattr(stats_api, "collect", lambda: dict(FULL))
    for name, role in (("sec33_kid", "kid"), ("sec33_guest", "guest")):
        res = client.get("/api/stats", headers=_login(client, name, role))
        assert res.status_code == 200
        body = res.json()
        assert "ip" not in body and "disks" not in body and "security" not in body
        assert body["storage"]["pct"] == 25


def test_an_adult_and_an_admin_get_everything(client, auth_headers, monkeypatch):
    monkeypatch.setattr(stats_api, "collect", lambda: dict(FULL))
    assert client.get("/api/stats", headers=auth_headers).json()["ip"] == "192.0.2.10"
    adult = _login(client, "sec33_adult", "share_user")
    assert client.get("/api/stats", headers=adult).json()["disks"] == [{"serial": "WD-123"}]


def test_the_stream_gives_a_kid_the_reduced_snapshot(monkeypatch):
    import asyncio

    from backend.services.broadcaster import StatsBroadcaster

    class _Req:
        query_params: dict = {}
        headers: dict = {}
        cookies: dict = {}

        async def is_disconnected(self):
            return False

    b = StatsBroadcaster()
    monkeypatch.setattr(stats_api, "broadcaster", b)
    monkeypatch.setattr(stats_api.Z_STATE, "cached_stats", dict(FULL))
    monkeypatch.setattr(stats_api.Z_STATE, "shutting_down", False)

    async def first_frame(principal):
        resp = await stats_api.stats_stream(_Req(), principal)
        gen = resp.body_iterator
        try:
            return await gen.__anext__()
        finally:
            await gen.aclose()

    kid = asyncio.run(first_frame(AuthenticatedPrincipal(scopes=["shares:read"])))
    assert json.loads(kid[6:]) == stats_api.family_view(FULL)
    admin = asyncio.run(first_frame(AuthenticatedPrincipal(scopes=["*"])))
    assert json.loads(admin[6:])["ip"] == "192.0.2.10"
