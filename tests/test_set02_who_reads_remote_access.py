"""SET-02: sign-in links, invite links and the devices' addresses are for people who may change
settings. Five roles that may only look used to read them."""

import pytest

from backend.users_db import create_user, get_user_by_username

TAILSCALE = {
    "installed": True,
    "auth_url": "https://login.tailscale.com/a/abc123",
    "peers_count": 2,
    "peers": [{"name": "phone", "ip": "100.64.0.2", "cur_addr": "203.0.113.9:41641"}, {"name": "laptop"}],
    "taildrop_files_count": 1,
    "taildrop_files": ["payslip.pdf"],
}


@pytest.fixture
def reader(client):
    if not get_user_by_username("ra_reader"):
        create_user("ra_reader", "Reader", "GoodPass123!", role_id="share_user")
    token = client.post("/api/auth/login", json={"username": "ra_reader", "password": "GoodPass123!"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_the_sign_in_link_is_not_for_readers(client, auth_headers, reader, monkeypatch):
    status = {"state": "NeedsLogin", "auth_url": TAILSCALE["auth_url"], "name": "", "addresses": {}}
    monkeypatch.setattr("backend.services.remote_access.status", lambda: dict(status))
    seen = client.get("/api/network/remote-access", headers=reader).json()
    assert seen["auth_url"] == "" and seen["state"] == "NeedsLogin"
    assert client.get("/api/network/remote-access", headers=auth_headers).json()["auth_url"] == TAILSCALE["auth_url"]


def test_devices_addresses_and_file_names_are_not_for_readers(client, auth_headers, reader, monkeypatch):
    monkeypatch.setattr(
        "backend.hardware.network.cached_mesh_vpn_status", lambda: {"tailscale": dict(TAILSCALE), "wireguard": {}}
    )
    seen = client.get("/api/network/mesh-vpn", headers=reader).json()["tailscale"]
    assert seen["auth_url"] == "" and seen["peers"] == [] and seen["taildrop_files"] == []
    assert seen["peers_count"] == 2 and seen["taildrop_files_count"] == 1 and seen["installed"] is True
    full = client.get("/api/network/mesh-vpn", headers=auth_headers).json()["tailscale"]
    assert full["peers"][0]["cur_addr"] == "203.0.113.9:41641" and full["taildrop_files"] == ["payslip.pdf"]


def test_family_invites_are_not_for_readers(client, auth_headers, reader, monkeypatch):
    refreshed = []
    monkeypatch.setattr("backend.services.family_access.refresh", lambda: refreshed.append(1))
    monkeypatch.setattr("backend.services.family_access.status", lambda: {"people": [{"invite_url": "https://x"}]})
    assert client.get("/api/network/family-access", headers=reader).status_code == 403
    assert refreshed == []  # a refused read starts nothing either
    assert client.get("/api/network/family-access", headers=auth_headers).json()["people"]
