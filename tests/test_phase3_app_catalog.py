import pytest
from unittest.mock import patch


def test_get_app_catalog(client, auth_headers):
    res = client.get("/api/docker/catalog", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 20

    app_ids = {a["id"] for a in data}
    assert "jellyfin" in app_ids
    assert "immich" in app_ids
    assert "homeassistant" in app_ids
    assert "vaultwarden" in app_ids
    assert "qbittorrent" in app_ids

    jellyfin = next(a for a in data if a["id"] == "jellyfin")
    assert jellyfin["default_port"] == 8096
    assert jellyfin["category"] == "media"
    assert "image" in jellyfin
    assert "volumes" in jellyfin


def test_resolve_app_port_no_conflict(client, auth_headers):
    with patch("backend.services.app_catalog.check_port_available", return_value=True):
        res = client.get("/api/docker/catalog/jellyfin/resolve", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["app_id"] == "jellyfin"
        assert data["conflict_detected"] is False
        assert data["suggested_port"] == 8096


def test_resolve_app_port_with_conflict(client, auth_headers):
    # Simulate default 8096 being occupied, but 8097 being free
    def mock_check(port, proto="tcp"):
        return port != 8096

    with patch("backend.services.app_catalog.check_port_available", side_effect=mock_check):
        res = client.get("/api/docker/catalog/jellyfin/resolve", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["app_id"] == "jellyfin"
        assert data["conflict_detected"] is True
        assert data["suggested_port"] == 8097
        assert "already in use" in data["reason"]


def test_generate_compose_for_app(client, auth_headers):
    res = client.post(
        "/api/docker/catalog/jellyfin/compose",
        json={"host_port": 8099, "storage_root": "/mnt/user/appdata"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["app_id"] == "jellyfin"
    assert data["port"] == 8099
    assert "8099:8096" in data["compose_yaml"]
    assert "/mnt/user/appdata/jellyfin/config" in data["compose_yaml"]
    assert "services" in data["compose_dict"]


def test_container_exec_endpoint(client, auth_headers):
    with patch(
        "backend.services.compose_synthesizer.execute_in_container",
        return_value={"success": True, "output": "Linux 6.6.0-unraid x86_64", "cmd": ["uname", "-a"]},
    ):
        res = client.post(
            "/api/docker/containers/my-test-container/exec",
            json={"cmd": "uname -a"},
            headers=auth_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "Linux" in data["output"]
