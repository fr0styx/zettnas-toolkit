"""SET-02: Kiboto's own page is never put on the internet.

An older switch on the Network page ran `tailscale funnel` for Kiboto's own port, with no question
on the server and no log entry, and its "off" wiped the share links and the published apps with
`funnel reset`. The route refuses it now; a NAS where it is still on gets an alert and a way out.
"""

import json

import pytest

from backend.hardware.net import tailscale
from backend.services import public_links as pl

DNS = "family-nas.tail1234.ts.net"


def test_the_route_refuses_to_publish_kibotos_own_page(client, auth_headers, monkeypatch):
    ran = []
    monkeypatch.setattr("backend.hardware.network.execute_tailscale_set_serve", lambda **kw: ran.append(kw) or {})
    res = client.post(
        "/api/network/mesh-vpn/tailscale/set-serve",
        json={"serve": True, "funnel": True, "port": 8082},
        headers=auth_headers,
    )
    assert res.status_code == 400 and "never put on the internet" in res.text
    assert ran == []
    ok = client.post(
        "/api/network/mesh-vpn/tailscale/set-serve", json={"serve": True, "port": 8082}, headers=auth_headers
    )
    assert ok.status_code == 200 and ran == [{"serve": True, "funnel": False, "port": 8082}]


def test_the_switch_neither_publishes_nor_resets_funnel(monkeypatch):
    calls = []

    def fake(args, timeout=3.0):
        calls.append(args)
        return (0, "{}") if args[-1] == "--json" else (0, "")

    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", fake)
    tailscale.execute_tailscale_set_serve(serve=True, funnel=True, port=8082)
    tailscale.execute_tailscale_set_serve(serve=True, funnel=False, port=8082)
    changing = [c for c in calls if c[0] == "funnel" and "status" not in c]
    assert changing == []  # no "funnel --bg" and no "funnel reset"
    assert ["serve", "--bg", "--yes", "8082"] in calls


class FakeFunnel:
    def __init__(self, doc):
        self.doc, self.calls = doc, []

    def __call__(self, args, timeout=8.0):
        self.calls.append(args)
        if args[:2] == ["status", "--json"]:
            return 0, json.dumps({"Self": {"DNSName": DNS + ".", "ID": "nTestNode1CNTRL", "CapMap": {}}})
        if args[:3] == ["funnel", "status", "--json"]:
            return 0, json.dumps(self.doc)
        if args[0] == "funnel" and args[-1] == "off":
            port = next(a for a in args if a.startswith("--https=")).split("=")[1]
            self.doc["AllowFunnel"].pop(f"{DNS}:{port}", None)
            return 0, ""
        return 1, "unexpected"


@pytest.fixture
def funnel(monkeypatch, tmp_path):
    monkeypatch.setattr(pl, "STATE_FILE", str(tmp_path / "public_links.json"))
    monkeypatch.setattr("backend.services.public_apps._own_port", lambda: 8082)
    fake = FakeFunnel(
        {
            "Web": {
                f"{DNS}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8082"}}},
                f"{DNS}:8443": {"Handlers": {pl.PATH: {"Proxy": f"http://127.0.0.1:8082{pl.PATH}"}}},
                f"{DNS}:10000": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8096"}}},
            },
            "AllowFunnel": {f"{DNS}:443": True, f"{DNS}:8443": True, f"{DNS}:10000": True},
        }
    )
    monkeypatch.setattr(pl, "_ts", fake)
    return fake


def test_a_published_own_page_is_found(funnel):
    # the share links' path and an app chosen for the internet are not Kiboto's own page
    assert pl.own_page_ports(DNS) == [443]
    assert pl.status()["own_page_public"] == [443]
    funnel.doc["AllowFunnel"][f"{DNS}:443"] = False  # served in the tailnet only: fine
    assert pl.own_page_ports(DNS) == []
    assert pl.own_page_ports("") == []


def test_only_such_a_port_can_be_taken_off(funnel):
    with pytest.raises(ValueError):
        pl.close_port("anna", 10000)  # an app's port has its own card
    st = pl.close_port("anna", 443)
    assert ["funnel", "--https=443", "off"] in funnel.calls
    assert st["own_page_public"] == []
    assert st["port_public"] is True  # the share links were not touched


def test_the_api_names_the_port(client, auth_headers, funnel):
    refused = client.post("/api/network/public-links/close-port", json={"port": 10000}, headers=auth_headers)
    assert refused.status_code == 400
    done = client.post("/api/network/public-links/close-port", json={"port": 443}, headers=auth_headers)
    assert done.status_code == 200 and done.json()["own_page_public"] == []
