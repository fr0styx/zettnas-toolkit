"""Funnel needs two switches only the tailnet's owner can turn on; Kiboto reads them from Tailscale's
status, links to both, and finishes a request made before they were on."""

import json

import pytest

from backend.services import public_apps as pa
from backend.services import public_links as pl

DNS = "attic.example-tailnet.ts.net"


def doc(https=True, funnel=True, ports="443,8443,10000"):
    caps = {}
    if funnel:
        caps = {"funnel": None, f"https://tailscale.com/cap/funnel-ports?ports={ports}": None}
    return {
        "Self": {"DNSName": DNS + ".", "ID": "nTestNode1CNTRL", "CapMap": caps},
        "CertDomains": [DNS] if https else [],
    }


@pytest.fixture
def tailnet(tmp_path, monkeypatch):
    state = {"doc": doc(https=False, funnel=False), "calls": []}

    def fake(args, timeout=8.0):
        state["calls"].append(args)
        if args[:2] == ["status", "--json"]:
            return 0, json.dumps(state["doc"])
        if args[:3] == ["funnel", "status", "--json"]:
            return 0, json.dumps({"Web": state.get("web", {}), "AllowFunnel": state.get("allow", {})})
        if args and args[0] == "funnel" and args[-1].startswith("http://"):
            port = [a for a in args if a.startswith("--https=")][0].split("=")[1]
            state.setdefault("web", {})[f"{DNS}:{port}"] = {"Handlers": {"/": {}}}
            state.setdefault("allow", {})[f"{DNS}:{port}"] = True
            return 0, ""
        return 0, ""

    monkeypatch.setattr(pl, "_ts", fake)
    monkeypatch.setattr(pl, "STATE_FILE", str(tmp_path / "public_links.json"))
    monkeypatch.setattr(pa, "STATE_FILE", str(tmp_path / "public_apps.json"))
    monkeypatch.setattr(pa, "PENDING_FILE", str(tmp_path / "public_apps_pending.json"))
    monkeypatch.setattr(pa, "_audit", lambda *a: state["calls"].append(["audit", *a]))
    monkeypatch.setattr(pa, "_own_port", lambda: 8082)
    monkeypatch.setattr(
        pa,
        "_docker",
        lambda path: [
            {
                "Names": ["/jellyfin"],
                "Image": "jellyfin/jellyfin",
                "Ports": [{"Type": "tcp", "PublicPort": 8096, "IP": "0.0.0.0"}],
            }
        ],
    )
    from backend.hardware.net import tailscale

    monkeypatch.setattr(tailscale, "login_server", lambda: "")
    return state


def test_readiness_names_each_step_and_its_link(tailnet):
    r = pl.funnel_readiness()
    assert r["connected"] and not r["https"] and not r["funnel"] and not r["ready"]
    assert r["approve_url"] == "https://login.tailscale.com/f/funnel?node=nTestNode1CNTRL"
    assert r["dns_url"] == "https://login.tailscale.com/admin/dns"
    tailnet["doc"] = doc(https=True, funnel=False)
    assert pl.funnel_readiness()["https"] and not pl.funnel_readiness()["ready"]
    tailnet["doc"] = doc(ports="443,10000")
    r = pl.funnel_readiness()
    assert r["ready"] and r["ports"] == [443, 10000]
    tailnet["doc"]["Self"]["ID"] = "bad id!"
    assert pl.funnel_readiness()["approve_url"] == ""


def test_headscale_has_no_funnel(tailnet, monkeypatch):
    from backend.hardware.net import tailscale

    tailnet["doc"] = doc()
    monkeypatch.setattr(tailscale, "login_server", lambda: "https://hs.example.com")
    r = pl.funnel_readiness()
    assert r["headscale"] and not r["ready"]


def test_an_app_asked_for_early_is_published_once_both_steps_are_done(tailnet):
    st = pa.publish("jellyfin", 8096, 10000, actor="ann")
    assert st["pending"] == {"name": "jellyfin", "funnel_port": 10000} and st["published"] == []
    assert not any(
        c[0] == "funnel" and c[-1].startswith("http://") for c in tailnet["calls"]
    )  # nothing waits on Tailscale
    assert st["funnel"]["approve_url"].endswith("nTestNode1CNTRL")
    tailnet["doc"] = doc()  # the owner clicked both
    assert pa.status()["published"] == []  # reading the card publishes nothing (SET-02)
    st = pa.status(finish_pending=True)
    assert st["pending"] is None and [p["name"] for p in st["published"]] == ["jellyfin"]


def test_a_waiting_request_can_be_withdrawn_and_expires(tailnet, monkeypatch):
    pa.publish("jellyfin", 8096, 10000)
    assert pa.unpublish(10000)["pending"] is None
    pa.publish("jellyfin", 8096, 10000)
    monkeypatch.setattr(pl, "PENDING_SECONDS", -1)
    assert pa.status()["pending"] is None


def test_only_ports_funnel_allows_are_offered(tailnet):
    tailnet["doc"] = doc(ports="443,8443")
    assert pa.status()["free_ports"] == [443]


def test_share_links_asked_for_early_go_public_once_both_are_done(tailnet):
    st = pl.enable(8082)
    assert st["pending"] is True and st["enabled"] is False
    tailnet["doc"] = doc()
    assert pl.status()["enabled"] is False  # reading the card publishes nothing (SET-02)
    st = pl.status(finish_pending=True)
    assert st["enabled"] is True and st["pending"] is False
