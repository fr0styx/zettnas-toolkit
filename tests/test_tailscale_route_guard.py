"""Tailscale never accepts a route over the NAS's own network: another node offering 192.168.50.0/24
while the NAS sits on 192.168.50.0/24 sent its home traffic into the tailnet, and it dropped off."""

import json

import pytest

from backend.hardware.net import tailscale

DOC = {
    "Peer": {
        "a": {"HostName": "router", "PrimaryRoutes": ["192.168.50.0/24"]},
        "b": {"HostName": "cabin", "PrimaryRoutes": ["192.168.8.0/24"]},
        "c": {"HostName": "exit", "PrimaryRoutes": ["0.0.0.0/0"]},
        "d": {"DNSName": "wide.tailnet.ts.net.", "PrimaryRoutes": ["192.168.0.0/16", "fd00::/8", "nonsense"]},
        "e": {"HostName": "quiet"},
    }
}


@pytest.fixture
def lan(monkeypatch):
    monkeypatch.setattr(tailscale, "detect_local_subnets", lambda fallback=True: ["192.168.50.0/24", "bad"])


def test_routes_over_the_own_network_are_found(lan):
    found = tailscale.lan_route_conflicts(DOC)
    assert found == [
        {"peer": "router", "route": "192.168.50.0/24", "lan": "192.168.50.0/24"},
        {"peer": "wide.tailnet.ts.net", "route": "192.168.0.0/16", "lan": "192.168.50.0/24"},
    ]
    assert tailscale.lan_route_conflicts({"Peer": {"b": DOC["Peer"]["b"]}}) == []


def test_accepting_is_turned_off_and_said(lan, monkeypatch):
    calls, events = [], []
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda args, timeout=10.0: (calls.append(args), (0, ""))[1])
    import backend.state as state

    monkeypatch.setattr(state, "add_event", lambda *a, **k: events.append(a))
    found = tailscale.guard_lan_routes(DOC, route_all=True)
    assert len(found) == 2
    assert calls == [["set", "--accept-routes=false"]]
    assert events and "router offers 192.168.50.0/24" in events[0][2]


def test_nothing_happens_when_accepting_is_off_or_nothing_overlaps(lan, monkeypatch):
    calls = []

    def fake(args, timeout=10.0):
        calls.append(args)
        if args == ["status", "--json"]:
            return 0, json.dumps(DOC)
        if args == ["debug", "prefs"]:
            return 0, json.dumps({"RouteAll": False})
        return 0, ""

    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", fake)
    assert len(tailscale.guard_lan_routes()) == 2  # reports, but accepting is already off
    assert ["set", "--accept-routes=false"] not in calls
    calls.clear()
    assert tailscale.guard_lan_routes({"Peer": {}}, route_all=True) == []
    assert calls == []


def test_a_broken_status_is_no_conflict(lan, monkeypatch):
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda args, timeout=10.0: (1, "not running"))
    assert tailscale.guard_lan_routes() == []
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda args, timeout=10.0: (0, "{not json"))
    assert tailscale.guard_lan_routes() == []


def test_without_fallback_no_subnet_is_guessed(monkeypatch):
    from backend.hardware.net import common

    monkeypatch.setattr(common, "_parse_routes", lambda: [])
    assert tailscale.detect_local_subnets() == ["192.168.1.0/24"]
    assert tailscale.detect_local_subnets(fallback=False) == []


def test_connecting_never_accepts_routes(monkeypatch):
    """Accept routes is no longer an option (D5): a route over the NAS's own network could cut it off."""
    from backend.hardware.net import tailscale_setup

    calls = []
    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {"exists": False})
    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", lambda args, timeout=10.0: (calls.append(args), (0, ""))[1])
    tailscale_setup.execute_tailscale_up(auth_key="tskey-test")
    assert "--accept-routes" not in calls[0]
    with pytest.raises(TypeError):
        tailscale_setup.execute_tailscale_up(auth_key="tskey-test", accept_routes=True)
