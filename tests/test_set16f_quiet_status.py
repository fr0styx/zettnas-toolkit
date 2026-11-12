"""SET-16 stage 2: the Tailscale status read changes nothing and is cached; the route check runs in
the scheduler; opening the Network pages ten times touches no share (a sleeping drive stays asleep)."""

import builtins
import json
import os

import pytest

from backend.hardware.net import mesh, tailscale
from backend.services import scheduler

DOC = {
    "BackendState": "Running",
    "Self": {"HostName": "kiboto", "TailscaleIPs": ["100.64.0.2"], "DNSName": "kiboto.tail.ts.net."},
    "Peer": {"a": {"HostName": "router", "PrimaryRoutes": ["192.168.50.0/24"], "TailscaleIPs": ["100.64.0.3"]}},
}


@pytest.fixture
def ts(monkeypatch):
    calls = []

    def fake(args, timeout=10.0):
        calls.append(list(args))
        if args == ["status", "--json"]:
            return 0, json.dumps(DOC)
        if args == ["debug", "prefs"]:
            return 0, json.dumps({"RouteAll": True, "AdvertiseRoutes": []})
        return 0, ""

    monkeypatch.setattr(tailscale, "_run_tailscale_cmd", fake)
    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {"exists": True, "running": True})
    monkeypatch.setattr(tailscale, "detect_local_subnets", lambda fallback=True: ["192.168.50.0/24"])
    mesh.forget_cached_status()
    yield calls
    mesh.forget_cached_status()


def test_the_status_read_reports_a_conflict_but_changes_nothing(ts):
    doc = mesh.get_mesh_vpn_status()["tailscale"]
    assert doc["route_conflicts"] == [{"peer": "router", "route": "192.168.50.0/24", "lan": "192.168.50.0/24"}]
    assert doc["accept_routes"] is True  # what Tailscale says, not what a check made of it
    assert not [c for c in ts if c[0] == "set"]


def test_the_cached_read_asks_once_until_something_changes(ts, monkeypatch):
    first = mesh.cached_mesh_vpn_status()
    first["tailscale"]["hostname"] = "edited by a caller"
    second = mesh.cached_mesh_vpn_status()
    assert second["tailscale"]["hostname"] == "kiboto"  # each caller gets its own copy
    assert ts.count(["status", "--json"]) == 1
    tailscale.changed()
    mesh.cached_mesh_vpn_status()
    assert ts.count(["status", "--json"]) == 2
    clock = [1000.0]
    monkeypatch.setattr(mesh.time, "monotonic", lambda: clock[0])
    mesh.forget_cached_status()
    mesh.cached_mesh_vpn_status()
    clock[0] += mesh.CACHE_S + 1
    mesh.cached_mesh_vpn_status()
    assert ts.count(["status", "--json"]) == 4


@pytest.mark.parametrize(
    ("args", "changes"),
    [
        (["status", "--json"], False),
        (["debug", "prefs"], False),
        (["serve", "status", "--json"], False),
        (["set", "--advertise-exit-node=true"], True),
        (["serve", "--bg", "443"], True),
        (["up", "--reset"], True),
    ],
)
def test_commands_that_may_change_tailscale_are_noted(monkeypatch, args, changes):
    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {})
    monkeypatch.setattr(tailscale, "_find_tailscale_bin", lambda: None)

    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(tailscale.subprocess, "run", missing)
    before = tailscale.changes()
    tailscale._run_tailscale_cmd(args)
    assert (tailscale.changes() > before) is changes


def test_the_route_check_asks_nothing_without_a_running_tailscale(monkeypatch):
    ran = []
    monkeypatch.setattr(tailscale, "guard_lan_routes", lambda *a, **k: ran.append(1) or [{"peer": "x"}])
    monkeypatch.setattr(tailscale, "_find_tailscale_bin", lambda: None)
    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {})
    assert tailscale.guard_routes_now() == []
    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {"exists": True, "running": False})
    assert tailscale.guard_routes_now() == []
    assert ran == []
    monkeypatch.setattr(tailscale, "_get_tailscale_container_info", lambda: {"exists": True, "running": True})
    assert tailscale.guard_routes_now() == [{"peer": "x"}]


def test_the_scheduler_checks_routes_every_ten_minutes(monkeypatch):
    started = []
    monkeypatch.setattr(scheduler, "on_its_own", lambda name, fn, *a: started.append(name) or True)
    monkeypatch.setitem(scheduler._LAST_ROUTE_CHECK, "at", 0.0)
    scheduler._run_route_check(10_000.0)
    scheduler._run_route_check(10_000.0 + scheduler.ROUTE_CHECK_S - 1)
    scheduler._run_route_check(10_000.0 + scheduler.ROUTE_CHECK_S)
    assert started == ["Tailscale routes", "Tailscale routes"]


def test_a_failed_route_check_is_logged_not_raised(monkeypatch):
    def broken():
        raise OSError("docker is gone")

    monkeypatch.setattr(tailscale, "guard_routes_now", broken)
    scheduler._check_tailscale_routes()  # no exception
    ran = []
    monkeypatch.setattr(tailscale, "guard_routes_now", lambda: ran.append(1) or [])
    scheduler._check_tailscale_routes()
    assert ran == [1]


SHARES = ("/mnt/user", "/mnt/disk", "/mnt/user0")


def test_opening_the_network_pages_ten_times_touches_no_share(client, auth_headers, monkeypatch):
    """The gate of stage 2: a sleeping drive stays asleep while the page is opened ten times."""
    touched = []

    def watch(fn):
        def wrapped(path, *a, **k):
            p = os.fspath(path) if isinstance(path, (str, bytes, os.PathLike)) else ""
            if isinstance(p, bytes):
                p = p.decode("utf-8", "replace")
            if p.startswith(SHARES):
                touched.append((fn.__name__, p))
            return fn(path, *a, **k)

        wrapped.__name__ = fn.__name__
        return wrapped

    for mod, name in ((os, "listdir"), (os, "scandir"), (os, "makedirs"), (os, "stat"), (builtins, "open")):
        monkeypatch.setattr(mod, name, watch(getattr(mod, name)))
    mesh.forget_cached_status()
    for _ in range(10):
        for path in (
            "/api/system/network-topology",
            "/api/network/capabilities",
            "/api/network/mesh-vpn",
            "/api/network/remote-access",
            "/api/network/remote-access/netbird",
        ):
            r = client.get(path, headers=auth_headers)
            assert r.status_code == 200, (path, r.text[:200])
    assert touched == []
