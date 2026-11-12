"""SET-16N: NetBird as a second way in (the owner's yes, 12 Nov 2026)."""

import json

import pytest

from backend.services import netbird


class FakeDocker:
    def __init__(self, exists=False, running=False):
        self.exists, self.running, self.calls = exists, running, []

    def __call__(self, method, path, body=None, headers=None):
        self.calls.append((method, path, body, headers))
        if path == "/containers/netbird/json":
            return (200, {"State": {"Running": self.running}}) if self.exists else (404, {})
        if path.startswith("/containers/create"):
            self.exists = True
            return 201, {"Id": "abc"}
        if path.endswith("/start"):
            self.running = True
            return 204, {}
        return 200, {}


STATUS = json.dumps(
    {
        "management": {"connected": True, "url": "https://api.netbird.io:443"},
        "netbirdIp": "100.92.1.5/16",
        "fqdn": "kiboto.netbird.cloud",
        "peers": {"connected": 2, "total": 3},
    }
)


@pytest.fixture
def env(monkeypatch, tmp_path):
    docker = FakeDocker()
    execs = []
    monkeypatch.setattr(netbird, "_docker", docker)
    monkeypatch.setattr(netbird, "_pull", lambda: None)
    monkeypatch.setattr(netbird, "SETTINGS_FILE", str(tmp_path / "netbird.json"))
    monkeypatch.setattr(netbird.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(netbird, "_state_dir", lambda: str(tmp_path / "nbstate"))

    def fake_exec(args):
        execs.append(args)
        if args[:1] == ["status"]:
            return 0, STATUS
        return 0, ""

    monkeypatch.setattr(netbird, "_exec", fake_exec)
    return docker, execs


def test_parse_status():
    s = netbird.parse_status("warning first\n" + STATUS)
    assert s == {
        "connected": True,
        "ip": "100.92.1.5",
        "name": "kiboto.netbird.cloud",
        "management": "https://api.netbird.io:443",
        "peers_connected": 2,
        "peers_total": 3,
    }
    assert netbird.parse_status("not json")["connected"] is False


def test_states(env):
    docker, _ = env
    assert netbird.status() == {"state": "NotInstalled"}
    docker.exists = True
    assert netbird.status() == {"state": "Stopped"}
    docker.running = True
    assert netbird.status()["state"] == "Connected"


def test_first_connect_creates_the_container_with_the_key_and_server(env):
    docker, _ = env
    s = netbird.connect("3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90", "https://netbird.example.com")
    create = next(c for c in docker.calls if c[1].startswith("/containers/create"))
    assert create[3] == {"X-Kiboto-Elevated": "1"}
    env_vars = create[2]["Env"]
    assert (
        "NB_SETUP_KEY=3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90" in env_vars
        and "NB_MANAGEMENT_URL=https://netbird.example.com" in env_vars
    )
    assert create[2]["HostConfig"]["NetworkMode"] == "host"
    assert s["state"] == "Connected" and netbird.settings() == {"management_url": "https://netbird.example.com"}


def test_a_second_connect_signs_the_existing_container_in(env):
    docker, execs = env
    docker.exists, docker.running = True, False
    netbird.connect("3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90")
    assert ["up", "--setup-key", "3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90"] in execs
    assert not any(c[1].startswith("/containers/create") for c in docker.calls)


@pytest.mark.parametrize(
    "key, url",
    [
        ("short", ""),
        ("3f2a9c1e-5b7d-4e8a; reboot", ""),
        ("3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90", "http://x"),
        ("3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90", "https://x/path"),
    ],
)
def test_bad_input_is_refused_before_anything_runs(env, key, url):
    docker, execs = env
    with pytest.raises(netbird.NetbirdError):
        netbird.connect(key, url)
    assert docker.calls == [] and execs == []


def test_failures_are_said(env, monkeypatch):
    docker, _ = env
    docker.exists, docker.running = True, True
    monkeypatch.setattr(netbird, "_exec", lambda args: (1, "invalid setup key"))
    with pytest.raises(netbird.NetbirdError, match="invalid setup key"):
        netbird.connect("3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90")
    refused = FakeDocker()

    def refused_create(m, p, body=None, headers=None):
        return (403, {"message": "denied"}) if p.startswith("/containers/create") else refused(m, p, body, headers)

    monkeypatch.setattr(netbird, "_docker", refused_create)
    with pytest.raises(netbird.NetbirdError, match="denied"):
        netbird.connect("3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90")


def test_disconnect_keeps_the_container(env):
    docker, execs = env
    docker.exists = docker.running = True
    netbird.disconnect()
    assert ["down"] in execs and not any(c[0] == "DELETE" for c in docker.calls)
    docker.running = False
    execs.clear()
    assert netbird.disconnect() == {"state": "Stopped"} and execs == []


@pytest.mark.real_confirmations
def test_routes_ask_first_and_hide_the_address_from_viewers(client, auth_headers, monkeypatch):
    monkeypatch.setattr(netbird, "container", lambda: {"exists": False, "running": False})
    monkeypatch.setattr(netbird, "connect", lambda k, u: {"state": "Connected", "ip": "100.92.1.5"})
    r = client.post(
        "/api/network/remote-access/netbird/connect",
        json={"setup_key": "3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90"},
        headers=auth_headers,
    )
    assert r.status_code == 428 and r.json()["action"] == "network.netbird_install"
    tok = client.post(
        "/api/confirmations", json={"action": "network.netbird_install", "target": "netbird"}, headers=auth_headers
    ).json()["token"]
    r = client.post(
        "/api/network/remote-access/netbird/connect",
        json={"setup_key": "3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90"},
        headers=auth_headers | {"x-confirm-token": tok},
    )
    assert r.status_code == 200 and r.json()["state"] == "Connected"


def test_routes_status_disconnect_and_errors(client, auth_headers, monkeypatch):
    monkeypatch.setattr(netbird, "status", lambda: {"state": "Connected", "ip": "100.92.1.5"})
    monkeypatch.setattr(netbird, "container", lambda: {"exists": True, "running": True})
    assert client.get("/api/network/remote-access/netbird", headers=auth_headers).json()["ip"] == "100.92.1.5"
    monkeypatch.setattr(netbird, "disconnect", lambda: {"state": "Disconnected"})
    assert (
        client.post("/api/network/remote-access/netbird/disconnect", headers=auth_headers).json()["state"]
        == "Disconnected"
    )

    def refuse(k, u):
        raise netbird.NetbirdError("Paste the setup key from NetBird")

    monkeypatch.setattr(netbird, "connect", refuse)
    r = client.post("/api/network/remote-access/netbird/connect", json={"setup_key": "x" * 30}, headers=auth_headers)
    assert r.status_code == 400 and r.json()["error"] == "netbird_failed"


def test_viewers_see_the_state_only(monkeypatch):
    import asyncio

    from backend.api import network as api

    monkeypatch.setattr(netbird, "status", lambda: {"state": "Connected", "ip": "100.92.1.5"})
    monkeypatch.setattr(api, "_may_change", lambda p: False)
    assert asyncio.run(api.get_netbird(principal=object())) == {"state": "Connected"}


def test_state_dir_follows_the_host(monkeypatch, tmp_path):
    monkeypatch.setattr(netbird.config, "DATA_DIR", str(tmp_path))
    real_isdir = netbird.os.path.isdir
    monkeypatch.setattr(netbird.os.path, "isdir", lambda p: p == "/mnt/user/appdata" or real_isdir(p))
    assert netbird._state_dir() == "/mnt/user/appdata/netbird"
    monkeypatch.setattr(netbird.os.path, "isdir", lambda p: False if p == "/mnt/user/appdata" else real_isdir(p))
    assert netbird._state_dir() == str(tmp_path / "netbird")
