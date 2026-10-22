"""M2: turning on Tailscale Serve returns the https address to open on a phone."""

import json

from backend.hardware import network


def test_serve_returns_the_tailnet_address(monkeypatch):
    def fake(args, timeout=3.0):
        if args[:2] == ["serve", "--bg"]:
            return 0, "Available within your tailnet"
        if args[:3] == ["serve", "status", "--json"]:
            return 0, json.dumps({"TCP": {"443": {"HTTPS": True}}})
        if args[:2] == ["status", "--json"]:
            return 0, json.dumps({"Self": {"DNSName": "ark.tail1234.ts.net."}})
        return 0, ""

    monkeypatch.setattr(network, "_run_tailscale_cmd", fake)
    res = network.execute_tailscale_set_serve(serve=True)
    assert res["status"] == "ok" and res["serve_url"] == "https://ark.tail1234.ts.net"


def test_serve_approval_is_passed_through(monkeypatch):
    monkeypatch.setattr(
        network,
        "_run_tailscale_cmd",
        lambda args, timeout=3.0: (
            (1, "Serve is not enabled. https://login.tailscale.com/f/serve?node=abc")
            if args[:2] == ["serve", "--bg"]
            else (1, "")
        ),
    )
    res = network.execute_tailscale_set_serve(serve=True)
    assert res["status"] == "needs_approval" and res["approval_url"].startswith("https://login.tailscale.com/f/serve")
    assert res["serve_url"] == ""
