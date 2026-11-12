import json
from unittest.mock import MagicMock, patch

import pytest
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
        patch("backend.hardware.net.tailscale._find_tailscale_bin", return_value=None),
        patch(
            "backend.hardware.net.tailscale._get_tailscale_container_info",
            return_value={"exists": False, "running": False},
        ),
        patch("backend.hardware.net.tailscale._run_tailscale_cmd", return_value=(127, "not found")),
        patch("subprocess.run") as mock_subp,
    ):
        status = get_mesh_vpn_status()
        assert status["tailscale"]["installed"] is False
        assert status["tailscale"]["active"] is False
        assert status["tailscale"]["container_mode"] is False
        assert "wireguard" not in status  # removed (decision D3)


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
        patch("backend.hardware.net.tailscale._find_tailscale_bin", return_value=None),
        patch(
            "backend.hardware.net.tailscale._get_tailscale_container_info",
            return_value={"exists": True, "running": True, "id": "abc123def456"},
        ),
        patch("backend.hardware.net.tailscale._run_tailscale_cmd", return_value=(0, mock_status_json)),
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


def test_get_mesh_vpn_status_container_stopped():
    with (
        patch("backend.hardware.net.tailscale._find_tailscale_bin", return_value=None),
        patch(
            "backend.hardware.net.tailscale._get_tailscale_container_info",
            return_value={"exists": True, "running": False, "id": "abc123def456"},
        ),
        patch("subprocess.run") as mock_subp,
    ):
        mock_subp.return_value = MagicMock(returncode=1, stdout="")
        status = get_mesh_vpn_status()
        assert status["tailscale"]["installed"] is True
        assert status["tailscale"]["active"] is False
        assert status["tailscale"]["backend_state"] == "Stopped"
        assert status["tailscale"]["container_mode"] is True
        assert status["tailscale"]["container_id"] == "abc123def456"


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
        patch("backend.hardware.net.tailscale._find_tailscale_bin", return_value="/usr/bin/tailscale"),
        patch("backend.hardware.net.tailscale._get_tailscale_container_info", return_value={"exists": False}),
        patch("backend.hardware.net.tailscale._run_tailscale_cmd", side_effect=mock_cmd),
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
        assert "ssh_enabled" not in ts  # Tailscale SSH removed (decision D5)


def test_execute_tailscale_up_needs_login():
    auth_text = "To authenticate, visit:\n\n\thttps://login.tailscale.com/a/sample123456\n"
    with (
        patch("backend.hardware.net.tailscale._get_tailscale_container_info", return_value={"exists": False}),
        patch("backend.hardware.net.tailscale._run_tailscale_cmd", return_value=(1, auth_text)),
    ):
        res = execute_tailscale_up()
        assert res["status"] == "needs_login"
        assert res["auth_url"] == "https://login.tailscale.com/a/sample123456"


def test_execute_tailscale_up_status_json_fallback():
    status_json = json.dumps({"BackendState": "NeedsLogin", "AuthURL": "https://login.tailscale.com/a/fallback999"})

    def mock_cmd(args, timeout=10.0):
        if args[:2] == ["status", "--json"]:
            return 0, status_json
        return 1, "Some generic error without url"

    with (
        patch("backend.hardware.net.tailscale._get_tailscale_container_info", return_value={"exists": False}),
        patch("backend.hardware.net.tailscale._run_tailscale_cmd", side_effect=mock_cmd),
    ):
        res = execute_tailscale_up()
        assert res["status"] == "needs_login"
        assert res["auth_url"] == "https://login.tailscale.com/a/fallback999"


def test_execute_tailscale_up_success():
    with (
        patch("backend.hardware.net.tailscale._get_tailscale_container_info", return_value={"exists": False}),
        patch("backend.hardware.net.tailscale._run_tailscale_cmd", return_value=(0, "Success")),
    ):
        res = execute_tailscale_up(auth_key="tskey-auth-123", hostname="my-nas")
        assert res["status"] == "success"
        assert res["code"] == 0


def test_execute_tailscale_up_starts_stopped_container():
    with (
        patch(
            "backend.hardware.net.tailscale._get_tailscale_container_info",
            return_value={"exists": True, "running": False, "id": "abc123def456"},
        ),
        patch("backend.services.container_mutator._docker_request", return_value=(204, {})) as mock_start,
        patch("backend.hardware.net.tailscale._run_tailscale_cmd", return_value=(0, "Success")),
        patch("time.sleep"),
    ):
        res = execute_tailscale_up()
        assert res["status"] == "success"
        mock_start.assert_called_with("POST", "/containers/tailscale/start")


def test_execute_tailscale_down():
    # Host CLI mode
    with (
        patch("backend.hardware.net.tailscale._get_tailscale_container_info", return_value={"exists": False}),
        patch("backend.hardware.net.tailscale._run_tailscale_cmd", return_value=(0, "Logged out")),
    ):
        res = execute_tailscale_down()
        assert res["status"] == "success"
        assert res["code"] == 0

    # Container mode
    with (
        patch(
            "backend.hardware.net.tailscale._get_tailscale_container_info",
            return_value={"exists": True, "running": True},
        ),
        patch("backend.hardware.net.tailscale._run_tailscale_cmd", return_value=(0, "")),
        patch("backend.services.container_mutator._docker_request", return_value=(204, {})) as mock_stop,
    ):
        res = execute_tailscale_down()
        assert res["status"] == "success"
        assert "stopped and disconnected" in res["output"]
        mock_stop.assert_called_with("POST", "/containers/tailscale/stop?t=5")


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
        patch("backend.hardware.net.tailscale_setup.execute_tailscale_up", return_value={"status": "success"}),
    ):
        res = deploy_tailscale_container(auth_key="tskey-auth-test")
        assert res["status"] == "success"
        assert res["container_id"] == "aabbccddeeff"


def test_deploy_tailscale_container_new_flow(tmp_path):
    def fake_docker_req(method, path, body=None, headers=None):
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
            "backend.hardware.net.tailscale_setup.execute_tailscale_up",
            return_value={"status": "needs_login", "auth_url": "https://login.tailscale.com/a/xyz999"},
        ),
    ):
        res = deploy_tailscale_container(state_dir=str(tmp_path / "tailscale"))
        assert res["status"] == "success"
        assert res["container_id"] == "112233445566"
        assert res["auth_url"] == "https://login.tailscale.com/a/xyz999"


GONE = [
    ("post", "/api/network/mesh-vpn/tailscale/up"),
    ("post", "/api/network/mesh-vpn/tailscale/down"),
    ("post", "/api/network/mesh-vpn/tailscale/deploy"),
    ("post", "/api/network/mesh-vpn/tailscale/set-ssh"),
    ("post", "/api/network/mesh-vpn/tailscale/set-serve"),
    ("post", "/api/network/mesh-vpn/tailscale/taildrop/receive"),
    ("get", "/api/network/mesh-vpn/tailscale/taildrop/files"),
    ("post", "/api/network/mesh-vpn/tailscale/ping"),
    ("post", "/api/network/mesh-vpn/wireguard/client-config"),
    ("get", "/api/network/mesh-vpn/wireguard/subnet-routing"),
    ("post", "/api/network/mesh-vpn/wireguard/subnet-routing"),
]


def test_api_mesh_vpn_endpoints(client, token):
    """What stays (D5): the status, reaching things at home, home internet when away, signing in again."""
    headers = {"Authorization": f"Bearer {token}"}
    with patch(
        "backend.hardware.network.cached_mesh_vpn_status",
        return_value={"tailscale": {"installed": True, "active": True, "peers": []}},
    ):
        r = client.get("/api/network/mesh-vpn", headers=headers)
        assert r.status_code == 200 and r.json()["tailscale"]["active"] is True
    with patch("backend.hardware.network.execute_tailscale_set_routes", return_value={"status": "success"}) as routes:
        r = client.post(
            "/api/network/mesh-vpn/tailscale/set-routes",
            json={"routes": "192.168.1.0/24", "enabled": True},
            headers=headers,
        )
        assert r.status_code == 200 and routes.call_args.kwargs == {"routes": "192.168.1.0/24", "enabled": True}
    with patch(
        "backend.hardware.network.execute_tailscale_set_exit_node", return_value={"status": "success"}
    ) as exit_node:
        r = client.post("/api/network/mesh-vpn/tailscale/set-exit-node", json={"enabled": True}, headers=headers)
        assert r.status_code == 200 and exit_node.call_args.kwargs == {"enabled": True}
    with patch(
        "backend.hardware.network.execute_tailscale_reauth",
        return_value={"status": "needs_login", "auth_url": "https://login.tailscale.com/a/x"},
    ):
        r = client.post("/api/network/mesh-vpn/tailscale/reauth", headers=headers)
        assert r.status_code == 200


@pytest.mark.parametrize("method, path", GONE)
def test_removed_routes_say_what_replaced_them(client, token, method, path):
    r = getattr(client, method)(path, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 410 and r.json()["error"] == "removed" and r.json()["detail"]


def test_the_kept_tailscale_switches(tmp_path):
    from backend.hardware.network import execute_tailscale_set_exit_node, execute_tailscale_set_routes

    with patch("backend.hardware.net.tailscale._run_tailscale_cmd", return_value=(0, "")) as run:
        assert execute_tailscale_set_routes("192.168.1.0/24", enabled=True)["status"] in ("success", "ok")
        execute_tailscale_set_routes("", enabled=False)
        execute_tailscale_set_exit_node(enabled=True)
    assert run.call_count >= 3
