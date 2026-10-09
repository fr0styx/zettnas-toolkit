from unittest.mock import patch

from backend.services.app_catalog import get_catalog_app
from backend.services.docker_cleanup import (
    destroy_container,
    get_docker_system_df,
    is_self_container,
    prune_docker_system,
)


def test_uptime_kuma_uses_next_tag():
    app = get_catalog_app("uptime-kuma")
    assert app is not None
    assert app["image"] == "louislam/uptime-kuma:next"


def test_is_self_container():
    assert is_self_container("abc123456789", "zettnas-toolkit") is True
    assert is_self_container("abc123456789", "/zettnas-toolkit") is True
    assert is_self_container("abc123456789", "zettnas") is True
    assert is_self_container("112233445566", "uptime-kuma") is False
    assert is_self_container("112233445566", "jellyfin") is False


def test_destroy_container_self_protection():
    with patch(
        "backend.services.docker_cleanup._docker_request",
        return_value=(200, {"Name": "/zettnas-toolkit", "Id": "self999", "Image": "zettnas:latest"}),
    ):
        try:
            destroy_container("self999")
            assert False, "Should have raised ValueError on self-deletion"
        except ValueError as exc:
            assert "Cannot destroy the zettnas-toolkit container itself" in str(exc)


def test_destroy_container_success():
    def mock_docker(method, path, body=None, timeout=20.0):
        if method == "GET" and path == "/containers/c123/json":
            return (
                200,
                {
                    "Name": "/uptime-kuma",
                    "Id": "c123456789012",
                    "Image": "sha256:abc123image",
                    "Config": {"Image": "louislam/uptime-kuma:next"},
                },
            )
        if method == "DELETE" and path == "/containers/c123?v=true&force=false":
            return 204, {}
        if method == "DELETE" and "images/" in path:
            return 200, [{"Deleted": "sha256:abc123image"}]
        return 400, {}

    with patch("backend.services.docker_cleanup._docker_request", side_effect=mock_docker):
        res = destroy_container("c123", force=False, remove_volumes=True, remove_image=True)
        assert res["success"] is True
        assert res["name"] == "uptime-kuma"
        assert res["volumes_removed"] is True
        assert res["image_removed"] is True


def test_delete_container_api_endpoint(client, auth_headers):
    def mock_docker(method, path, body=None, timeout=20.0):
        if method == "GET":
            return (
                200,
                {
                    "Name": "/test-app",
                    "Id": "testapp123456",
                    "Image": "testapp:latest",
                    "Config": {"Image": "testapp:latest"},
                },
            )
        if method == "DELETE":
            return 204, {}
        return 400, {}

    with patch("backend.services.docker_cleanup._docker_request", side_effect=mock_docker):
        res = client.delete(
            "/api/docker/containers/testapp123456?force=true&remove_volumes=true&remove_image=false",
            headers=auth_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["name"] == "test-app"
        assert data["removed"] is True


def test_system_df_and_prune(client, auth_headers):
    mock_df_response = {
        "Images": [
            {"Size": 500000000, "Containers": 1},
            {"Size": 250000000, "Containers": 0},
        ],
        "Containers": [
            {"SizeRw": 10000000, "State": "running"},
            {"SizeRw": 5000000, "State": "exited"},
        ],
        "Volumes": [
            {"UsageData": {"Size": 100000000, "RefCount": 1}},
            {"UsageData": {"Size": 50000000, "RefCount": 0}},
        ],
        "BuildCache": [],
    }

    with patch("backend.services.docker_cleanup._docker_request", return_value=(200, mock_df_response)):
        df = get_docker_system_df()
        assert df["images"]["total_count"] == 2
        assert df["images"]["unused_count"] == 1
        assert df["volumes"]["unused_count"] == 1
        assert df["total_reclaimable_bytes"] == 300000000  # 250MB image + 50MB volume

        res = client.get("/api/docker/system/df", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["images"]["unused_count"] == 1

    def mock_prune(method, path, body=None, timeout=60.0):
        if "containers/prune" in path:
            return 200, {"ContainersDeleted": ["c1", "c2"], "SpaceReclaimed": 5000000}
        if "images/prune" in path:
            return 200, {"ImagesDeleted": [{"Deleted": "img1"}], "SpaceReclaimed": 250000000}
        if "volumes/prune" in path:
            return 200, {"VolumesDeleted": ["vol1"], "SpaceReclaimed": 50000000}
        if "networks/prune" in path:
            return 200, {"NetworksDeleted": ["net1"]}
        if "build/prune" in path:
            return 200, {"CachesDeleted": [], "SpaceReclaimed": 0}
        return 200, {}

    with patch("backend.services.docker_cleanup._docker_request", side_effect=mock_prune):
        res_prune = prune_docker_system(
            prune_containers=True,
            prune_images=True,
            prune_volumes=True,
            prune_networks=True,
            prune_build_cache=True,
        )
        assert res_prune["success"] is True
        assert res_prune["containers_deleted_count"] == 2
        assert res_prune["images_deleted_count"] == 1
        assert res_prune["volumes_deleted_count"] == 1
        assert res_prune["space_reclaimed_bytes"] == 305000000

        api_res = client.post(
            "/api/docker/system/prune",
            json={"prune_containers": True, "prune_images": True, "prune_volumes": True},
            headers=auth_headers,
        )
        assert api_res.status_code == 200
        assert api_res.json()["success"] is True
