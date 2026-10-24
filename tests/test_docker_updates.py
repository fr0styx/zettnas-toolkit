from unittest.mock import MagicMock, patch

import pytest

from backend.services.docker_updates import (
    _check_container_image_update,
    check_all_container_updates,
    update_all_containers,
    update_single_container,
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


def test_extract_registry_from_image():
    from backend.services.docker_updates import extract_registry_from_image

    assert extract_registry_from_image("ghcr.io/org/my-app:v1.2.3") == ("ghcr.io", "org/my-app", "v1.2.3")
    assert extract_registry_from_image("harbor.local:8443/prod/api:latest") == (
        "harbor.local:8443",
        "prod/api",
        "latest",
    )
    assert extract_registry_from_image("library/postgres:16-alpine") == ("docker.io", "library/postgres", "16-alpine")
    assert extract_registry_from_image("ubuntu:latest") == ("docker.io", "library/ubuntu", "latest")


@patch("backend.services.docker_updates.load_docker_host_credentials")
def test_get_registry_auth_for_image_and_header(mock_load_creds):
    import base64
    import json

    from backend.services.docker_updates import get_registry_auth_for_image, get_registry_auth_header

    mock_load_creds.return_value = {
        "ghcr.io": {"auth": "Z2hfdXNlcjpnaF90b2tlbg=="},
        "https://index.docker.io/v1/": {"auth": "ZG9ja2VydXNlcjpkb2NrZXJwYXNz"},
    }

    auth_ghcr = get_registry_auth_for_image("ghcr.io/myteam/secret-app:1.0")
    assert auth_ghcr is not None
    assert auth_ghcr["auth"] == "Z2hfdXNlcjpnaF90b2tlbg=="

    header_ghcr = get_registry_auth_header("ghcr.io/myteam/secret-app:1.0")
    assert "X-Registry-Auth" in header_ghcr
    decoded_auth = json.loads(base64.b64decode(header_ghcr["X-Registry-Auth"]).decode("utf-8"))
    assert decoded_auth["auth"] == "Z2hfdXNlcjpnaF90b2tlbg=="

    # Non-authenticated registry returns empty header
    header_quay = get_registry_auth_header("quay.io/coreos/etcd:latest")
    assert header_quay == {}


@patch("backend.services.docker_updates.load_docker_host_credentials")
@patch("backend.services.docker_updates._docker_request")
def test_check_container_image_update_private_registry_authenticated(mock_docker_req, mock_load_creds):
    mock_load_creds.return_value = {
        "ghcr.io": {"auth": "dGVzdHVzZXI6dGVzdHBhc3M="},
    }

    # 1. Distribution returns digest
    # 2. Local image inspect returns older digest
    mock_docker_req.side_effect = [
        (200, {"Descriptor": {"digest": "sha256:private99998888"}}),
        (200, {"RepoDigests": ["ghcr.io/myteam/app@sha256:private11112222"]}),
    ]

    c = {
        "Id": "priv12345678",
        "Names": ["/private_app"],
        "Image": "ghcr.io/myteam/app:latest",
    }

    res = _check_container_image_update(c)
    assert res["has_update"] is True
    assert res["status"] == "update_available"
    assert res["remote_digest"] == "sha256:private99998888"

    # Verify X-Registry-Auth header was passed to the distribution query
    first_call_headers = mock_docker_req.call_args_list[0][1].get("headers", {})
    assert "X-Registry-Auth" in first_call_headers


@patch("backend.services.docker_updates.pull_container_image")
@patch("backend.services.docker_updates.recreate_container")
@patch("backend.services.compose_synthesizer.fetch_container_raw_inspect")
def test_update_clears_the_cached_update_and_counts_it_once(mock_inspect, mock_recreate, mock_pull, monkeypatch):
    from backend.services import docker_updates

    entry = {"name": "dozzle", "id": "old1", "has_update": True, "status": "update_available"}
    monkeypatch.setattr(
        docker_updates,
        "_update_cache",
        {
            "checked_at": 1,
            "total_containers": 2,
            "updates_available_count": 2,
            "containers": {"dozzle": entry, "old1": entry},
        },
    )
    mock_inspect.return_value = {"Id": "old1", "Name": "/dozzle", "Config": {"Image": "amir20/dozzle:latest"}}
    mock_recreate.return_value = {"status": "success", "new_id": "new1"}
    update_single_container("dozzle")
    status = docker_updates.get_cached_update_status()
    assert status["containers"]["dozzle"]["has_update"] is False and status["containers"]["old1"]["has_update"] is False
    assert status["updates_available_count"] == 1
    # updating it again (already up to date) does not lower the count of the others
    update_single_container("dozzle")
    assert docker_updates.get_cached_update_status()["updates_available_count"] == 1
