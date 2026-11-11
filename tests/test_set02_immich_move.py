"""SET-02, the owner's decision S7: Immich's HTTPS address leaves the share links' port only when
someone turns share links on, after a question that shows the new address."""

import json

import pytest

from backend.hardware.net import tailscale
from backend.services import public_links as pl
from backend.services import remote_access

DNS = "family-nas.tail1234.ts.net"
HOST = f"{DNS}:{pl.FUNNEL_PORT}"
NEW = f"https://{DNS}:12283/"


class Tailnet:
    """Tailscale's serve settings: {port: {path: proxy}} and the ports Funnel publishes."""

    def __init__(self):
        self.served = {8443: {"/": "http://127.0.0.1:2283"}}
        self.public, self.calls, self.serve_fails = set(), [], False

    def links(self, args, timeout=8.0):  # public_links._ts
        self.calls.append(args)
        if args[:2] == ["status", "--json"]:
            me = {"DNSName": DNS + ".", "ID": "nTestNode1CNTRL", "CapMap": {"funnel": None}}
            return 0, json.dumps({"Self": me, "CertDomains": [DNS]})
        if args[:3] == ["funnel", "status", "--json"]:
            web = {f"{DNS}:{p}": {"Handlers": {k: {"Proxy": v} for k, v in h.items()}} for p, h in self.served.items()}
            return 0, json.dumps({"Web": web, "AllowFunnel": {f"{DNS}:{p}": True for p in self.public}})
        if args[0] == "funnel" and "--bg" in args:
            port = int(args[3].split("=")[1])
            self.served.setdefault(port, {})[args[4].split("=", 1)[1]] = args[5]
            self.public.add(port)
            return 0, ""
        return 1, "unexpected"

    def cli(self, args, timeout=10.0):  # tailscale.run_cli
        self.calls.append(args)
        port = int(next(a for a in args if a.startswith("--https=")).split("=")[1])
        if args[-1] == "off":
            self.served.pop(port, None)
            return 0, ""
        if self.serve_fails:
            return 1, "error: listener already exists"
        self.served[port] = {"/": args[-1]}
        return 0, ""


@pytest.fixture
def net(monkeypatch, tmp_path):
    fake = Tailnet()
    monkeypatch.setattr(pl, "STATE_FILE", str(tmp_path / "public_links.json"))
    monkeypatch.setattr(pl, "_ts", fake.links)
    monkeypatch.setattr(tailscale, "SETTINGS_FILE", str(tmp_path / "remote_access.json"))
    monkeypatch.setattr(tailscale, "run_cli", fake.cli)
    monkeypatch.setattr(remote_access, "immich_port", lambda: 2283)
    monkeypatch.setattr(pl, "_own_port", lambda: 8082)
    return fake


def test_immich_stands_in_the_way_and_its_new_address_is_known(net):
    assert pl.immich_to_move() == NEW
    assert pl.enable(8082)["error"] == pl.OTHERS_ON_PORT  # not without the person's yes
    assert net.served[8443] == {"/": "http://127.0.0.1:2283"} and remote_access.immich_https_port() == 8443


def test_with_a_yes_immich_moves_and_the_share_links_take_the_port(net):
    st = pl.enable(8082, move_immich=True)
    assert st["enabled"] is True and st["live"] is True and st["also_public"] == []
    assert net.served[12283] == {"/": "http://127.0.0.1:2283"}
    assert list(net.served[8443]) == [pl.PATH] and net.public == {8443}
    assert remote_access.immich_https_port() == 12283
    addresses = remote_access.addresses(DNS, ["100.64.0.1"], True, {443, 12283})
    assert addresses["immich"] == NEW
    assert pl.immich_to_move() == ""  # nothing left to move


def test_something_else_on_the_port_is_not_kibotos_to_move(net):
    net.served[8443] = {"/": "http://127.0.0.1:9000"}
    assert pl.immich_to_move() == ""
    st = pl.enable(8082, move_immich=True)
    assert st["enabled"] is False and st["error"] == pl.OTHERS_ON_PORT and 12283 not in net.served


def test_a_failed_move_publishes_nothing(net):
    net.serve_fails = True
    st = pl.enable(8082, move_immich=True)
    assert st["enabled"] is False and st["error"].startswith("Immich could not be moved") and net.public == set()


def test_no_immich_nothing_to_move(net, monkeypatch):
    monkeypatch.setattr(remote_access, "immich_port", lambda: None)
    assert pl.immich_to_move() == "" and remote_access.move_immich() is None


def test_a_waiting_request_remembers_the_yes(net, monkeypatch):
    ready = {"ready": False, "connected": True, "https": False, "funnel": False, "ports": [], "headscale": False}
    monkeypatch.setattr(pl, "funnel_readiness", lambda doc=None: dict(ready))
    assert pl.enable(8082, move_immich=True)["pending"] is True
    ready["ready"] = True
    st = pl.status(finish_pending=True)
    assert st["enabled"] is True and 12283 in net.served


@pytest.mark.real_confirmations
def test_the_question_shows_the_new_address(client, auth_headers, net):
    asked = client.put("/api/network/public-links", json={"enabled": True}, headers=auth_headers)
    assert asked.status_code == 428
    body = asked.json()
    assert body["action"] == "network.public_links_move_immich" and body["target"] == NEW
    net.served.pop(8443)  # no Immich on the port: the plain question
    plain = client.put("/api/network/public-links", json={"enabled": True}, headers=auth_headers)
    assert plain.status_code == 428 and plain.json()["action"] == "network.public_links"
