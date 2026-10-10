"""
Unit tests for Docker Stacks Manager & Setup Editor Subsystem
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.docker_stacks import (
    execute_stack_action,
    get_stack_details,
    list_all_stacks,
    save_stack_config,
)


@pytest.fixture
def mock_containers_list():
    return [
        {
            "Id": "1234567890abcdef1234",
            "Names": ["/arr_radarr"],
            "Image": "lscr.io/linuxserver/radarr:latest",
            "State": "running",
            "Status": "Up 2 hours",
            "Ports": [{"PublicPort": 7878, "PrivatePort": 7878, "Type": "tcp"}],
            "Labels": {
                "com.docker.compose.project": "arr",
                "com.docker.compose.service": "radarr",
                "com.docker.compose.project.working_dir": "/app/data/stacks/prod/arr",
                "com.docker.compose.project.config_files": "/app/data/stacks/prod/arr/compose.yaml",
            },
        },
        {
            "Id": "abcdef1234567890abcd",
            "Names": ["/arr_sonarr"],
            "Image": "lscr.io/linuxserver/sonarr:latest",
            "State": "running",
            "Status": "Up 2 hours",
            "Ports": [{"PublicPort": 8989, "PrivatePort": 8989, "Type": "tcp"}],
            "Labels": {
                "com.docker.compose.project": "arr",
                "com.docker.compose.service": "sonarr",
                "com.docker.compose.project.working_dir": "/app/data/stacks/prod/arr",
                "com.docker.compose.project.config_files": "/app/data/stacks/prod/arr/compose.yaml",
            },
        },
        {
            "Id": "99999999999999999999",
            "Names": ["/standalone_app"],
            "Image": "nginx:alpine",
            "State": "running",
            "Status": "Up 5 days",
            "Ports": [{"PublicPort": 80, "PrivatePort": 80, "Type": "tcp"}],
            "Labels": {},
        },
    ]


def test_list_all_stacks(mock_containers_list):
    with patch("backend.services.docker_stacks._docker_request") as mock_req:
        mock_req.return_value = (200, json.dumps(mock_containers_list).encode("utf-8"))

        stacks = list_all_stacks()
        assert len(stacks) == 1
        arr = stacks[0]
        assert arr["name"] == "arr"
        assert arr["total_count"] == 2
        assert arr["running_count"] == 2
        assert arr["status"] == "running"
        assert "radarr" in arr["services"]
        assert "sonarr" in arr["services"]


def test_get_stack_details_synthesized(mock_containers_list):
    with (
        patch("backend.services.docker_stacks.list_all_stacks") as mock_list,
        patch("backend.services.docker_stacks.fetch_container_raw_inspect") as mock_inspect,
        patch("os.path.isfile", return_value=False),
        patch("os.path.isdir", return_value=False),
    ):
        mock_list.return_value = [
            {
                "name": "arr",
                "origin": "compose",
                "working_dir": "/nonexistent",
                "config_files": "/nonexistent/compose.yaml",
                "environment_file": "",
                "containers": [
                    {"id": "1234567890ab", "name": "arr_radarr", "service": "radarr", "state": "running"},
                ],
                "status": "running",
            }
        ]

        mock_inspect.return_value = {
            "Name": "/arr_radarr",
            "Config": {
                "Image": "lscr.io/linuxserver/radarr:latest",
                "Env": ["PUID=1000", "PGID=1000", "TZ=UTC"],
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
                "Binds": ["/mnt/user/appdata/radarr:/config:rw"],
            },
        }

        details = get_stack_details("arr")
        assert details["name"] == "arr"
        assert details["has_real_file"] is False
        assert details["location_type"] == "synthesized"
        assert "services:" in details["compose_yaml"]
        assert "radarr:" in details["compose_yaml"]
        assert "PUID=1000" in details["env_content"]


def test_save_stack_config_validation():
    # Invalid YAML
    res = save_stack_config("test_stack", "invalid: yaml: : ::::")
    assert res["success"] is False
    assert "Invalid YAML syntax" in res["error"]

    # Empty YAML
    res_empty = save_stack_config("test_stack", "   ")
    assert res_empty["success"] is False
    assert "cannot be empty" in res_empty["error"]


def test_save_stack_config_host(tmp_path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("version: '3.8'\nservices:\n  web:\n    image: nginx\n")

    with patch("backend.services.docker_stacks.get_stack_details") as mock_details:
        mock_details.return_value = {
            "name": "my_stack",
            "location_type": "host_fs",
            "config_file": str(compose_file),
            "working_dir": str(tmp_path),
        }

        new_yaml = "version: '3.8'\nservices:\n  web:\n    image: nginx:alpine\n"
        res = save_stack_config("my_stack", new_yaml, "PORT=8080")
        assert res["success"] is True

        assert "nginx:alpine" in compose_file.read_text()
        env_file = tmp_path / ".env"
        assert env_file.exists()
        assert env_file.read_text() == "PORT=8080"


def test_execute_stack_action():
    with (
        patch("backend.services.docker_stacks.get_stack_details") as mock_details,
        patch("backend.services.docker_stacks._docker_request") as mock_docker,
    ):
        mock_details.return_value = {
            "name": "arr",
            "containers": [
                {"id": "111111111111", "name": "radarr"},
                {"id": "222222222222", "name": "sonarr"},
            ],
            "location_type": "dockhand",
            "working_dir": "/app/data/stacks/prod/arr",
        }
        mock_docker.return_value = (204, b"")

        res_restart = execute_stack_action("arr", "restart")
        assert res_restart["success"] is True
        assert res_restart["action"] == "restart"
        assert len(res_restart["details"]) == 2

        res_stop = execute_stack_action("arr", "stop")
        assert res_stop["success"] is True
        assert res_stop["action"] == "stop"


def test_api_docker_stacks(client, auth_headers, mock_containers_list):
    with (
        patch("backend.services.docker_stacks._docker_request") as mock_req,
        patch("backend.services.docker_stacks.fetch_container_raw_inspect") as mock_inspect,
    ):
        mock_req.return_value = (200, json.dumps(mock_containers_list).encode("utf-8"))
        mock_inspect.return_value = {
            "Name": "/arr_radarr",
            "Config": {"Image": "radarr:latest", "Env": []},
            "HostConfig": {},
        }

        # 1. GET /api/docker/stacks
        res = client.get("/api/docker/stacks", headers=auth_headers)
        assert res.status_code == 200
        stacks = res.json()
        assert isinstance(stacks, list)
        assert len(stacks) == 1
        assert stacks[0]["name"] == "arr"

        # 2. GET /api/docker/stacks/{stack_name}
        res_det = client.get("/api/docker/stacks/arr", headers=auth_headers)
        assert res_det.status_code == 200
        det = res_det.json()
        assert det["name"] == "arr"
        assert "compose_yaml" in det


def test_api_docker_stack_save_and_action(client, auth_headers):
    with (
        patch("backend.services.docker_stacks.save_stack_config") as mock_save,
        patch("backend.services.docker_stacks.execute_stack_action") as mock_action,
    ):
        mock_save.return_value = {"success": True, "message": "Saved successfully"}
        res_save = client.post(
            "/api/docker/stacks/arr/save",
            json={
                "compose_yaml": "version: '3.8'\nservices:\n  radarr:\n    image: radarr\n",
                "env_content": "PUID=1000",
            },
            headers=auth_headers,
        )
        assert res_save.status_code == 200
        assert res_save.json()["success"] is True

        mock_action.return_value = {"success": True, "action": "restart", "details": []}
        res_act = client.post(
            "/api/docker/stacks/arr/action",
            json={"action": "restart"},
            headers=auth_headers,
        )
        assert res_act.status_code == 200
        assert res_act.json()["success"] is True
        assert res_act.json()["action"] == "restart"
