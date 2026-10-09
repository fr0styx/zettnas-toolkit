import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.hardware.network import (
    _format_speed,
    _hex_to_ip,
    _mask_to_cidr,
    get_network_topology,
)


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
    assert _hex_to_ip("011E280A") == "10.40.30.1"
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
        patch("backend.hardware.network._find_sys_net_dir", return_value=str(sys_net)),
        patch(
            "backend.hardware.network._parse_routes",
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
        patch("backend.hardware.network._get_dns_servers", return_value=["10.0.0.1"]),
        patch("backend.hardware.network.read_ip", return_value="10.0.0.100"),
        patch(
            "backend.hardware.network._get_docker_topology",
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
        "summary": {"primary_ip": "10.40.30.249", "default_gateway": "10.40.30.1"},
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
        assert json1["summary"]["primary_ip"] == "10.40.30.249"

        # Test /api/metrics/network-topology
        res2 = client.get("/api/metrics/network-topology", headers={"Authorization": f"Bearer {token}"})
        assert res2.status_code == 200
        json2 = res2.json()
        assert json2["status"] == "ok"
