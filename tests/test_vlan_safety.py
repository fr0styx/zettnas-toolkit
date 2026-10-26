"""VLAN sub-interfaces: created with names Linux accepts, and deleting removes only VLANs
(ip link del would just as well remove br0 or bond0 and cut the NAS off the network)."""

import subprocess

import pytest

from backend.hardware import network as net


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(net.common, "NETWORK_CONFIG_FILE", str(tmp_path / "network_config.json"))
    ran = []
    kernel = {}

    def run(cmd, **kw):
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(net.subprocess, "run", run)
    monkeypatch.setattr(net.vlans, "_parse_proc_net_vlan", lambda: dict(kernel))
    monkeypatch.setattr(
        net.os.path, "exists", lambda p: False if p == "/host/proc/1/ns/net" else __import__("os").path.lexists(p)
    )
    return ran, kernel


@pytest.mark.parametrize("name", ["br0", "bond0", "docker0", "eth0", "wg0", "-x.10", "a" * 14 + ".10"])
def test_delete_refuses_anything_but_a_vlan(env, name):
    ran, kernel = env
    kernel["br0"] = {"vlan_id": 0, "parent": "x"}  # even a name the parser lists, if it has no VLAN tag
    assert net.delete_vlan(name)["status"] == "error"
    assert ran == []


def test_delete_an_unknown_tagged_name_is_refused(env):
    ran, _ = env
    res = net.delete_vlan("eth0.99")
    assert res["status"] == "error" and "not a VLAN" in res["message"] and ran == []


def test_create_then_delete(env):
    ran, kernel = env
    res = net.create_vlan("eth0", 20, "cameras")
    assert res["status"] == "ok" and res["applied_runtime"] is True
    assert ran[0] == ["ip", "link", "add", "link", "eth0", "name", "eth0.20", "type", "vlan", "id", "20"]
    assert net.load_network_config()["vlans"]["eth0.20"]["alias"] == "cameras"
    kernel["eth0.20"] = {"vlan_id": 20, "parent": "eth0"}
    ran.clear()
    assert net.delete_vlan("eth0.20")["status"] == "ok"
    assert ran == [["ip", "link", "del", "dev", "eth0.20"]]
    assert "eth0.20" not in net.load_network_config().get("vlans", {})


def test_a_saved_vlan_missing_from_the_kernel_only_leaves_the_settings(env):
    ran, _ = env
    net.save_network_config({"vlans": {"eth1.30": {"name": "eth1.30"}}, "aliases": {"eth1.30": "iot"}})
    assert net.delete_vlan("eth1.30")["status"] == "ok"
    assert ran == [] and net.load_network_config()["vlans"] == {} and net.load_network_config()["aliases"] == {}


def test_a_failed_delete_is_reported(env, monkeypatch):
    ran, kernel = env
    kernel["eth0.40"] = {"vlan_id": 40, "parent": "eth0"}
    net.save_network_config({"vlans": {"eth0.40": {}}})
    monkeypatch.setattr(
        net.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "", "RTNETLINK answers: busy")
    )
    res = net.delete_vlan("eth0.40")
    assert res["status"] == "error" and "busy" in res["message"]
    assert "eth0.40" in net.load_network_config()["vlans"]  # kept, since it still exists


@pytest.mark.parametrize(
    ("parent", "vid"), [("enp0s31f6long", 100), ("-bad", 10), ("eth0", 0), ("eth0", 4095), ("eth0", "x")]
)
def test_create_refuses_names_linux_would_not_take(env, parent, vid):
    ran, _ = env
    assert net.create_vlan(parent, vid)["status"] == "error" and ran == []


def test_delete_route_reports_errors(client, auth_headers, env):
    r = client.delete("/api/network/vlan/br0", headers=auth_headers)
    assert r.status_code == 400
