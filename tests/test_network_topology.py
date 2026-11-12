import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.hardware.network import (
    _format_speed,
    _hex_to_ip,
    _mask_to_cidr,
    create_docker_network,
    delete_docker_network,
    get_bond_config,
    get_bridge_config,
    get_host_ip_config,
    get_network_topology,
    get_port_config,
    get_vlans,
    load_network_config,
    save_network_config,
)
from backend.main import app


def test_format_speed():
    assert _format_speed(10000, is_up=True) == "10 Gbps"
    assert _format_speed(2500, is_up=True) == "2.5 Gbps"
    assert _format_speed(1000, is_up=True) == "1 Gbps"
    assert _format_speed(100, is_up=True) == "100 Mbps"
    assert _format_speed(10, is_up=True) == "10 Mbps"
    assert _format_speed(0, is_up=False) == "Disconnected"
    assert _format_speed(-1, is_up=False) == "Disconnected"
    assert _format_speed(1000, is_up=False) == "Disconnected"
    assert _format_speed(None, is_up=True) == "Unknown"


def test_hex_to_ip():
    assert _hex_to_ip("0101A8C0") == "192.168.1.1"
    assert _hex_to_ip("00000000") == "0.0.0.0"
    assert _hex_to_ip("000011AC") == "172.17.0.0"
    assert _hex_to_ip("invalid_hex") == "invalid_hex"


def test_mask_to_cidr():
    assert _mask_to_cidr("255.255.255.0") == 24
    assert _mask_to_cidr("255.255.0.0") == 16
    assert _mask_to_cidr("255.0.0.0") == 8
    assert _mask_to_cidr("0.0.0.0") == 0


def test_get_network_topology_mocked(tmp_path):
    sys_net = tmp_path / "sys_net"
    sys_net.mkdir()

    # eth0 (Physical up 2.5G)
    eth0 = sys_net / "eth0"
    eth0.mkdir()
    (eth0 / "operstate").write_text("up\n")
    (eth0 / "carrier").write_text("1\n")
    (eth0 / "speed").write_text("2500\n")
    (eth0 / "duplex").write_text("full\n")
    (eth0 / "mtu").write_text("1500\n")
    (eth0 / "address").write_text("aa:bb:cc:dd:ee:01\n")
    stats0 = eth0 / "statistics"
    stats0.mkdir()
    (stats0 / "rx_bytes").write_text("1000000\n")
    (stats0 / "tx_bytes").write_text("500000\n")
    (stats0 / "rx_packets").write_text("1000\n")
    (stats0 / "tx_packets").write_text("500\n")
    (stats0 / "rx_errors").write_text("0\n")
    (stats0 / "tx_errors").write_text("0\n")
    (stats0 / "rx_dropped").write_text("0\n")
    (stats0 / "tx_dropped").write_text("0\n")

    # eth1 (Physical down)
    eth1 = sys_net / "eth1"
    eth1.mkdir()
    (eth1 / "operstate").write_text("down\n")
    (eth1 / "carrier").write_text("0\n")
    (eth1 / "speed").write_text("-1\n")
    (eth1 / "duplex").write_text("unknown\n")
    (eth1 / "mtu").write_text("1500\n")
    (eth1 / "address").write_text("aa:bb:cc:dd:ee:02\n")
    stats1 = eth1 / "statistics"
    stats1.mkdir()
    for s in ["rx_bytes", "tx_bytes", "rx_packets", "tx_packets", "rx_errors", "tx_errors", "rx_dropped", "tx_dropped"]:
        (stats1 / s).write_text("0\n")

    # br0 (Bridge)
    br0 = sys_net / "br0"
    br0.mkdir()
    (br0 / "operstate").write_text("up\n")
    (br0 / "carrier").write_text("1\n")
    (br0 / "bridge").mkdir()
    brif = br0 / "brif"
    brif.mkdir()
    (brif / "eth0").touch()

    # bond0 (Bond)
    bond0 = sys_net / "bond0"
    bond0.mkdir()
    (bond0 / "operstate").write_text("up\n")
    (bond0 / "carrier").write_text("1\n")
    bonding = bond0 / "bonding"
    bonding.mkdir()
    (bonding / "mode").write_text("active-backup 1\n")
    (bonding / "slaves").write_text("eth0 eth1\n")
    (bonding / "active_slave").write_text("eth0\n")

    with (
        patch("backend.hardware.net.common._find_sys_net_dir", return_value=str(sys_net)),
        patch(
            "backend.hardware.net.common._parse_routes",
            return_value=[
                {"iface": "br0", "destination": "0.0.0.0", "gateway": "10.0.0.1", "is_default": True, "metric": 1},
                {
                    "iface": "br0",
                    "destination": "10.0.0.0",
                    "gateway": "0.0.0.0",
                    "cidr": 24,
                    "is_default": False,
                    "metric": 1,
                },
            ],
        ),
        patch("backend.hardware.net.common._get_dns_servers", return_value=["10.0.0.1"]),
        patch("backend.hardware.net.topology.read_ip", return_value="10.0.0.100"),
        patch(
            "backend.hardware.net.topology._get_docker_topology",
            return_value=[
                {
                    "id": "net123456789",
                    "name": "app_network",
                    "driver": "bridge",
                    "subnet": "172.22.0.0/16",
                    "gateway": "172.22.0.1",
                    "bridge_device": "br-net123456789",
                    "containers": [
                        {"name": "web", "ipv4": "172.22.0.2", "mac": "02:42:ac:16:00:02", "ports": ["80:80/tcp"]}
                    ],
                    "container_count": 1,
                }
            ],
        ),
    ):
        topo = get_network_topology()
        assert topo["status"] == "ok"
        assert topo["summary"]["total_physical"] == 2
        assert topo["summary"]["active_physical"] == 1
        assert topo["summary"]["max_speed"] == "2.5 Gbps"
        assert topo["summary"]["primary_ip"] == "10.0.0.100"
        assert topo["summary"]["default_gateway"] == "10.0.0.1"

        phys = {p["name"]: p for p in topo["physical_interfaces"]}
        assert "eth0" in phys
        assert phys["eth0"]["is_up"] is True
        assert phys["eth0"]["speed_human"] == "2.5 Gbps"
        assert phys["eth0"]["duplex"] == "full"
        assert phys["eth0"]["rx_bytes"] == 1000000

        assert "eth1" in phys
        assert phys["eth1"]["is_up"] is False
        assert phys["eth1"]["speed_human"] == "Disconnected"

        assert len(topo["bridges"]) == 1
        assert topo["bridges"][0]["name"] == "br0"
        assert "eth0" in topo["bridges"][0]["interfaces"]

        assert len(topo["bonds"]) == 1
        assert topo["bonds"][0]["name"] == "bond0"
        assert topo["bonds"][0]["active_slave"] == "eth0"

        assert len(topo["docker_networks"]) == 1
        assert topo["docker_networks"][0]["containers"][0]["name"] == "web"


def test_network_topology_api_endpoints(client, token):
    mock_data = {
        "status": "ok",
        "summary": {"primary_ip": "192.168.1.50", "default_gateway": "192.168.1.1"},
        "physical_interfaces": [{"name": "eth1", "speed_human": "10 Gbps"}],
        "bonds": [],
        "bridges": [],
        "docker_networks": [],
        "routes": [],
    }

    with patch("backend.hardware.network.get_network_topology", return_value=mock_data):
        # Test /api/system/network-topology
        res1 = client.get("/api/system/network-topology", headers={"Authorization": f"Bearer {token}"})
        assert res1.status_code == 200
        json1 = res1.json()
        assert json1["status"] == "ok"
        assert json1["summary"]["primary_ip"] == "192.168.1.50"

        # Test /api/metrics/network-topology
        res2 = client.get("/api/metrics/network-topology", headers={"Authorization": f"Bearer {token}"})
        assert res2.status_code == 200
        json2 = res2.json()
        assert json2["status"] == "ok"


def test_network_config_persistence(tmp_path):
    cfg_file = tmp_path / "network_config.json"
    with patch("backend.hardware.net.common.NETWORK_CONFIG_FILE", str(cfg_file)):
        cfg = load_network_config()
        assert cfg == {"aliases": {}, "ports": {}}

        cfg["aliases"]["eth0"] = "Direct 10G to Workstation"
        cfg["ports"]["eth0"] = {"mtu": 9000, "wol_enabled": True}
        save_network_config(cfg)

        reloaded = load_network_config()
        assert reloaded["aliases"]["eth0"] == "Direct 10G to Workstation"
        assert reloaded["ports"]["eth0"]["mtu"] == 9000
        assert reloaded["ports"]["eth0"]["wol_enabled"] is True


def test_get_host_ip_config(tmp_path):
    cfg_file = tmp_path / "network_config.json"
    mock_topo = {
        "status": "ok",
        "summary": {
            "primary_ip": "192.168.1.50",
            "default_gateway": "192.168.1.1",
            "primary_interface": "br0",
            "dns_servers": ["192.168.1.1"],
        },
        "physical_interfaces": [{"name": "eth0"}, {"name": "eth1"}],
        "bridges": [{"name": "br0"}],
        "bonds": [{"name": "bond0"}],
        "routes": [{"iface": "br0", "destination": "192.168.1.0", "mask": "255.255.255.0", "cidr": 24}],
    }

    with (
        patch("backend.hardware.net.common.NETWORK_CONFIG_FILE", str(cfg_file)),
        patch("backend.hardware.net.topology.get_network_topology", return_value=mock_topo),
        patch("backend.hardware.net.unraid_cfg._parse_unraid_network_cfg", return_value={}),
    ):
        res = get_host_ip_config()
        assert res["status"] == "ok"
        assert res["interface"] == "br0"
        assert "br0" in res["available_interfaces"]
        assert "eth0" in res["available_interfaces"]
        assert res["ip_address"] == "192.168.1.50"
        assert res["netmask"] == "255.255.255.0"
        assert res["cidr"] == 24
        assert res["gateway"] == "192.168.1.1"
        assert res["dns1"] == "192.168.1.1"


def test_read_network_rates_combined_and_interfaces(tmp_path):
    from backend.hardware.network import read_network_rates
    from backend.state import Z_STATE

    proc_net = tmp_path / "proc_net"
    proc_net.mkdir(parents=True, exist_ok=True)
    dev_file = proc_net / "dev"

    # Simulate 2 physical NICs: eth0 and eth1
    content_t1 = (
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        "  lo: 1000       10    0    0    0     0          0         0     1000       10    0    0    0     0       0          0\n"
        "eth0: 1000000    50    0    0    0     0          0         0  2000000       60    0    0    0     0       0          0\n"
        "eth1: 5000000    80    0    0    0     0          0         0  4000000       90    0    0    0     0       0          0\n"
        "veth123: 500      5    0    0    0     0          0         0      500        5    0    0    0     0       0          0\n"
    )
    dev_file.write_text(content_t1)

    with patch("backend.hardware.net.common._find_proc_net_path", return_value=str(dev_file)):
        # Sample 1
        res1 = read_network_rates()
        assert res1["iface"] == "combined"
        assert "interfaces" in res1
        assert "eth0" in res1["interfaces"]
        assert "eth1" in res1["interfaces"]
        assert "lo" not in res1["interfaces"]
        assert "veth123" not in res1["interfaces"]

        # Advance counters (Sample 2)
        content_t2 = (
            "Inter-|   Receive                                                |  Transmit\n"
            " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
            "  lo: 1000       10    0    0    0     0          0         0     1000       10    0    0    0     0       0          0\n"
            "eth0: 2048576    60    0    0    0     0          0         0  3048576       70    0    0    0     0       0          0\n"
            "eth1: 7097152    90    0    0    0     0          0         0  6097152      100    0    0    0     0       0          0\n"
        )
        dev_file.write_text(content_t2)

        res2 = read_network_rates()
        assert res2["iface"] == "combined"
        # Total combined bytes must equal sum of eth0 and eth1
        assert res2["rx_bytes"] == 2048576 + 7097152
        assert res2["tx_bytes"] == 3048576 + 6097152
        assert res2["rx_rate"] > 0
        assert res2["tx_rate"] > 0
        assert res2["interfaces"]["eth0"]["rx_bytes"] == 2048576
        assert res2["interfaces"]["eth1"]["rx_bytes"] == 7097152
        assert res2["interfaces"]["eth0"]["is_physical"] is True
        assert res2["interfaces"]["eth1"]["is_physical"] is True


# ---- SET-16, decision D2: the host's own settings own the wiring; Kiboto reads it and says where to change it


def test_get_port_config_reads_the_port(tmp_path):
    with (
        patch("backend.hardware.net.common.NETWORK_CONFIG_FILE", str(tmp_path / "network_config.json")),
        patch(
            "backend.hardware.net.topology.get_network_topology",
            return_value={
                "status": "ok",
                "physical_interfaces": [{"name": "eth0", "mtu": 1500, "is_up": True}],
                "bonds": [],
                "bridges": [],
            },
        ),
        patch(
            "backend.hardware.net.ports._query_ethtool",
            return_value="Supports Wake-on: pumbg\nWake-on: d\nAuto-negotiation: on",
        ),
    ):
        cfg = get_port_config("eth0")
    assert cfg["status"] == "ok" and cfg["interface"]["name"] == "eth0"
    assert cfg["wol_supported"] is True and cfg["wol_enabled"] is False and cfg["autoneg"] is True


def test_bond_and_bridge_are_read_from_the_host(tmp_path):
    sys_net = tmp_path / "sys_net"
    bonding = sys_net / "bond0" / "bonding"
    bonding.mkdir(parents=True)
    (bonding / "mode").write_text("active-backup 1\n")
    (bonding / "slaves").write_text("eth0 eth1\n")
    (bonding / "active_slave").write_text("eth0\n")
    (bonding / "miimon").write_text("100\n")
    bridge_dir = sys_net / "br0" / "bridge"
    bridge_dir.mkdir(parents=True)
    (bridge_dir / "stp_state").write_text("0\n")
    (bridge_dir / "forward_delay").write_text("0\n")
    (sys_net / "br0" / "brif").mkdir()
    (sys_net / "br0" / "brif" / "bond0").touch()
    with (
        patch("backend.hardware.net.common._find_sys_net_dir", return_value=str(sys_net)),
        patch("backend.hardware.net.common.NETWORK_CONFIG_FILE", str(tmp_path / "network_config.json")),
        patch(
            "backend.hardware.network.get_network_topology",
            return_value={"physical_interfaces": [{"name": "eth0"}, {"name": "eth1"}], "bonds": [{"name": "bond0"}]},
        ),
        patch(
            "backend.hardware.net.unraid_cfg._parse_unraid_network_cfg",
            return_value={"BONDING_MODE[0]": "1", "BONDNICS[0]": "eth0 eth1", "BONDING_MIIMON[0]": "100"},
        ),
    ):
        bond = get_bond_config("bond0")
        bridge = get_bridge_config("br0")
    assert bond["status"] == "ok" and bond["mode"] == "1" and bond["mode_name"] == "active-backup"
    assert "eth0" in bond["slaves"] and len(bond["available_modes"]) >= 5
    assert bridge["status"] == "ok" and bridge["stp"] is False and "bond0" in bridge["members"]


def test_a_host_kiboto_does_not_manage_changes_nothing():
    from backend.hardware.net.host import HostNetwork, NotOnThisHost
    from backend.hardware.pal.base import PlatformType

    host = HostNetwork(PlatformType.UNRAID)
    caps = host.capabilities()
    assert caps["managed"] is False and caps["where"] == "unraid"
    assert set(caps["can_change"]) == {"address", "mtu", "speed", "wake_on_lan", "bond", "bridge", "vlan"}
    assert not any(caps["can_change"].values())
    with pytest.raises(NotOnThisHost) as e:
        host.apply("bond", "bond0", {"mode": "4"})
    assert "Unraid" in str(e.value) and e.value.setting == "bond"
    assert HostNetwork("something-else").where() == "system"


def test_a_managed_host_only_has_to_add_the_writes():
    """What Kiboto's own OS images will do: say managed, implement apply()."""
    from backend.hardware.net.host import HostNetwork

    class Managed(HostNetwork):
        managed = True

        def apply(self, setting, target, changes):
            return {"status": "ok", "setting": setting, "target": target, **changes}

    assert all(Managed().capabilities()["can_change"].values())
    assert Managed().apply("mtu", "eth0", {"mtu": 9000})["mtu"] == 9000


WRITES = [
    ("post", "/api/network/host/apply", {"mode": "static", "interface": "br0", "ip_address": "192.168.1.51"}),
    ("post", "/api/network/host/confirm", {"canary_id": "c1"}),
    ("post", "/api/network/host/revert", {"canary_id": "c1"}),
    ("post", "/api/network/bond/bond0", {"mode": "4", "slaves": ["eth0", "eth1"]}),
    ("post", "/api/network/bridge/br0", {"stp": True, "forward_delay": 0, "members": ["bond0"]}),
    ("post", "/api/network/vlan/create", {"parent": "eth0", "vlan_id": 20, "alias": "Guest"}),
    ("delete", "/api/network/vlan/eth0.20", None),
    ("post", "/api/network/port/eth0", {"mtu": 9000}),
]


@pytest.mark.parametrize("method, path, body", WRITES)
def test_every_wiring_change_answers_not_on_this_host(client, token, method, path, body):
    headers = {"Authorization": f"Bearer {token}"}
    with patch("backend.hardware.net.host.current_host") as host_of:
        from backend.hardware.net.host import HostNetwork
        from backend.hardware.pal.base import PlatformType

        host_of.return_value = HostNetwork(PlatformType.UNRAID)
        with patch("backend.api.network.current_host", host_of):
            kw = {"headers": headers} | ({"json": body} if body is not None else {})
            r = getattr(client, method)(path, **kw)
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "not_on_this_host" and "Unraid" in r.json()["detail"]


@pytest.mark.parametrize("method, path, body", WRITES)
def test_a_managed_host_receives_the_change(client, token, method, path, body):
    from backend.hardware.net.host import HostNetwork

    seen = []

    class Managed(HostNetwork):
        managed = True

        def apply(self, setting, target, changes):
            seen.append((setting, target))
            return {"status": "ok"}

    with patch("backend.api.network.current_host", return_value=Managed()):
        kw = {"headers": {"Authorization": f"Bearer {token}"}} | ({"json": body} if body is not None else {})
        r = getattr(client, method)(path, **kw)
    assert r.status_code == 200 and r.json()["status"] == "ok" and len(seen) == 1


def test_capabilities_and_reads_answer(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    with (
        patch("backend.api.network.get_host_ip_config", return_value={"status": "ok", "ip_address": "192.168.1.50"}),
        patch("backend.api.network.get_bond_config", return_value={"status": "ok", "bond_name": "bond0", "mode": "1"}),
        patch("backend.api.network.get_bridge_config", return_value={"status": "ok", "bridge_name": "br0"}),
        patch("backend.api.network.get_vlans", return_value=[{"name": "eth0.10", "parent": "eth0", "vlan_id": 10}]),
    ):
        caps = client.get("/api/network/capabilities", headers=headers)
        assert caps.status_code == 200 and caps.json()["managed"] is False and "where" in caps.json()
        assert client.get("/api/network/host/config", headers=headers).json()["ip_address"] == "192.168.1.50"
        assert client.get("/api/network/bond/bond0", headers=headers).json()["mode"] == "1"
        assert client.get("/api/network/bridge/br0", headers=headers).json()["bridge_name"] == "br0"
        assert len(client.get("/api/network/vlans", headers=headers).json()["vlans"]) == 1


def test_a_port_nickname_is_kiboto_s_own_and_is_saved(client, token, tmp_path):
    headers = {"Authorization": f"Bearer {token}"}
    with patch("backend.hardware.net.common.NETWORK_CONFIG_FILE", str(tmp_path / "network_config.json")):
        r = client.post("/api/network/port/eth0", json={"alias": "  Uplink  "}, headers=headers)
        assert r.status_code == 200 and r.json()["alias"] == "Uplink"
        assert load_network_config()["aliases"]["eth0"] == "Uplink"
        # a nickname with a wiring change: refused whole, the nickname is not half-saved
        r = client.post("/api/network/port/eth0", json={"alias": "Other", "mtu": 9000}, headers=headers)
        assert r.status_code == 409
        assert load_network_config()["aliases"]["eth0"] == "Uplink"
        client.post("/api/network/port/eth0", json={"alias": ""}, headers=headers)
        assert "eth0" not in load_network_config()["aliases"]


def test_docker_network_routes_still_answer(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    with (
        patch("backend.api.network.create_docker_network", return_value={"status": "ok", "id": "net789"}),
        patch("backend.api.network.delete_docker_network", return_value={"status": "ok", "message": "Deleted"}),
    ):
        r = client.post("/api/network/docker/create", json={"name": "test_net", "driver": "bridge"}, headers=headers)
        assert r.status_code == 200 and r.json()["id"] == "net789"
        assert client.delete("/api/network/docker/net789", headers=headers).json()["status"] == "ok"


def test_the_layout_says_what_this_host_lets_kiboto_change(client, token):
    with patch("backend.hardware.network.get_network_topology", return_value={"status": "ok", "summary": {}}):
        r = client.get("/api/system/network-topology", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    host = r.json()["host"]
    assert host["managed"] is False and "where" in host and host["can_change"]["address"] is False


def test_settings_saved_but_never_applied_are_forgotten_once(tmp_path):
    """SET-16: an older version saved an address "trial" and VLANs that never reached the host."""
    import json

    from backend.hardware.net import common

    path = tmp_path / "network_config.json"
    path.write_text(
        json.dumps(
            {
                "aliases": {"eth0": "Uplink"},
                "ports": {},
                "host_ip_config": {"mode": "static", "ip_address": "10.9.9.9"},
                "host_ip_staged": {"ip_address": "10.9.9.9"},
                "vlans": {
                    "eth0.30": {"parent": "eth0", "vlan_id": 30, "alias": "Cameras"},
                    "eth0.40": {"parent": "eth0", "vlan_id": 40},
                },
            }
        )
    )
    with patch("backend.hardware.net.common.NETWORK_CONFIG_FILE", str(path)):
        cfg = common.load_network_config()
        assert cfg["aliases"] == {"eth0": "Uplink", "eth0.30": "Cameras"}
        assert not set(common.UNAPPLIED_KEYS) & set(cfg)
        on_disk = json.loads(path.read_text())
        assert not set(common.UNAPPLIED_KEYS) & set(on_disk) and on_disk["aliases"]["eth0.30"] == "Cameras"
        assert common.forget_unapplied(dict(on_disk)) is False  # nothing left to forget


def test_the_address_shown_is_the_host_s_not_a_saved_trial(tmp_path):
    import json

    path = tmp_path / "network_config.json"
    path.write_text(
        json.dumps(
            {"aliases": {}, "host_ip_config": {"mode": "static", "ip_address": "10.9.9.9", "gateway": "10.9.9.1"}}
        )
    )
    topo = {
        "summary": {
            "primary_ip": "192.168.1.50",
            "primary_interface": "br0",
            "default_gateway": "192.168.1.1",
            "dns_servers": ["192.168.1.1"],
        },
        "routes": [],
        "physical_interfaces": [{"name": "eth0"}],
        "bridges": [{"name": "br0"}],
        "bonds": [],
    }
    with (
        patch("backend.hardware.net.common.NETWORK_CONFIG_FILE", str(path)),
        patch("backend.hardware.net.topology.get_network_topology", return_value=topo),
        patch("backend.hardware.net.unraid_cfg._parse_unraid_network_cfg", return_value={}),
    ):
        cfg = get_host_ip_config()
    assert cfg["ip_address"] == "192.168.1.50" and cfg["gateway"] == "192.168.1.1"


def test_only_bridge_docker_networks_are_created():
    res = create_docker_network("cams", "macvlan")
    assert res["status"] == "error" and "bridge" in res["message"]
