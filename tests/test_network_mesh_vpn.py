import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.hardware.network import (
    deploy_tailscale_container,
    execute_tailscale_down,
    execute_tailscale_up,
    get_mesh_vpn_status,
)
from backend.main import app


def test_get_mesh_vpn_status_not_installed():
    with (
        patch("backend.hardware.network._find_tailscale_bin", return_value=None),
        patch(
            "backend.hardware.network._get_tailscale_container_info", return_value={"exists": False, "running": False}
        ),
        patch("backend.hardware.network._run_tailscale_cmd", return_value=(127, "not found")),
        patch("subprocess.run") as mock_subp,
    ):
        mock_subp.return_value = MagicMock(returncode=0, stdout="wg0\n")
        status = get_mesh_vpn_status()
        assert status["tailscale"]["installed"] is False
        assert status["tailscale"]["active"] is False
        assert status["tailscale"]["container_mode"] is False
        assert status["wireguard"]["installed"] is True
        assert status["wireguard"]["active"] is True


def test_get_mesh_vpn_status_container_running():
    mock_status_json = json.dumps(
        {
            "BackendState": "Running",
            "Self": {
                "HostName": "zettnas-box",
                "TailscaleIPs": ["100.80.90.100", "fd7a:115c:a1e0::1"],
            },
            "MagicDNSSuffix": "custom.ts.net",
            "Peer": {"peer1": {}, "peer2": {}},
        }
    )
    with (
        patch("backend.hardware.network._find_tailscale_bin", return_value=None),
        patch(
            "backend.hardware.network._get_tailscale_container_info",
            return_value={"exists": True, "running": True, "id": "abc123def456"},
        ),
        patch("backend.hardware.network._run_tailscale_cmd", return_value=(0, mock_status_json)),
        patch("subprocess.run") as mock_subp,
    ):
        mock_subp.return_value = MagicMock(returncode=1, stdout="")
        status = get_mesh_vpn_status()
        assert status["tailscale"]["installed"] is True
        assert status["tailscale"]["active"] is True
        assert status["tailscale"]["container_mode"] is True
        assert status["tailscale"]["container_id"] == "abc123def456"
        assert status["tailscale"]["hostname"] == "zettnas-box"
        assert status["tailscale"]["ipv4"] == "100.80.90.100"
        assert status["tailscale"]["tailnet"] == "custom.ts.net"
        assert status["tailscale"]["peers_count"] == 2


def test_get_mesh_vpn_status_exit_node_and_routes_separation():
    mock_status_json = json.dumps(
        {
            "BackendState": "Running",
            "Self": {
                "HostName": "zettnas-box",
                "TailscaleIPs": ["100.80.90.100"],
                "ExitNodeOption": False,
                "ExitNode": False,
            },
            "Peer": {},
        }
    )
    mock_prefs_json = json.dumps(
        {
            "AdvertiseRoutes": ["0.0.0.0/0", "::/0", "192.168.1.0/24"],
            "RunSSH": True,
        }
    )

    def mock_cmd(args, timeout=10.0):
        if args[:2] == ["status", "--json"]:
            return 0, mock_status_json
        if args[:2] == ["debug", "prefs"]:
            return 0, mock_prefs_json
        return 1, ""

    with (
        patch("backend.hardware.network._find_tailscale_bin", return_value="/usr/bin/tailscale"),
        patch("backend.hardware.network._get_tailscale_container_info", return_value={"exists": False}),
        patch("backend.hardware.network._run_tailscale_cmd", side_effect=mock_cmd),
        patch("subprocess.run") as mock_subp,
    ):
        mock_subp.return_value = MagicMock(returncode=1, stdout="")
        status = get_mesh_vpn_status()
        ts = status["tailscale"]
        assert ts["installed"] is True
        assert ts["active"] is True
        # Exit node is advertised via 0.0.0.0/0, but not yet approved in admin console
        assert ts["advertise_exit_node"] is True
        assert ts["exit_node_approved"] is False
        assert ts["is_exit_node"] is False
        # Subnet routes must contain ONLY genuine LAN routes, NEVER 0.0.0.0/0 or ::/0
        assert ts["advertised_routes"] == ["192.168.1.0/24"]
        assert ts["is_subnet_router"] is True
        assert ts["ssh_enabled"] is True


def test_execute_tailscale_up_needs_login():
    auth_text = "To authenticate, visit:\n\n\thttps://login.tailscale.com/a/sample123456\n"
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(1, auth_text)):
        res = execute_tailscale_up()
        assert res["status"] == "needs_login"
        assert res["auth_url"] == "https://login.tailscale.com/a/sample123456"


def test_execute_tailscale_up_status_json_fallback():
    status_json = json.dumps({"BackendState": "NeedsLogin", "AuthURL": "https://login.tailscale.com/a/fallback999"})

    def mock_cmd(args, timeout=10.0):
        if args[:2] == ["status", "--json"]:
            return 0, status_json
        return 1, "Some generic error without url"

    with patch("backend.hardware.network._run_tailscale_cmd", side_effect=mock_cmd):
        res = execute_tailscale_up()
        assert res["status"] == "needs_login"
        assert res["auth_url"] == "https://login.tailscale.com/a/fallback999"


def test_execute_tailscale_up_success():
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(0, "Success")):
        res = execute_tailscale_up(auth_key="tskey-auth-123", hostname="my-nas")
        assert res["status"] == "success"
        assert res["code"] == 0


def test_execute_tailscale_down():
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(0, "Logged out")):
        res = execute_tailscale_down()
        assert res["status"] == "success"


def test_deploy_tailscale_container_no_docker_socket():
    with patch("os.path.exists", return_value=False):
        res = deploy_tailscale_container()
        assert res["status"] == "error"
        assert "Docker socket" in res["message"]


def test_deploy_tailscale_container_existing_running():
    fake_info = {"Id": "aabbccddeeff112233", "State": {"Running": True}}
    with (
        patch("os.path.exists", return_value=True),
        patch("backend.services.container_mutator._docker_request", return_value=(200, fake_info)),
        patch("backend.hardware.network.execute_tailscale_up", return_value={"status": "success"}),
    ):
        res = deploy_tailscale_container(auth_key="tskey-auth-test")
        assert res["status"] == "success"
        assert res["container_id"] == "aabbccddeeff"


def test_deploy_tailscale_container_new_flow(tmp_path):
    def fake_docker_req(method, path, body=None):
        if method == "GET" and path == "/containers/tailscale/json":
            return 404, {}
        if method == "GET" and path == "/images/tailscale/tailscale:stable/json":
            return 200, {}
        if method == "POST" and "/containers/create" in path:
            return 201, {"Id": "112233445566778899"}
        if method == "POST" and "/start" in path:
            return 204, {}
        return 200, {}

    with (
        patch("os.path.exists", return_value=True),
        patch("time.sleep", return_value=None),
        patch("backend.services.container_mutator._docker_request", side_effect=fake_docker_req),
        patch(
            "backend.hardware.network.execute_tailscale_up",
            return_value={"status": "needs_login", "auth_url": "https://login.tailscale.com/a/xyz999"},
        ),
    ):
        res = deploy_tailscale_container(state_dir=str(tmp_path / "tailscale"))
        assert res["status"] == "success"
        assert res["container_id"] == "112233445566"
        assert res["auth_url"] == "https://login.tailscale.com/a/xyz999"


def test_api_mesh_vpn_endpoints(client, token):
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET /api/network/mesh-vpn
    with patch(
        "backend.hardware.network.get_mesh_vpn_status",
        return_value={"tailscale": {"installed": False}, "wireguard": {"installed": True}},
    ):
        r = client.get("/api/network/mesh-vpn", headers=headers)
        assert r.status_code == 200
        assert r.json()["wireguard"]["installed"] is True

    # 2. POST /api/network/mesh-vpn/tailscale/deploy
    with patch(
        "backend.hardware.network.deploy_tailscale_container",
        return_value={
            "status": "success",
            "container_id": "testcid123",
            "auth_url": "https://login.tailscale.com/a/test",
        },
    ):
        r = client.post(
            "/api/network/mesh-vpn/tailscale/deploy",
            json={"hostname": "my-box", "accept_routes": True},
            headers=headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["container_id"] == "testcid123"
        assert data["auth_url"] == "https://login.tailscale.com/a/test"

    # 3. POST /api/network/mesh-vpn/tailscale/up
    with patch(
        "backend.hardware.network.execute_tailscale_up",
        return_value={"status": "success", "code": 0, "output": "ok"},
    ):
        r = client.post(
            "/api/network/mesh-vpn/tailscale/up",
            json={"auth_key": "tskey-auth-xyz"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    # 4. POST /api/network/mesh-vpn/tailscale/set-routes
    with patch(
        "backend.hardware.network.execute_tailscale_set_routes",
        return_value={"status": "success", "routes": "10.40.30.0/24", "enabled": True},
    ):
        r = client.post(
            "/api/network/mesh-vpn/tailscale/set-routes",
            json={"routes": "10.40.30.0/24", "enabled": True},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["routes"] == "10.40.30.0/24"

    # 5. POST /api/network/mesh-vpn/tailscale/set-exit-node
    with patch(
        "backend.hardware.network.execute_tailscale_set_exit_node",
        return_value={"status": "success", "enabled": True},
    ):
        r = client.post(
            "/api/network/mesh-vpn/tailscale/set-exit-node",
            json={"enabled": True},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["enabled"] is True

    # 6. POST /api/network/mesh-vpn/tailscale/set-ssh
    with patch(
        "backend.hardware.network.execute_tailscale_set_ssh",
        return_value={"status": "success", "enabled": True},
    ):
        r = client.post(
            "/api/network/mesh-vpn/tailscale/set-ssh",
            json={"enabled": True},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["enabled"] is True

    # 7. POST /api/network/mesh-vpn/tailscale/set-serve
    with patch(
        "backend.hardware.network.execute_tailscale_set_serve",
        return_value={"status": "success", "serve_url": "https://test.ts.net", "enabled": True},
    ):
        r = client.post(
            "/api/network/mesh-vpn/tailscale/set-serve",
            json={"enabled": True, "funnel": False, "port": 8082},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["serve_url"] == "https://test.ts.net"

    # 8. POST /api/network/mesh-vpn/tailscale/taildrop/receive
    with patch(
        "backend.hardware.network.execute_tailscale_taildrop_receive",
        return_value={"status": "success", "count": 2, "files": []},
    ):
        r = client.post("/api/network/mesh-vpn/tailscale/taildrop/receive", headers=headers)
        assert r.status_code == 200
        assert r.json()["count"] == 2

    # 9. GET /api/network/mesh-vpn/tailscale/taildrop/files
    with patch(
        "backend.hardware.network.get_taildrop_inbox_files",
        return_value=[{"name": "photo.jpg", "size": 1024, "size_human": "1.0 KB"}],
    ):
        r = client.get("/api/network/mesh-vpn/tailscale/taildrop/files", headers=headers)
        assert r.status_code == 200
        assert len(r.json()["files"]) == 1

    # 10. POST /api/network/mesh-vpn/tailscale/ping
    with patch(
        "backend.hardware.network.execute_tailscale_ping",
        return_value={"status": "success", "peer": "100.80.20.1", "latency_ms": 12.5, "direct": True},
    ):
        r = client.post(
            "/api/network/mesh-vpn/tailscale/ping",
            json={"peer": "100.80.20.1"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["latency_ms"] == 12.5

    # 11. POST /api/network/mesh-vpn/tailscale/reauth
    with patch(
        "backend.hardware.network.execute_tailscale_reauth",
        return_value={"status": "needs_login", "auth_url": "https://login.tailscale.com/a/reauth123"},
    ):
        r = client.post("/api/network/mesh-vpn/tailscale/reauth", headers=headers)
        assert r.status_code == 200
        assert r.json()["auth_url"] == "https://login.tailscale.com/a/reauth123"


def test_tailscale_extended_hardware_functions(tmp_path):
    from backend.hardware.network import (
        detect_local_subnets,
        execute_tailscale_ping,
        execute_tailscale_reauth,
        execute_tailscale_set_exit_node,
        execute_tailscale_set_routes,
        execute_tailscale_set_serve,
        execute_tailscale_set_ssh,
        get_taildrop_inbox_files,
    )

    # Routes
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(0, "ok")):
        res = execute_tailscale_set_routes("192.168.1.0/24", enabled=True)
        assert res["status"] == "ok"
        res_dis = execute_tailscale_set_routes("", enabled=False)
        assert res_dis["status"] == "ok"

    # Exit node
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(0, "ok")):
        res = execute_tailscale_set_exit_node(enabled=True)
        assert res["status"] == "ok"

    # SSH
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(0, "ok")):
        res = execute_tailscale_set_ssh(enabled=True)
        assert res["status"] == "ok"

    # Ping
    ping_out = "pong from test-peer (100.80.1.2) via 192.168.1.50:41641 in 8ms\n"
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(0, ping_out)):
        res = execute_tailscale_ping("100.80.1.2")
        assert res["status"] == "success"
        assert res["latency_ms"] == 8.0
        assert res["is_direct"] is True

    # Reauth
    reauth_out = "To authenticate, visit:\n\n\thttps://login.tailscale.com/a/reauth789\n"
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(1, reauth_out)):
        res = execute_tailscale_reauth()
        assert res["status"] == "needs_login"
        assert res["auth_url"] == "https://login.tailscale.com/a/reauth789"

    # Serve
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(0, "https://my-nas.ts.net")):
        res = execute_tailscale_set_serve(True, False, 8082)
        assert res["status"] == "ok"

    # Taildrop inbox files
    td_dir = tmp_path / "taildrop"
    td_dir.mkdir()
    sample_file = td_dir / "document.pdf"
    sample_file.write_text("dummy content")
    with patch("backend.hardware.network.get_taildrop_dir", return_value=str(td_dir)):
        files = get_taildrop_inbox_files()
        assert len(files) == 1
        assert files[0]["name"] == "document.pdf"

    # Detect subnets
    with patch(
        "backend.hardware.network._parse_routes",
        return_value=[{"destination": "10.40.30.0", "mask": "255.255.255.0", "iface": "eth0"}],
    ):
        subnets = detect_local_subnets()
        assert "10.40.30.0/24" in subnets
