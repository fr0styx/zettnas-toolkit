"""SET-02: a port that is on the internet carries the share links and nothing else.

Tailscale Funnel opens a whole port, never one path. Share links and Immich's HTTPS address used
the same port, so turning share links on could publish all of Immich, and turning them off left it
there while the card said "Off".
"""

import json

import pytest

from backend.services import public_links as pl
from backend.services import remote_access

DNS = "family-nas.tail1234.ts.net"
HOST = f"{DNS}:{pl.FUNNEL_PORT}"
IMMICH = {"/": {"Proxy": "http://127.0.0.1:2283"}}
LINKS = {pl.PATH: {"Proxy": f"http://127.0.0.1:8082{pl.PATH}"}}


class FakeTailscale:
    """The tailscale command: `web` is what the port serves, `public` whether Funnel opens it."""

    def __init__(self):
        self.web, self.public, self.calls = {}, False, []
        self.off_works, self.answers = True, True

    def __call__(self, args, timeout=8.0):
        self.calls.append(args)
        if args[:2] == ["status", "--json"]:
            me = {"DNSName": DNS + ".", "ID": "nTestNode1CNTRL", "CapMap": {"funnel": None}}
            return 0, json.dumps({"Self": me, "CertDomains": [DNS]})
        if args[:3] == ["funnel", "status", "--json"]:
            if not self.answers:
                return 1, "tailscaled is not running"
            doc = {"Web": {HOST: {"Handlers": self.web}}, "AllowFunnel": {HOST: self.public}} if self.web else {}
            return 0, json.dumps(doc)
        if args[0] == "funnel" and args[-1] == "off":
            if self.off_works:
                path = next((a.split("=", 1)[1] for a in args if a.startswith("--set-path=")), None)
                self.web = {p: h for p, h in self.web.items() if path and p != path}
                self.public = self.public and bool(self.web) and path is not None
            return 0, ""
        if args[0] == "funnel":
            self.web = {**self.web, args[4].split("=", 1)[1]: {"Proxy": args[5]}}
            self.public = True
            return 0, ""
        return 1, "unexpected"

    def published(self):
        return [a for a in self.calls if a[0] == "funnel" and "--bg" in a]


@pytest.fixture
def ts(monkeypatch, tmp_path):
    monkeypatch.setattr(pl, "STATE_FILE", str(tmp_path / "public_links.json"))
    fake = FakeTailscale()
    monkeypatch.setattr(pl, "_ts", fake)
    return fake


def test_share_links_are_refused_while_the_port_serves_something_else(ts):
    ts.web = dict(IMMICH)
    st = pl.enable(8082)
    assert st["enabled"] is False and st["error"] == pl.OTHERS_ON_PORT
    assert ts.published() == [] and ts.public is False
    ts.web = {}
    st = pl.enable(8082)
    assert st["enabled"] is True and st["live"] is True and st["also_public"] == []


def test_the_card_says_what_else_is_on_the_internet(ts):
    ts.web, ts.public = {**IMMICH, **LINKS}, True
    st = pl.status()
    assert st["port_public"] is True and st["also_public"] == ["/"]
    ts.public = False
    assert pl.status()["also_public"] == []  # served for the tailnet only: nothing to warn about


def test_off_is_said_only_once_tailscale_shows_it(ts):
    pl.enable(8082)
    ts.off_works = False
    st = pl.disable()
    assert st["enabled"] is True and st["error"] == pl.NOT_OFF and st["live"] is True
    ts.off_works = True
    st = pl.disable()
    assert st["enabled"] is False and st["error"] == "" and st["port_public"] is False


def test_off_is_not_said_when_tailscale_does_not_answer(ts):
    pl.enable(8082)
    ts.answers = False
    assert pl.disable()["enabled"] is True
    ts.answers = True
    assert pl.disable()["enabled"] is False


def test_the_whole_port_can_be_taken_off_the_internet(ts, monkeypatch):
    logged = []
    monkeypatch.setattr("backend.users_db.log_security_event", lambda *a, **k: logged.append((a[0], k.get("details"))))
    ts.web, ts.public = {**IMMICH, **LINKS}, True
    st = pl.close_port("anna")
    assert ["funnel", f"--https={pl.FUNNEL_PORT}", "off"] in ts.calls
    assert st["port_public"] is False and st["enabled"] is False and st["also_public"] == []
    assert logged == [("public_links.close_port", {"port": pl.FUNNEL_PORT})]
    ts.web, ts.public, ts.off_works = dict(IMMICH), True, False
    assert pl.close_port()["error"] == pl.NOT_OFF


def test_reading_the_card_publishes_nothing(ts, monkeypatch):
    ready = {"ready": False, "connected": True, "https": False, "funnel": False, "ports": [], "headscale": False}
    monkeypatch.setattr(pl, "funnel_readiness", lambda doc=None: dict(ready))
    assert pl.enable(8082)["pending"] is True
    ready["ready"] = True
    assert pl.status()["pending"] is True and ts.published() == []  # a reader does not finish it
    done = pl.status(finish_pending=True)  # someone who may change settings does
    assert done["enabled"] is True and len(ts.published()) == 1


def test_the_api_finishes_a_waiting_request_only_for_an_administrator(client, auth_headers, ts, monkeypatch):
    from backend.users_db import create_user, get_user_by_username

    seen = []
    monkeypatch.setattr(pl, "status", lambda finish_pending=False: seen.append(finish_pending) or {"enabled": False})
    monkeypatch.setattr(pl, "close_port", lambda actor="", port=pl.FUNNEL_PORT: {"enabled": False, "by": actor})
    if not get_user_by_username("net_reader"):
        create_user("net_reader", "Reader", "GoodPass123!", role_id="share_user")
    token = client.post("/api/auth/login", json={"username": "net_reader", "password": "GoodPass123!"}).json()["token"]
    reader = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/network/public-links", headers=reader).status_code == 200
    assert client.get("/api/network/public-links", headers=auth_headers).status_code == 200
    assert seen == [False, True]
    assert client.post("/api/network/public-links/close-port", headers=reader).status_code == 403
    assert client.post("/api/network/public-links/close-port", headers=auth_headers).json()["by"] == "admin"


def test_https_for_the_tailnet_leaves_a_public_port_alone(monkeypatch):
    served = []
    monkeypatch.setattr(remote_access, "status", lambda: {"state": "Running", "https": True})
    monkeypatch.setattr(remote_access, "immich_port", lambda: 2283)
    monkeypatch.setattr(remote_access, "web_apps", lambda: [])
    monkeypatch.setattr(remote_access, "_drop_gone_apps", lambda wanted: None)
    monkeypatch.setattr(remote_access, "_app_port", lambda: 8082)
    monkeypatch.setattr(remote_access.tailscale, "run_cli", lambda args, timeout=10.0: served.append(args) or (0, ""))
    funnel = {"AllowFunnel": {HOST: True, f"{DNS}:10000": False, "odd": True}}
    monkeypatch.setattr(remote_access, "_json", lambda args: (0, funnel))
    assert remote_access._public_ports() == {8443}
    remote_access.publish()
    ports = [next(a for a in call if a.startswith("--https=")) for call in served]
    assert ports == ["--https=443"]  # Immich is not put on the port that is on the internet
    funnel["AllowFunnel"] = {}
    served.clear()
    remote_access.publish()
    assert [next(a for a in call if a.startswith("--https=")) for call in served] == ["--https=443", "--https=8443"]
