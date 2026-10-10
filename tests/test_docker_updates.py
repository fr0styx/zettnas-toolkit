import pytest
from unittest.mock import patch, MagicMock

from backend.services.docker_updates import (
    _check_container_image_update,
    check_all_container_updates,
    update_single_container,
    update_all_containers,
)


@patch("backend.services.docker_updates._docker_request")
def test_check_container_image_update_up_to_date(mock_docker_req):
    # Remote distribution returns digest
    # Local image RepoDigests has the same digest
    mock_docker_req.side_effect = [
        (200, {"Descriptor": {"digest": "sha256:1111222233334444"}}),
        (200, {"RepoDigests": ["linuxserver/jellyfin@sha256:1111222233334444"]}),
    ]

    c = {
        "Id": "abc1234567890",
        "Names": ["/jellyfin"],
        "Image": "linuxserver/jellyfin:latest",
    }
    res = _check_container_image_update(c)
    assert res["has_update"] is False
    assert res["status"] == "up_to_date"
    assert res["remote_digest"] == "sha256:1111222233334444"


@patch("backend.services.docker_updates._docker_request")
def test_check_container_image_update_available(mock_docker_req):
    # Remote distribution returns newer digest
    # Local image RepoDigests has older digest
    mock_docker_req.side_effect = [
        (200, {"Descriptor": {"digest": "sha256:9999888877776666"}}),
        (200, {"RepoDigests": ["linuxserver/jellyfin@sha256:1111222233334444"]}),
    ]

    c = {
        "Id": "abc1234567890",
        "Names": ["/jellyfin"],
        "Image": "linuxserver/jellyfin:latest",
    }
    res = _check_container_image_update(c)
    assert res["has_update"] is True
    assert res["status"] == "update_available"
    assert res["remote_digest"] == "sha256:9999888877776666"


def test_check_container_image_update_pinned_digest():
    c = {
        "Id": "abc1234567890",
        "Names": ["/valkey"],
        "Image": "valkey/valkey:9@sha256:4963247afc4cd33c7d3b2d2816b9f7f8eeebab148d29056c2ca4d7cbc966f2d9",
    }
    res = _check_container_image_update(c)
    assert res["has_update"] is False
    assert res["status"] == "pinned"


@patch("backend.services.docker_updates.pull_container_image")
@patch("backend.services.docker_updates.recreate_container")
@patch("backend.services.compose_synthesizer.fetch_container_raw_inspect")
def test_update_single_container(mock_inspect, mock_recreate, mock_pull):
    mock_inspect.return_value = {
        "Id": "c123456",
        "Name": "/testapp",
        "Config": {"Image": "myorg/testapp:latest"},
    }
    mock_pull.return_value = True
    mock_recreate.return_value = {"status": "success", "new_id": "new789"}

    res = update_single_container("c123456")
    assert res["status"] == "success"
    mock_pull.assert_called_once_with("myorg/testapp:latest", timeout=240.0)
    mock_recreate.assert_called_once_with("c123456", image="myorg/testapp:latest", pull_image=False, keep_backup=False)


@patch("backend.services.docker_updates.check_all_container_updates")
@patch("backend.services.docker_updates.update_single_container")
def test_update_all_containers_skips_toolkit(mock_single_update, mock_check_all):
    mock_check_all.return_value = {
        "containers": {
            "immich_server": {"name": "immich_server", "has_update": True},
            "zettnas-toolkit": {"name": "zettnas-toolkit", "has_update": True},
        }
    }
    mock_single_update.return_value = {"status": "success", "new_id": "new_immich"}

    res = update_all_containers()
    assert res["status"] == "completed"
    assert len(res["updated"]) == 1
    assert res["updated"][0]["name"] == "immich_server"
    assert len(res["skipped"]) == 1
    assert res["skipped"][0]["name"] == "zettnas-toolkit"
    mock_single_update.assert_called_once_with("immich_server")
