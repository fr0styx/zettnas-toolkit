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


def test_stream_deploy_catalog_app_endpoint(client, auth_headers):
    import json

    mock_events = [
        {"step": "init", "percent": 5, "message": "Initializing deployment...", "done": False},
        {"step": "storage", "percent": 20, "message": "Storage prepared", "done": False},
        {"step": "pull", "percent": 75, "message": "Image pulled", "done": False},
        {"step": "create", "percent": 88, "message": "Container created", "done": False},
        {
            "step": "success",
            "percent": 100,
            "message": "✓ Home Assistant deployed successfully!",
            "container_id": "mock_cid_12345",
            "webui_url": "http://[HOST]:8123/",
            "port": 8123,
            "done": True,
        },
    ]

    def mock_generator(*args, **kwargs):
        yield from mock_events

    with patch("backend.services.app_catalog.stream_deploy_catalog_app", side_effect=mock_generator):
        res = client.post(
            "/api/docker/catalog/homeassistant/deploy",
            json={"host_port": 8123, "storage_root": "/tmp/test-appdata"},
            headers=auth_headers,
        )
        assert res.status_code == 200
        lines = [line.strip() for line in res.text.strip().split("\n") if line.strip()]
        assert len(lines) == 5

        data_0 = json.loads(lines[0])
        assert data_0["step"] == "init"
        assert data_0["percent"] == 5

        data_last = json.loads(lines[-1])
        assert data_last["step"] == "success"
        assert data_last["percent"] == 100
        assert data_last["container_id"] == "mock_cid_12345"
        assert data_last["port"] == 8123


def test_get_catalog_sources(client, auth_headers):
    res = client.get("/api/docker/catalog/sources", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert any(s["id"] == "builtin" for s in data)


def test_add_sync_toggle_delete_custom_source(client, auth_headers, tmp_path):
    import json
    from unittest.mock import MagicMock

    mock_templates = {
        "templates": [
            {
                "type": 1,
                "title": "Mock AdGuard",
                "name": "mock-adguard",
                "categories": ["DNS", "Network"],
                "description": "AdGuard Home DNS Server",
                "image": "adguard/adguardhome:latest",
                "ports": ["53:53/udp", "3000:3000/tcp"],
                "env": [{"name": "TZ", "default": "UTC"}],
                "volumes": [{"container": "/opt/adguardhome/conf"}],
            }
        ]
    }
    raw_json_bytes = json.dumps(mock_templates).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_json_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        # 1. Add source
        add_res = client.post(
            "/api/docker/catalog/sources",
            json={
                "name": "Custom Unit Test Source",
                "url": "https://raw.githubusercontent.com/test/templates.json",
            },
            headers=auth_headers,
        )
        assert add_res.status_code == 200
        add_data = add_res.json()
        assert add_data["status"] == "ok"
        src = add_data["source"]
        src_id = src["id"]
        assert src["item_count"] == 1
        assert src["status"] == "ok"

        # Verify app is now in catalog
        cat_res = client.get("/api/docker/catalog", headers=auth_headers)
        assert cat_res.status_code == 200
        apps = cat_res.json()
        custom_app = next((a for a in apps if a.get("source_id") == src_id), None)
        assert custom_app is not None
        assert custom_app["name"] == "Mock AdGuard"
        assert custom_app["category"] == "utilities"

        # 2. Toggle source
        toggle_res = client.post(
            f"/api/docker/catalog/sources/{src_id}/toggle",
            json={"enabled": False},
            headers=auth_headers,
        )
        assert toggle_res.status_code == 200
        assert toggle_res.json()["source"]["enabled"] is False

        # Verify app is excluded from catalog when source disabled
        cat_res2 = client.get("/api/docker/catalog", headers=auth_headers)
        apps2 = cat_res2.json()
        assert not any(a.get("source_id") == src_id for a in apps2)

        # 3. Delete source
        del_res = client.delete(f"/api/docker/catalog/sources/{src_id}", headers=auth_headers)
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is True

        # 4. Built-in deletion fails
        del_builtin = client.delete("/api/docker/catalog/sources/builtin", headers=auth_headers)
        assert del_builtin.status_code == 400


def test_resolve_app_port_detects_docker_container_conflict(client, auth_headers):
    mock_containers = [
        {
            "Names": ["/uptime-kuma"],
            "Ports": [{"PublicPort": 3001, "Type": "tcp"}],
        }
    ]

    def fake_docker(method, path, *args, **kwargs):
        if path == "/containers/json":
            return 200, mock_containers
        if "/containers/uptime-kuma/json" in path:
            return 200, {"Id": "abc123456789", "State": {"Running": True}}
        return 404, {}

    with patch("backend.services.container_mutator._docker_request", side_effect=fake_docker):
        with patch("backend.services.app_catalog._docker_request", side_effect=fake_docker):
            res = client.get("/api/docker/catalog/uptime-kuma/resolve", headers=auth_headers)
            assert res.status_code == 200
            data = res.json()
            assert data["app_id"] == "uptime-kuma"
            assert data["conflict_detected"] is True
            assert data["suggested_port"] == 3002
            assert "container 'uptime-kuma'" in data["in_use_by"]
            assert data["existing_container"]["name"] == "uptime-kuma"


def test_check_port_detailed_with_docker():
    from backend.services.container_mutator import check_port_available_detailed

    mock_containers = [
        {
            "Names": ["/uptime-kuma"],
            "Ports": [{"PublicPort": 3001, "Type": "tcp"}],
        }
    ]
    with patch("backend.services.container_mutator._docker_request", return_value=(200, mock_containers)):
        with patch("backend.services.container_mutator.socket.socket") as mock_sock:
            # Mock successful bind for free ports
            mock_sock.return_value.__enter__.return_value.bind.return_value = None
            avail, owner = check_port_available_detailed(3001, "tcp")
            assert avail is False
            assert owner == "container 'uptime-kuma'"


def test_stream_deploy_catalog_app_aborts_on_conflicting_port():
    from backend.services.app_catalog import stream_deploy_catalog_app

    with patch(
        "backend.services.app_catalog.check_port_available_detailed", return_value=(False, "container 'rogue-app'")
    ):
        events = list(stream_deploy_catalog_app("uptime-kuma", host_port=3001))
        error_event = next((e for e in events if e.get("step") == "error"), None)
        assert error_event is not None
        assert "already in use by container 'rogue-app'" in error_event["message"]
