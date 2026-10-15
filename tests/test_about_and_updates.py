from unittest.mock import AsyncMock, MagicMock, patch

from backend import __version__
from backend.api.system import _is_newer_version, _parse_version


def test_version_parsing_and_comparison():
    assert _parse_version("1.5.0") == [1, 5, 0]
    assert _parse_version("v1.5.0") == [1, 5, 0]
    assert _parse_version("v2.0") == [2, 0]

    assert _is_newer_version("1.5.1", "1.5.0") is True
    assert _is_newer_version("1.6.0", "1.5.0") is True
    assert _is_newer_version("2.0.0", "1.5.0") is True
    assert _is_newer_version("1.5.0", "1.5.0") is False
    assert _is_newer_version("1.4.3", "1.5.0") is False


def test_get_system_about_endpoint(client, auth_headers):
    resp = client.get("/api/system/about", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "ZettNAS Workbench"
    assert data["version"] == __version__
    assert data["tag"] == f"v{__version__}"
    assert data["release_channel"] == "stable"
    assert "chassis_model" in data
    assert "chassis_slug" in data
    assert "hostname" in data
    assert "platform" in data
    assert "python_version" in data
    assert "uptime_secs" in data


def test_check_system_updates_up_to_date(client, auth_headers):
    mock_gh_response = {
        "tag_name": f"v{__version__}",
        "name": f"Release v{__version__}",
        "html_url": f"https://github.com/fr0styx/zettnas-toolkit/releases/tag/v{__version__}",
        "published_at": "2026-10-08T20:00:00Z",
        "body": "Latest release notes",
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_gh_response

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        resp = client.get("/api/system/updates?force=true", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_version"] == __version__
        assert data["update_available"] is False
        assert data["latest_tag"] == f"v{__version__}"


def test_check_system_updates_newer_available(client, auth_headers):
    mock_gh_response = {
        "tag_name": "v9.9.9",
        "name": "Release v9.9.9",
        "html_url": "https://github.com/fr0styx/zettnas-toolkit/releases/tag/v9.9.9",
        "published_at": "2026-10-09T00:00:00Z",
        "body": "Exciting new features in v9.9.9",
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_gh_response

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        resp = client.get("/api/system/updates?force=true", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_version"] == __version__
        assert data["update_available"] is True
        assert data["latest_tag"] == "v9.9.9"
        assert data["release_name"] == "Release v9.9.9"
        assert "Exciting new features" in data["release_notes"]


def test_check_system_updates_edge_channel(client, auth_headers):
    mock_gh_commit = {
        "sha": "9abc1234567890abcdef",
        "commit": {
            "message": "feat(core): high velocity storage metrics\nDetailed body...",
            "author": {
                "name": "fr0styx",
                "date": "2026-10-13T21:00:00Z",
            },
        },
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_gh_commit

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        resp = client.get("/api/system/updates?force=true&channel=edge", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["channel"] == "edge"
        assert data["latest_version"] == "9abc123"
        assert "9abc123" in data["latest_tag"]
        assert "high velocity storage metrics" in data["release_name"]


def test_apply_system_update_endpoint(client, auth_headers):
    with (
        patch("backend.services.container_mutator.pull_container_image") as mock_pull,
        patch("backend.services.self_updater.spawn_self_updater", return_value=True) as mock_spawn,
        patch("os.path.exists", return_value=True),
    ):
        resp = client.post(
            "/api/system/updates/apply",
            json={"channel": "edge", "target_image": "ghcr.io/fr0styx/zettnas-toolkit:edge"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "restarting"
        assert data["auto_restarting"] is True
        assert data["target_image"] == "ghcr.io/fr0styx/zettnas-toolkit:edge"
        mock_pull.assert_called_once_with("ghcr.io/fr0styx/zettnas-toolkit:edge", 300.0)
        mock_spawn.assert_called_once_with("ghcr.io/fr0styx/zettnas-toolkit:edge", "zettnas-toolkit", 2.5)


def test_apply_system_update_edge_channel_defaults_to_edge_tag(client, auth_headers):
    with (
        patch("backend.services.container_mutator.pull_container_image") as mock_pull,
        patch("backend.services.self_updater.spawn_self_updater", return_value=True) as mock_spawn,
        patch("os.path.exists", return_value=True),
    ):
        resp = client.post(
            "/api/system/updates/apply",
            json={"channel": "edge"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_image"] == "ghcr.io/fr0styx/zettnas-toolkit:edge"
        mock_pull.assert_called_once_with("ghcr.io/fr0styx/zettnas-toolkit:edge", 300.0)
        mock_spawn.assert_called_once_with("ghcr.io/fr0styx/zettnas-toolkit:edge", "zettnas-toolkit", 2.5)


def test_apply_system_update_stable_channel_defaults_to_latest_tag(client, auth_headers):
    with (
        patch("backend.services.container_mutator.pull_container_image") as mock_pull,
        patch("backend.services.self_updater.spawn_self_updater", return_value=True) as mock_spawn,
        patch("os.path.exists", return_value=True),
    ):
        resp = client.post(
            "/api/system/updates/apply",
            json={"channel": "stable"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_image"] == "ghcr.io/fr0styx/zettnas-toolkit:latest"
        mock_pull.assert_called_once_with("ghcr.io/fr0styx/zettnas-toolkit:latest", 300.0)
        mock_spawn.assert_called_once_with("ghcr.io/fr0styx/zettnas-toolkit:latest", "zettnas-toolkit", 2.5)


def test_get_current_build_info_authoritative_image_inspect(monkeypatch):
    from backend.api.system import _get_current_build_info

    monkeypatch.delenv("BUILD_COMMIT", raising=False)
    monkeypatch.delenv("BUILD_DATE", raising=False)

    mock_container = {
        "Image": "sha256:abcd1234abcd",
        "Config": {
            "Labels": {"org.opencontainers.image.revision": "old_stale_commit"},
        },
    }
    mock_image_data = {
        "Config": {
            "Labels": {
                "org.opencontainers.image.revision": "authoritative_new_commit_40char_long_sha",
                "org.opencontainers.image.created": "2026-10-15T18:00:00Z",
            }
        }
    }

    with (
        patch("backend.services.compose_synthesizer.fetch_container_raw_inspect", return_value=mock_container),
        patch("backend.services.container_mutator._docker_request", return_value=(200, mock_image_data)),
        patch("os.path.exists", return_value=False),
    ):
        info = _get_current_build_info()
        assert info["commit"] == "authori"
        assert info["full_commit"] == "authoritative_new_commit_40char_long_sha"
        assert info["build_date"] == "2026-10-15T18:00:00Z"
