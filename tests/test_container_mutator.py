import pytest
from unittest.mock import patch, MagicMock

from backend.services.container_mutator import (
    check_port_available,
    update_container_resources,
    recreate_container_ports,
)


def test_check_port_available():
    # Invalid ports
    assert check_port_available(0) is False
    assert check_port_available(70000) is False
    assert check_port_available(-5) is False

    # Valid port range
    # In test sandbox, checking a high port should generally return a boolean without error
    res = check_port_available(58321)
    assert isinstance(res, bool)


def test_update_container_resources_validation():
    # Negative memory
    with pytest.raises(ValueError, match="memory_mb must be >= 0"):
        update_container_resources("c123", memory_mb=-10)

    # Negative cpus
    with pytest.raises(ValueError, match="nano_cpus must be >= 0"):
        update_container_resources("c123", nano_cpus=-0.5)

    # Invalid restart policy
    with pytest.raises(ValueError, match="restart_policy must be one of"):
        update_container_resources("c123", restart_policy="invalid-policy")

    # No changes specified
    res = update_container_resources("c123")
    assert res["status"] == "no_changes"


@patch("backend.services.container_mutator._docker_request")
def test_update_container_resources_success(mock_docker_req):
    mock_docker_req.return_value = (200, {"Warnings": []})

    res = update_container_resources(
        "c12345678901",
        memory_mb=512,
        nano_cpus=1.5,
        restart_policy="unless-stopped",
    )

    assert res["status"] == "success"
    assert "Memory" in res["updated_fields"]
    assert "NanoCPUs" in res["updated_fields"]
    assert "RestartPolicy" in res["updated_fields"]

    mock_docker_req.assert_called_once()
    method, path = mock_docker_req.call_args[0][:2]
    body = mock_docker_req.call_args[1].get("body", {})

    assert method == "POST"
    assert path == "/containers/c12345678901/update"
    assert body["Memory"] == 512 * 1024 * 1024
    assert body["MemorySwap"] == 512 * 1024 * 1024 * 2
    assert body["NanoCPUs"] == 1500000000
    assert body["RestartPolicy"] == {"Name": "unless-stopped"}


MOCK_INSPECT_DATA = {
    "Id": "abc123fullid000111222333444",
    "Name": "/jellyfin",
    "Config": {
        "Image": "lscr.io/linuxserver/jellyfin:latest",
        "Env": ["PUID=1000", "PGID=100"],
        "ExposedPorts": {"8096/tcp": {}},
    },
    "HostConfig": {
        "PortBindings": {"8096/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8096"}]},
        "Binds": ["/mnt/user/appdata/jellyfin:/config:rw"],
        "RestartPolicy": {"Name": "unless-stopped"},
    },
    "NetworkSettings": {"Networks": {"bridge": {"NetworkID": "net123", "IPAddress": "172.17.0.5"}}},
}


@patch("backend.services.container_mutator.fetch_container_raw_inspect")
@patch("backend.services.container_mutator.check_port_available", return_value=True)
@patch("backend.services.container_mutator._docker_request")
def test_recreate_container_ports_success(mock_docker_req, mock_chk_port, mock_inspect):
    mock_inspect.return_value = MOCK_INSPECT_DATA

    # Sequence of responses:
    # 1. Stop old -> 204
    # 2. Rename old -> 204
    # 3. Create new -> 201, {"Id": "newid999fullid"}
    # 4. Start new -> 204
    # 5. Delete backup -> 204
    mock_docker_req.side_effect = [
        (204, {}),
        (204, {}),
        (201, {"Id": "newid999fullid"}),
        (204, {}),
        (204, {}),
    ]

    res = recreate_container_ports(
        "abc123fullid000111222333444",
        new_port_bindings=[{"container_port": 8096, "host_port": 8097, "proto": "tcp", "host_ip": "0.0.0.0"}],
        keep_backup=False,
    )

    assert res["status"] == "success"
    assert res["old_id"] == "abc123fullid"
    assert res["new_id"] == "newid999full"
    assert res["retained_backup"] is False

    # Check calls
    assert mock_docker_req.call_count == 5
    calls = mock_docker_req.call_args_list

    # Call 1: Stop
    assert "/stop" in calls[0][0][1]
    # Call 2: Rename
    assert "/rename?name=jellyfin.backup." in calls[1][0][1]
    # Call 3: Create
    assert calls[2][0][1] == "/containers/create?name=jellyfin"
    created_host_config = calls[2][1]["body"]["HostConfig"]
    assert created_host_config["PortBindings"] == {"8096/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8097"}]}
    # Call 4: Start
    assert calls[3][0][1] == "/containers/newid999fullid/start"
    # Call 5: Delete backup
    assert calls[4][0][0] == "DELETE"
    assert "abc123fullid" in calls[4][0][1]


@patch("backend.services.container_mutator.fetch_container_raw_inspect")
@patch("backend.services.container_mutator.check_port_available", return_value=True)
@patch("backend.services.container_mutator._docker_request")
def test_recreate_container_ports_rollback_on_create_failure(mock_docker_req, mock_chk_port, mock_inspect):
    mock_inspect.return_value = MOCK_INSPECT_DATA

    # Sequence:
    # 1. Stop old -> 204
    # 2. Rename old -> 204
    # 3. Create new -> FAILS (status 500)
    # Rollback begins:
    # 4. Rename backup back to original name -> 204
    # 5. Start original container -> 204
    mock_docker_req.side_effect = [
        (204, {}),
        (204, {}),
        (500, {"message": "Image manifest unreadable"}),
        (204, {}),
        (204, {}),
    ]

    with pytest.raises(RuntimeError, match="Automatic rollback restored original state"):
        recreate_container_ports(
            "abc123fullid000111222333444",
            new_port_bindings=[{"container_port": 8096, "host_port": 8097}],
        )

    # Verify rollback was performed: backup renamed back and restarted
    calls = mock_docker_req.call_args_list
    assert any("/rename?name=jellyfin" in c[0][1] for c in calls)
    assert any(c[0][1] == "/containers/abc123fullid000111222333444/start" for c in calls)


@patch("backend.services.container_mutator.fetch_container_raw_inspect")
@patch("backend.services.container_mutator.check_port_available", return_value=True)
@patch("backend.services.container_mutator._docker_request")
def test_recreate_container_ports_rollback_on_start_failure(mock_docker_req, mock_chk_port, mock_inspect):
    mock_inspect.return_value = MOCK_INSPECT_DATA

    # Sequence:
    # 1. Stop old -> 204
    # 2. Rename old -> 204
    # 3. Create new -> 201 {"Id": "failed_new_id"}
    # 4. Start new -> FAILS (status 500)
    # Rollback begins:
    # 5. Delete failed_new_id -> 204
    # 6. Rename backup back to jellyfin -> 204
    # 7. Start original container -> 204
    mock_docker_req.side_effect = [
        (204, {}),
        (204, {}),
        (201, {"Id": "failed_new_id"}),
        (500, {"message": "failed to bind port"}),
        (204, {}),
        (204, {}),
        (204, {}),
    ]

    with pytest.raises(RuntimeError, match="Automatic rollback restored original state"):
        recreate_container_ports(
            "abc123fullid000111222333444",
            new_port_bindings=[{"container_port": 8096, "host_port": 8097}],
        )

    # Verify failed container was deleted
    calls = mock_docker_req.call_args_list
    assert any(c[0][0] == "DELETE" and "failed_new_id" in c[0][1] for c in calls)
    # Verify original container restored and restarted
    assert any("/rename?name=jellyfin" in c[0][1] for c in calls)
    assert any(c[0][1] == "/containers/abc123fullid000111222333444/start" for c in calls)


@patch("backend.services.container_mutator.fetch_container_raw_inspect")
@patch("backend.services.container_mutator.check_port_available", return_value=False)
def test_recreate_container_ports_collision_detected(mock_chk_port, mock_inspect):
    mock_inspect.return_value = MOCK_INSPECT_DATA

    with pytest.raises(ValueError, match="Port collision: Host port 9999/tcp is already in use"):
        recreate_container_ports(
            "abc123fullid000111222333444",
            new_port_bindings=[{"container_port": 8096, "host_port": 9999, "proto": "tcp"}],
        )


@patch("backend.services.container_mutator.fetch_container_raw_inspect")
@patch("backend.services.container_mutator._docker_request")
def test_recreate_container_full_config(mock_docker_req, mock_inspect):
    from backend.services.container_mutator import recreate_container

    mock_inspect.return_value = MOCK_INSPECT_DATA
    # 1. Stop old -> 204
    # 2. Rename old -> 204
    # 3. Create new -> 201
    # 4. Start new -> 204
    # 5. Delete backup -> 204
    mock_docker_req.side_effect = [
        (204, {}),
        (204, {}),
        (201, {"Id": "recreated_new_id_12345"}),
        (204, {}),
        (204, {}),
    ]

    res = recreate_container(
        "abc123fullid000111222333444",
        name="jellyfin-renamed",
        image="lscr.io/linuxserver/jellyfin:10.9.1",
        env=["PUID=1001", "PGID=101", "TZ=UTC"],
        binds=["/mnt/user/appdata/jellyfin:/config:rw", "/mnt/user/media:/media:ro"],
        network_mode="bridge",
        restart_policy="always",
        keep_backup=True,
    )

    assert res["status"] == "success"
    assert res["target_name"] == "jellyfin-renamed"
    assert res["target_image"] == "lscr.io/linuxserver/jellyfin:10.9.1"
    assert res["retained_backup"] is True
    assert res["new_id"] == "recreated_new_id_12345"[:12]

    # Verify create payload
    create_call = [c for c in mock_docker_req.call_args_list if c[0][0] == "POST" and "/containers/create" in c[0][1]][0]
    create_body = create_call[1]["body"]
    assert create_body["Image"] == "lscr.io/linuxserver/jellyfin:10.9.1"
    assert create_body["Env"] == ["PUID=1001", "PGID=101", "TZ=UTC"]
    assert create_body["HostConfig"]["Binds"] == ["/mnt/user/appdata/jellyfin:/config:rw", "/mnt/user/media:/media:ro"]
    assert create_body["HostConfig"]["RestartPolicy"] == {"Name": "always"}

