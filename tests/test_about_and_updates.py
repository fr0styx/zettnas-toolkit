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
