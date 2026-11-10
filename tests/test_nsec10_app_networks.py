"""NSEC-10: an app Kiboto talks to by name gets a network of its own with Kiboto, not Kiboto's."""

import ipaddress
import json
import urllib.parse

import pytest

from backend.services import app_networks, docker_client, ip_block


class FakeDocker:
    """Docker's networks API, as much as app_networks uses."""

    def __init__(self, in_container=True):
        self.networks = {"zettnas_default": {"Labels": {}}}
        self.me = {"Id": "me123", "NetworkSettings": {"Networks": {"zettnas_default": {}}}} if in_container else None
        self.calls = []

    def __call__(self, method, path, body=None, **_):
        self.calls.append((method, path, body))
        if path.startswith("/containers/"):
            return (200, self.me) if self.me else (404, {"message": "no such container"})
        if method == "GET" and path.startswith("/networks?filters="):
            want = json.loads(urllib.parse.unquote(path.split("=", 1)[1]))["label"][0]
            return 200, [{"Name": n, "Labels": v["Labels"]} for n, v in self.networks.items() if want in v["Labels"]]
        if method == "GET" and path.startswith("/networks/"):
            name = urllib.parse.unquote(path[len("/networks/") :])
            return (200, self.networks[name]) if name in self.networks else (404, {})
        if method == "POST" and path == "/networks/create":
            self.networks[body["Name"]] = {"Labels": body["Labels"]}
            return 201, {"Id": "n1"}
        if method == "POST" and path.endswith("/connect"):
            name = urllib.parse.unquote(path[len("/networks/") : -len("/connect")])
            if body["Container"] != "me123" or name not in self.networks:
                return 404, {}
            self.me["NetworkSettings"]["Networks"][name] = {}
            return 200, None
        return 500, {}


@pytest.fixture
def docker(monkeypatch):
    fake = FakeDocker()
    monkeypatch.setattr(docker_client, "request", fake)
    return fake


def test_the_name_is_safe_for_docker():
    assert app_networks.network_name("office-suite") == "zettnas-app-office-suite"
    assert app_networks.network_name("My App/2") == "zettnas-app-my-app-2"
    assert app_networks.network_name("") == "zettnas-app-app"
    assert len(app_networks.network_name("x" * 200)) == len("zettnas-app-") + 40


def test_an_app_gets_its_own_network_with_zettnas_on_it(docker):
    assert app_networks.private_network("frigate") == "zettnas-app-frigate"
    assert docker.networks["zettnas-app-frigate"]["Labels"] == {
        "com.zettnas.managed": "1",
        "com.zettnas.app": "frigate",
    }
    assert "zettnas-app-frigate" in docker.me["NetworkSettings"]["Networks"]
    creates = [c for c in docker.calls if c[1] == "/networks/create"]
    assert app_networks.private_network("frigate") == "zettnas-app-frigate"  # the second install reuses it
    assert [c for c in docker.calls if c[1] == "/networks/create"] == creates


def test_outside_a_container_or_without_docker_there_is_none(monkeypatch):
    monkeypatch.setattr(docker_client, "request", FakeDocker(in_container=False))
    assert app_networks.private_network("frigate") is None
    assert app_networks.rejoin() == 0

    def gone(*a, **k):
        raise docker_client.DockerUnavailable(0, "no socket", "/")

    monkeypatch.setattr(docker_client, "request", gone)
    assert app_networks.private_network("frigate") is None
    assert app_networks.rejoin() == 0


def test_a_refused_network_installs_on_the_default(docker, monkeypatch):
    real = docker.__call__

    def refuse_create(method, path, body=None, **k):
        return (500, {}) if path == "/networks/create" else real(method, path, body)

    monkeypatch.setattr(docker_client, "request", refuse_create)
    assert app_networks.private_network("adguardhome") is None


def test_zettnas_rejoins_its_app_networks_after_an_update(docker):
    app_networks.private_network("frigate")
    app_networks.private_network("office-suite")
    docker.me["NetworkSettings"]["Networks"] = {"zettnas_default": {}}  # recreated by an update
    assert app_networks.rejoin() == 2
    assert set(docker.me["NetworkSettings"]["Networks"]) == {
        "zettnas_default",
        "zettnas-app-frigate",
        "zettnas-app-office-suite",
    }
    assert app_networks.rejoin() == 0


def test_sign_ins_relayed_from_any_shared_network_are_not_blocked(monkeypatch):
    me = {
        "NetworkSettings": {
            "Networks": {
                "bridge": {"IPAddress": "172.17.0.2", "IPPrefixLen": 16},
                "zettnas_default": {"IPAddress": "172.20.0.3", "IPPrefixLen": 16},
                "zettnas-app-office-suite": {"IPAddress": "172.23.0.2", "IPPrefixLen": 16},
            }
        }
    }
    monkeypatch.setattr(ip_block, "_app_net", {"at": -1e9, "net": ()})
    monkeypatch.setattr(docker_client, "request", lambda m, p, **k: (200, me))
    assert ip_block._app_networks() == (ipaddress.ip_network("172.20.0.0/16"), ipaddress.ip_network("172.23.0.0/16"))
    assert ip_block._relay("172.23.0.9") is True
    assert ip_block._relay("172.17.0.9") is False  # the default bridge is not a shared app network
    assert ip_block._relay("not an address") is False
