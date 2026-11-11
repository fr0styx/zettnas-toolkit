"""SET-02: an app that is removed, or no longer publishes its port, leaves the internet.

The public address belonged to a host port. After the app was gone, the next app on that port was
public without anyone choosing it.
"""

import json

import pytest

from backend.services import public_apps as pa
from backend.services import public_links

DNS = "attic.example-tailnet.ts.net"


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = {
        "containers": [
            {
                "Names": ["/jellyfin"],
                "State": "running",
                "Ports": [{"Type": "tcp", "PublicPort": 8096, "IP": "0.0.0.0"}],
            }
        ],
        "calls": [],
        "audit": [],
        "allow": {},
    }

    def ts(args, timeout=8.0):
        w["calls"].append(args)
        if args[:2] == ["status", "--json"]:
            me = {"DNSName": DNS + ".", "ID": "nTestNode1CNTRL", "CapMap": {"funnel": None}}
            return 0, json.dumps({"Self": me, "CertDomains": [DNS]})
        if args[:3] == ["funnel", "status", "--json"]:
            return 0, json.dumps({"Web": {h: {"Handlers": {"/": {}}} for h in w["allow"]}, "AllowFunnel": w["allow"]})
        if args[0] == "funnel" and args[-1].startswith("http://"):
            w["allow"][f"{DNS}:{args[3].split('=')[1]}"] = True
            return 0, ""
        if args[0] == "funnel" and args[-1] == "off":
            w["allow"].pop(f"{DNS}:{args[1].split('=')[1]}", None)
            return 0, ""
        return 1, "unexpected"

    monkeypatch.setattr(public_links, "_ts", ts)
    monkeypatch.setattr(pa, "_docker", lambda path: w["containers"])
    monkeypatch.setattr(pa, "_own_port", lambda: 8082)
    monkeypatch.setattr(pa, "STATE_FILE", str(tmp_path / "public_apps.json"))
    monkeypatch.setattr(pa, "PENDING_FILE", str(tmp_path / "public_apps_pending.json"))
    monkeypatch.setattr(pa, "_audit", lambda *a: w["audit"].append(a[0]))
    pa._MISSING.clear()
    pa.publish("jellyfin", 8096, 10000, actor="ann")
    return w


def _public(w):
    return f"{DNS}:10000" in w["allow"]


def test_a_removed_app_leaves_the_internet_at_the_second_look(world):
    assert pa.withdraw_gone() == [] and _public(world)
    world["containers"] = []
    assert pa.withdraw_gone() == [] and _public(world)  # missing once: it may be an update
    assert pa.withdraw_gone() == ["jellyfin"]
    assert not _public(world) and pa.status()["published"] == []
    assert "public_app.withdrawn" in world["audit"]
    assert pa.withdraw_gone() == []  # nothing published: nothing to do


def test_an_app_recreated_by_an_update_keeps_its_address(world):
    there = world["containers"]
    world["containers"] = []
    assert pa.withdraw_gone() == []
    world["containers"] = there
    assert pa.withdraw_gone() == [] and pa.withdraw_gone() == []
    assert _public(world)


def test_a_changed_port_is_withdrawn_and_a_stopped_app_is_not(world):
    world["containers"][0]["State"] = "exited"
    world["containers"][0]["Ports"] = []
    assert pa.withdraw_gone() == [] and pa.withdraw_gone() == []
    assert _public(world)  # stopped: it keeps its address
    world["containers"][0]["State"] = "running"
    world["containers"][0]["Ports"] = [{"Type": "tcp", "PublicPort": 9000, "IP": "0.0.0.0"}]
    pa.withdraw_gone()
    assert pa.withdraw_gone() == ["jellyfin"] and not _public(world)


def test_no_answer_from_docker_decides_nothing(world, monkeypatch):
    monkeypatch.setattr(pa, "_docker", lambda path: None)
    assert pa.withdraw_gone() == [] and pa.withdraw_gone() == []
    assert _public(world)


def test_reading_the_card_publishes_no_waiting_app(world, monkeypatch):
    ready = {"ready": False, "connected": True, "https": False, "funnel": False, "ports": [], "headscale": False}
    monkeypatch.setattr(public_links, "funnel_readiness", lambda doc=None: dict(ready))
    pa.unpublish(10000)
    assert pa.publish("jellyfin", 8096, 10000, "ann")["pending"] == {"name": "jellyfin", "funnel_port": 10000}
    ready["ready"] = True
    assert pa.status()["published"] == [] and not _public(world)  # a reader does not finish it
    assert [p["name"] for p in pa.status(finish_pending=True)["published"]] == ["jellyfin"]


def test_the_watcher_looks_once_a_minute(monkeypatch):
    import threading

    from backend.services import protection_jobs

    looked = []
    stop = threading.Event()
    monkeypatch.setattr(pa, "withdraw_gone", lambda: looked.append(1) or stop.set() or [])
    monkeypatch.setattr("backend.services.backup_watch.check_and_alert", lambda now: None)
    monkeypatch.setattr(protection_jobs, "check_and_alert", lambda now: None)
    monkeypatch.setattr(protection_jobs, "alert_stalled", lambda now: None)
    protection_jobs.watch_daemon(stop, tick=0.01)
    assert looked == [1]
