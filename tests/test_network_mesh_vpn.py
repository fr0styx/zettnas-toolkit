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


def test_execute_tailscale_up_needs_login():
    auth_text = "To authenticate, visit:\n\n\thttps://login.tailscale.com/a/sample123456\n"
    with patch("backend.hardware.network._run_tailscale_cmd", return_value=(1, auth_text)):
        res = execute_tailscale_up()
        assert res["status"] == "needs_login"
        assert res["auth_url"] == "https://login.tailscale.com/a/sample123456"


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
