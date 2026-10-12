import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.hardware.network import (
    _format_speed,
    _hex_to_ip,
    _mask_to_cidr,
    apply_host_ip_config_canary,
    confirm_host_ip_config,
    create_docker_network,
    create_vlan,
    delete_docker_network,
    delete_vlan,
    get_bond_config,
    get_bridge_config,
    get_canary_watchdog,
    get_host_ip_config,
    get_network_topology,
    get_port_config,
    get_vlans,
    load_network_config,
    revert_host_ip_config,
    save_network_config,
    update_bond_config,
    update_bridge_config,
    update_port_config,
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


def test_network_config_persistence(tmp_path):
    cfg_file = tmp_path / "network_config.json"
    with patch("backend.hardware.network.NETWORK_CONFIG_FILE", str(cfg_file)):
        cfg = load_network_config()
        assert cfg == {"aliases": {}, "ports": {}}

        cfg["aliases"]["eth0"] = "Direct 10G to Workstation"
        cfg["ports"]["eth0"] = {"mtu": 9000, "wol_enabled": True}
        save_network_config(cfg)

        reloaded = load_network_config()
        assert reloaded["aliases"]["eth0"] == "Direct 10G to Workstation"
        assert reloaded["ports"]["eth0"]["mtu"] == 9000
        assert reloaded["ports"]["eth0"]["wol_enabled"] is True


def test_get_and_update_port_config(tmp_path):
    cfg_file = tmp_path / "network_config.json"
    mock_topo = {
        "status": "ok",
        "physical_interfaces": [{"name": "eth0", "mtu": 1500, "is_up": True}],
        "bonds": [],
        "bridges": [],
    }

    with (
        patch("backend.hardware.network.NETWORK_CONFIG_FILE", str(cfg_file)),
        patch("backend.hardware.network.get_network_topology", return_value=mock_topo),
        patch(
            "backend.hardware.network._query_ethtool",
            return_value="Supports Wake-on: pumbg\nWake-on: d\nAuto-negotiation: on",
        ),
        patch("backend.hardware.network._apply_mtu", return_value=True) as mock_mtu,
        patch("backend.hardware.network._apply_wol", return_value=True) as mock_wol,
        patch("backend.hardware.network._apply_negotiation", return_value=True) as mock_neg,
    ):
        # 1. Query port configuration
        cfg = get_port_config("eth0")
        assert cfg["status"] == "ok"
        assert cfg["interface"]["name"] == "eth0"
        assert cfg["wol_supported"] is True
        assert cfg["wol_enabled"] is False
        assert cfg["autoneg"] is True

        # 2. Update port configuration
        res = update_port_config(
            "eth0",
            {
                "alias": "Direct 10G Workstation",
                "mtu": 9000,
                "wol_enabled": True,
                "autoneg": False,
                "speed": 10000,
                "duplex": "full",
            },
        )
        assert res["status"] == "ok"
        assert res["config"]["alias"] == "Direct 10G Workstation"
        assert res["config"]["mtu"] == 9000
        assert res["config"]["wol_enabled"] is True
        mock_mtu.assert_called_once_with("eth0", 9000)
        mock_wol.assert_called_once_with("eth0", True)
        mock_neg.assert_called_once_with("eth0", False, 10000, "full")


def test_network_api_port_and_docker_endpoints(client, token):
    mock_port_data = {
        "status": "ok",
        "interface": {"name": "eth0", "mtu": 1500},
        "alias": "Workstation Link",
        "mtu": 1500,
        "wol_supported": True,
        "wol_enabled": False,
        "autoneg": True,
        "supported_speeds": [10000, 2500, 1000],
    }

    with (
        patch("backend.api.network.get_port_config", return_value=mock_port_data),
        patch("backend.api.network.update_port_config", return_value={"status": "ok", "message": "Updated"}),
        patch("backend.api.network.create_docker_network", return_value={"status": "ok", "id": "net789"}),
        patch("backend.api.network.delete_docker_network", return_value={"status": "ok", "message": "Deleted"}),
    ):
        headers = {"Authorization": f"Bearer {token}"}

        # 1. GET /api/network/port/eth0
        res = client.get("/api/network/port/eth0", headers=headers)
        assert res.status_code == 200
        assert res.json()["alias"] == "Workstation Link"

        # 2. POST /api/network/port/eth0
        res = client.post(
            "/api/network/port/eth0",
            json={"alias": "Uplink", "mtu": 9000, "wol_enabled": True},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        # 3. POST /api/network/docker/create
        res = client.post(
            "/api/network/docker/create",
            json={"name": "test_net", "driver": "bridge", "subnet": "172.28.0.0/16"},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["id"] == "net789"

        # 4. DELETE /api/network/docker/net789
        res = client.delete("/api/network/docker/net789", headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


def test_get_host_ip_config(tmp_path):
    cfg_file = tmp_path / "network_config.json"
    mock_topo = {
        "status": "ok",
        "summary": {
            "primary_ip": "10.40.30.249",
            "default_gateway": "10.40.30.1",
            "primary_interface": "br0",
            "dns_servers": ["10.40.30.1"],
        },
        "physical_interfaces": [{"name": "eth0"}, {"name": "eth1"}],
        "bridges": [{"name": "br0"}],
        "bonds": [{"name": "bond0"}],
        "routes": [{"iface": "br0", "destination": "10.40.30.0", "mask": "255.255.255.0", "cidr": 24}],
    }

    with (
        patch("backend.hardware.network.NETWORK_CONFIG_FILE", str(cfg_file)),
        patch("backend.hardware.network.get_network_topology", return_value=mock_topo),
        patch("backend.hardware.network._parse_unraid_network_cfg", return_value={}),
    ):
        res = get_host_ip_config()
        assert res["status"] == "ok"
        assert res["interface"] == "br0"
        assert "br0" in res["available_interfaces"]
        assert "eth0" in res["available_interfaces"]
        assert res["ip_address"] == "10.40.30.249"
        assert res["netmask"] == "255.255.255.0"
        assert res["cidr"] == 24
        assert res["gateway"] == "10.40.30.1"
        assert res["dns1"] == "10.40.30.1"
        assert res["canary"]["is_active"] is False


def test_apply_host_ip_config_canary_and_confirm(tmp_path):
    cfg_file = tmp_path / "network_config.json"
    mock_topo = {
        "status": "ok",
        "summary": {"primary_ip": "10.40.30.249", "default_gateway": "10.40.30.1", "primary_interface": "br0"},
        "physical_interfaces": [{"name": "eth0"}],
        "bridges": [{"name": "br0"}],
        "bonds": [],
        "routes": [],
    }

    watchdog = get_canary_watchdog()
    watchdog.confirm()  # Ensure reset

    with (
        patch("backend.hardware.network.NETWORK_CONFIG_FILE", str(cfg_file)),
        patch("backend.hardware.network.get_network_topology", return_value=mock_topo),
        patch("backend.hardware.network._write_unraid_network_cfg", return_value=True) as mock_write_unraid,
        patch("backend.state.add_event") as mock_event,
    ):
        # 1. Apply new IP config with 60s Canary
        res = apply_host_ip_config_canary(
            {
                "mode": "static",
                "interface": "br0",
                "ip_address": "10.40.30.250",
                "netmask": "255.255.255.0",
                "gateway": "10.40.30.1",
                "dns1": "1.1.1.1",
                "dns2": "8.8.8.8",
            },
            timeout_sec=60,
        )

        assert res["status"] == "testing"
        assert res["target_ip"] == "10.40.30.250"
        assert res["target_url"] == "http://10.40.30.250:8082"
        assert res["expires_in"] == 60
        canary_id = res["canary_id"]
        assert canary_id

        # Verify staged config in JSON
        saved = load_network_config()
        assert "host_ip_staged" in saved
        assert saved["host_ip_staged"]["canary_id"] == canary_id
        assert saved["host_ip_staged"]["target"]["ip_address"] == "10.40.30.250"

        # Verify Unraid update called
        mock_write_unraid.assert_called()
        mock_event.assert_called()

        # 2. Confirm Canary
        confirm_res = confirm_host_ip_config(canary_id=canary_id)
        assert confirm_res["status"] == "confirmed"

        # Verify persisted permanently
        saved_final = load_network_config()
        assert "host_ip_staged" not in saved_final
        assert saved_final["host_ip_config"]["ip_address"] == "10.40.30.250"
        assert watchdog.is_active is False


def test_apply_host_ip_config_canary_revert(tmp_path):
    cfg_file = tmp_path / "network_config.json"
    mock_topo = {
        "status": "ok",
        "summary": {"primary_ip": "10.40.30.249", "default_gateway": "10.40.30.1", "primary_interface": "br0"},
        "physical_interfaces": [{"name": "eth0"}],
        "bridges": [{"name": "br0"}],
        "bonds": [],
        "routes": [],
    }

    watchdog = get_canary_watchdog()
    watchdog.confirm()  # Ensure reset

    with (
        patch("backend.hardware.network.NETWORK_CONFIG_FILE", str(cfg_file)),
        patch("backend.hardware.network.get_network_topology", return_value=mock_topo),
        patch("backend.hardware.network._write_unraid_network_cfg", return_value=True),
        patch("backend.state.add_event"),
    ):
        apply_res = apply_host_ip_config_canary(
            {
                "mode": "static",
                "interface": "br0",
                "ip_address": "10.40.30.251",
                "netmask": "255.255.255.0",
                "gateway": "10.40.30.1",
            },
            timeout_sec=60,
        )
        assert apply_res["status"] == "testing"
        canary_id = apply_res["canary_id"]

        revert_res = revert_host_ip_config(canary_id=canary_id)
        assert revert_res["status"] == "reverted"
        assert revert_res["restored_ip"] == "10.40.30.249"

        saved = load_network_config()
        assert "host_ip_staged" not in saved
        assert watchdog.is_active is False


def test_canary_watchdog_auto_rollback_on_timeout():
    watchdog = get_canary_watchdog()
    watchdog.confirm()  # Reset

    target = {"ip_address": "10.40.30.252"}
    original = {"ip_address": "10.40.30.249"}

    with (
        patch("backend.hardware.network._execute_revert") as mock_revert,
        patch("backend.state.add_event") as mock_event,
    ):
        canary_id = watchdog.arm(target, original, timeout_sec=60)
        assert watchdog.is_active is True

        # Directly trigger timeout callback
        watchdog._on_timeout(canary_id)
        assert watchdog.is_active is False
        mock_revert.assert_called_once_with(original)
        mock_event.assert_called()


def test_host_ip_api_endpoints(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    mock_config = {
        "status": "ok",
        "mode": "static",
        "interface": "br0",
        "ip_address": "10.40.30.249",
        "netmask": "255.255.255.0",
        "gateway": "10.40.30.1",
        "canary": {"is_active": False},
    }

    with (
        patch("backend.api.network.get_host_ip_config", return_value=mock_config),
        patch(
            "backend.api.network.apply_host_ip_config_canary",
            return_value={"status": "testing", "canary_id": "c123", "expires_in": 60},
        ),
        patch("backend.api.network.confirm_host_ip_config", return_value={"status": "confirmed"}),
        patch("backend.api.network.revert_host_ip_config", return_value={"status": "reverted"}),
    ):
        # 1. GET /api/network/host/config
        r1 = client.get("/api/network/host/config", headers=headers)
        assert r1.status_code == 200
        assert r1.json()["ip_address"] == "10.40.30.249"

        # 2. POST /api/network/host/apply
        r2 = client.post(
            "/api/network/host/apply",
            json={"mode": "static", "interface": "br0", "ip_address": "10.40.30.250"},
            headers=headers,
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "testing"

        # 3. POST /api/network/host/confirm
        r3 = client.post("/api/network/host/confirm", json={"canary_id": "c123"}, headers=headers)
        assert r3.status_code == 200
        assert r3.json()["status"] == "confirmed"

        # 4. POST /api/network/host/revert
        r4 = client.post("/api/network/host/revert", json={"canary_id": "c123"}, headers=headers)
        assert r4.status_code == 200
        assert r4.json()["status"] == "reverted"


def test_get_and_update_bond_config(tmp_path):
    sys_net = tmp_path / "sys_net"
    sys_net.mkdir()
    bond0 = sys_net / "bond0"
    bond0.mkdir()
    bonding = bond0 / "bonding"
    bonding.mkdir()
    (bonding / "mode").write_text("active-backup 1\n")
    (bonding / "slaves").write_text("eth0 eth1\n")
    (bonding / "active_slave").write_text("eth0\n")
    (bonding / "miimon").write_text("100\n")

    unraid_cfg = tmp_path / "network.cfg"
    unraid_cfg.write_text('BONDING_MODE[0]="1"\nBONDNICS[0]="eth0 eth1"\nBONDING_MIIMON[0]="100"\n')

    cfg_file = tmp_path / "network_config.json"

    with (
        patch("backend.hardware.network._find_sys_net_dir", return_value=str(sys_net)),
        patch("backend.hardware.network.NETWORK_CONFIG_FILE", str(cfg_file)),
        patch(
            "backend.hardware.network.get_network_topology",
            return_value={"physical_interfaces": [{"name": "eth0"}, {"name": "eth1"}]},
        ),
        patch("os.path.isfile", side_effect=lambda p: str(p) == str(unraid_cfg) or os.path.exists(p)),
        patch(
            "backend.hardware.network._parse_unraid_network_cfg",
            return_value={"BONDING_MODE[0]": "1", "BONDNICS[0]": "eth0 eth1", "BONDING_MIIMON[0]": "100"},
        ),
        patch("backend.hardware.network._write_unraid_network_cfg", return_value=True),
    ):
        # 1. Get bond config
        cfg = get_bond_config("bond0")
        assert cfg["status"] == "ok"
        assert cfg["mode"] == "1"
        assert cfg["mode_name"] == "active-backup"
        assert "eth0" in cfg["slaves"]
        assert len(cfg["available_modes"]) >= 5

        # 2. Update bond config to 802.3ad LACP
        up_res = update_bond_config("bond0", {"mode": "4", "slaves": ["eth0", "eth1"], "miimon": 100})
        assert up_res["status"] == "ok"
        assert up_res["mode"] == "4"

        # 3. Invalid mode validation
        err_res = update_bond_config("bond0", {"mode": "invalid_mode", "slaves": ["eth0"]})
        assert err_res["status"] == "error"

        # 4. Empty slaves validation
        err_res2 = update_bond_config("bond0", {"mode": "1", "slaves": []})
        assert err_res2["status"] == "error"


def test_get_and_update_bridge_config(tmp_path):
    sys_net = tmp_path / "sys_net"
    sys_net.mkdir()
    br0 = sys_net / "br0"
    br0.mkdir()
    bridge_dir = br0 / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "stp_state").write_text("0\n")
    (bridge_dir / "forward_delay").write_text("0\n")
    brif = br0 / "brif"
    brif.mkdir()
    (brif / "bond0").touch()

    cfg_file = tmp_path / "network_config.json"

    with (
        patch("backend.hardware.network._find_sys_net_dir", return_value=str(sys_net)),
        patch("backend.hardware.network.NETWORK_CONFIG_FILE", str(cfg_file)),
        patch(
            "backend.hardware.network.get_network_topology",
            return_value={"physical_interfaces": [{"name": "eth0"}], "bonds": [{"name": "bond0"}]},
        ),
        patch("backend.hardware.network._write_unraid_network_cfg", return_value=True),
    ):
        # 1. Get bridge config
        cfg = get_bridge_config("br0")
        assert cfg["status"] == "ok"
        assert cfg["stp"] is False
        assert cfg["forward_delay"] == 0
        assert "bond0" in cfg["members"]

        # 2. Update bridge config with STP enabled and 15s forward delay
        up_res = update_bridge_config("br0", {"stp": True, "forward_delay": 15, "members": ["bond0"]})
        assert up_res["status"] == "ok"
        assert up_res["stp"] is True
        assert up_res["forward_delay"] == 15

        # 3. Invalid forward delay clamped
        up_res2 = update_bridge_config("br0", {"stp": False, "forward_delay": 999, "members": ["bond0"]})
        assert up_res2["forward_delay"] == 0


def test_vlan_lifecycle(tmp_path):
    cfg_file = tmp_path / "network_config.json"

    with (
        patch("backend.hardware.network.NETWORK_CONFIG_FILE", str(cfg_file)),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
        patch("os.path.exists", return_value=False),
    ):
        # 1. Create VLAN eth0.10
        create_res = create_vlan("eth0", 10, "IoT Network")
        assert create_res["status"] == "ok"
        assert create_res["name"] == "eth0.10"
        assert create_res["vlan_id"] == 10

        # 2. List VLANs
        vlans = get_vlans()
        assert len(vlans) >= 1
        v = next((x for x in vlans if x["name"] == "eth0.10"), None)
        assert v is not None
        assert v["alias"] == "IoT Network"

        # 3. Invalid VLAN ID
        err1 = create_vlan("eth0", 9999)
        assert err1["status"] == "error"

        # 4. Invalid parent
        err2 = create_vlan("", 10)
        assert err2["status"] == "error"

        # 5. Delete VLAN
        del_res = delete_vlan("eth0.10")
        assert del_res["status"] == "ok"
        vlans_after = get_vlans()
        assert not any(x["name"] == "eth0.10" for x in vlans_after)


def test_tier3_api_endpoints(client, token):
    headers = {"Authorization": f"Bearer {token}"}

    mock_bond = {"status": "ok", "bond_name": "bond0", "mode": "1", "slaves": ["eth0", "eth1"]}
    mock_bridge = {"status": "ok", "bridge_name": "br0", "stp": False, "members": ["bond0"]}
    mock_vlans = [{"name": "eth0.10", "parent": "eth0", "vlan_id": 10}]

    with (
        patch("backend.api.network.get_bond_config", return_value=mock_bond),
        patch(
            "backend.api.network.update_bond_config", return_value={"status": "ok", "bond_name": "bond0", "mode": "4"}
        ),
        patch("backend.api.network.get_bridge_config", return_value=mock_bridge),
        patch(
            "backend.api.network.update_bridge_config", return_value={"status": "ok", "bridge_name": "br0", "stp": True}
        ),
        patch("backend.api.network.get_vlans", return_value=mock_vlans),
        patch("backend.api.network.create_vlan", return_value={"status": "ok", "name": "eth0.20", "vlan_id": 20}),
        patch("backend.api.network.delete_vlan", return_value={"status": "ok", "message": "deleted"}),
    ):
        # 1. GET /api/network/bond/bond0
        r_b1 = client.get("/api/network/bond/bond0", headers=headers)
        assert r_b1.status_code == 200
        assert r_b1.json()["mode"] == "1"

        # 2. POST /api/network/bond/bond0
        r_b2 = client.post("/api/network/bond/bond0", json={"mode": "4", "slaves": ["eth0", "eth1"]}, headers=headers)
        assert r_b2.status_code == 200
        assert r_b2.json()["status"] == "ok"

        # 3. GET /api/network/bridge/br0
        r_br1 = client.get("/api/network/bridge/br0", headers=headers)
        assert r_br1.status_code == 200
        assert r_br1.json()["bridge_name"] == "br0"

        # 4. POST /api/network/bridge/br0
        r_br2 = client.post(
            "/api/network/bridge/br0", json={"stp": True, "forward_delay": 0, "members": ["bond0"]}, headers=headers
        )
        assert r_br2.status_code == 200
        assert r_br2.json()["status"] == "ok"

        # 5. GET /api/network/vlans
        r_v1 = client.get("/api/network/vlans", headers=headers)
        assert r_v1.status_code == 200
        assert len(r_v1.json()["vlans"]) == 1

        # 6. POST /api/network/vlan/create
        r_v2 = client.post(
            "/api/network/vlan/create", json={"parent": "eth0", "vlan_id": 20, "alias": "Guest"}, headers=headers
        )
        assert r_v2.status_code == 200
        assert r_v2.json()["name"] == "eth0.20"

        # 7. DELETE /api/network/vlan/eth0.20
        r_v3 = client.delete("/api/network/vlan/eth0.20", headers=headers)
        assert r_v3.status_code == 200
        assert r_v3.json()["status"] == "ok"


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

    with patch("backend.hardware.network._find_proc_net_path", return_value=str(dev_file)):
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
