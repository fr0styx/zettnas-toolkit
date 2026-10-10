"""
Tests for Application & Appdata Backup Engine (Features 21a, 21b, 21c).
Verifies:
1. On-demand backup of an installed container (21b).
2. Auto-archiving of app data & config on container uninstall (21a).
3. Listing, restoring, downloading, and deleting app backups (21c).
4. Tar-slip directory traversal prevention and safe extraction.
"""

import io
import json
import os
import tarfile
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from backend.services.app_backup import (
    create_app_backup,
    list_app_backups,
    restore_app_backup,
    delete_app_backup,
    get_app_backup_path,
    is_safe_tar_member,
    save_app_backup_record,
    get_app_backups_registry,
)
from backend.services.docker_cleanup import destroy_container


@pytest.fixture
def mock_container_inspect():
    return {
        "Id": "193158e06cff1234567890abcdef",
        "Name": "/test-app",
        "State": {"Running": True},
        "Config": {
            "Image": "louislam/uptime-kuma:1",
            "Env": ["NODE_ENV=production", "PORT=3001"],
            "Labels": {"com.docker.compose.project": "test-app"},
        },
        "HostConfig": {
            "PortBindings": {"3001/tcp": [{"HostPort": "3001"}]},
            "RestartPolicy": {"Name": "unless-stopped"},
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/tmp/test_appdata_mount",
                "Destination": "/app/data",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/var/run/docker.sock",
                "Destination": "/var/run/docker.sock",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/mnt/user/media",
                "Destination": "/media",
                "RW": False,
            }
        ],
    }


def test_is_safe_tar_member():
    target_dir = "/tmp/safe_extract_dir"
    safe_member = tarfile.TarInfo(name="config/settings.json")
    assert is_safe_tar_member(safe_member, target_dir) is True

    unsafe_member = tarfile.TarInfo(name="../../etc/shadow")
    assert is_safe_tar_member(unsafe_member, target_dir) is False

    absolute_member = tarfile.TarInfo(name="/etc/passwd")
    assert is_safe_tar_member(absolute_member, target_dir) is False


def test_create_and_restore_app_backup(tmp_path, mock_container_inspect):
    # Setup test appdata source folder
    appdata_dir = tmp_path / "appdata" / "test-app"
    appdata_dir.mkdir(parents=True)
    test_file = appdata_dir / "kuma.db"
    test_file.write_text("sqlite-mock-data-12345")

    # Update inspect data to point to this temp appdata
    mock_container_inspect["Mounts"][0]["Source"] = str(appdata_dir)

    backup_base = tmp_path / "backups"
    backup_base.mkdir()

    registry_file = tmp_path / "app_backups.json"

    with patch("backend.services.app_backup.get_app_backup_base_dir", return_value=str(backup_base)), \
         patch("backend.services.app_backup.APP_BACKUPS_REGISTRY_FILE", str(registry_file)), \
         patch("backend.services.app_backup._docker_request") as mock_docker:
        
        # Mock GET container json, POST pause, POST unpause
        def docker_side_effect(method, path, **kwargs):
            if method == "GET":
                return 200, mock_container_inspect
            if method == "POST" and "pause" in path:
                return 200, {}
            return 200, {}

        mock_docker.side_effect = docker_side_effect

        # 1. Create on-demand backup (Feature 21b)
        record = create_app_backup("test-app", reason="on-demand")
        assert record is not None
        assert record["app_name"] == "test-app"
        assert record["reason"] == "on-demand"
        assert os.path.exists(record["filepath"])
        assert record["size_bytes"] > 0

        # Verify tar contents
        with tarfile.open(record["filepath"], "r:gz") as tar:
            names = tar.getnames()
            assert "manifest.json" in names
            assert "docker-compose.yml" in names
            assert "container_inspect.json" in names
            assert any("kuma.db" in n for n in names)

        # 2. List backups (Feature 21c)
        backups = list_app_backups("test-app")
        assert len(backups) == 1
        assert backups[0]["id"] == record["id"]

        # 3. Simulate data loss and restore (Feature 21c)
        test_file.write_text("corrupted-data")
        assert test_file.read_text() == "corrupted-data"

        restore_res = restore_app_backup(record["id"], recreate_container=False)
        assert restore_res["success"] is True
        assert test_file.read_text() == "sqlite-mock-data-12345"

        # 4. Delete backup (Feature 21c)
        del_res = delete_app_backup(record["id"])
        assert del_res is True
        assert not os.path.exists(record["filepath"])
        assert len(list_app_backups("test-app")) == 0


def test_destroy_container_auto_archives_on_uninstall(tmp_path, mock_container_inspect):
    # Setup test appdata source folder
    appdata_dir = tmp_path / "appdata" / "uninstall-app"
    appdata_dir.mkdir(parents=True)
    test_config = appdata_dir / "config.json"
    test_config.write_text('{"installed": true}')

    mock_container_inspect["Name"] = "/uninstall-app"
    mock_container_inspect["Mounts"][0]["Source"] = str(appdata_dir)

    backup_base = tmp_path / "backups"
    backup_base.mkdir()
    registry_file = tmp_path / "app_backups.json"

    with patch("backend.services.app_backup.get_app_backup_base_dir", return_value=str(backup_base)), \
         patch("backend.services.app_backup.APP_BACKUPS_REGISTRY_FILE", str(registry_file)), \
         patch("backend.services.docker_cleanup._docker_request") as mock_docker_clean, \
         patch("backend.services.app_backup._docker_request") as mock_docker_backup:

        mock_docker_clean.side_effect = lambda method, path, **kw: (200, mock_container_inspect) if method == "GET" else (204, {})
        mock_docker_backup.side_effect = lambda method, path, **kw: (200, mock_container_inspect) if method == "GET" else (204, {})

        # Test destroying container with archive_data=True (Feature 21a)
        res = destroy_container("193158e06cff", archive_data=True, remove_volumes=True)
        assert res["success"] is True
        assert res["archived"] is True
        assert res["archive_record"] is not None
        assert res["archive_record"]["reason"] == "uninstall"
        assert os.path.exists(res["archive_record"]["filepath"])


def test_destroy_container_can_skip_archive(tmp_path, mock_container_inspect):
    with patch("backend.services.docker_cleanup._docker_request") as mock_docker_clean:
        mock_docker_clean.side_effect = lambda method, path, **kw: (200, mock_container_inspect) if method == "GET" else (204, {})

        res = destroy_container("193158e06cff", archive_data=False, remove_volumes=False)
        assert res["success"] is True
        assert res["archived"] is False
        assert res["archive_record"] is None


def test_app_backups_api_endpoints(client, auth_headers, tmp_path, mock_container_inspect):
    appdata_dir = tmp_path / "appdata" / "api-app"
    appdata_dir.mkdir(parents=True)
    test_db = appdata_dir / "data.db"
    test_db.write_text("database-v1-data")

    mock_container_inspect["Name"] = "/api-app"
    mock_container_inspect["Mounts"][0]["Source"] = str(appdata_dir)

    backup_base = tmp_path / "backups"
    backup_base.mkdir()
    registry_file = tmp_path / "app_backups.json"

    with patch("backend.services.app_backup.get_app_backup_base_dir", return_value=str(backup_base)), \
         patch("backend.services.app_backup.APP_BACKUPS_REGISTRY_FILE", str(registry_file)), \
         patch("backend.services.app_backup._docker_request") as mock_docker_backup, \
         patch("backend.services.docker_cleanup._docker_request") as mock_docker_clean:

        mock_docker_backup.side_effect = lambda method, path, **kw: (200, mock_container_inspect) if method == "GET" else (200, {})
        mock_docker_clean.side_effect = lambda method, path, **kw: (200, mock_container_inspect) if method == "GET" else (204, {})

        # 1. POST /api/docker/containers/{cid}/backup (On-demand backup - Feature 21b)
        res = client.post("/api/docker/containers/api-app/backup", headers=auth_headers, json={"reason": "on-demand"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        backup_id = data["backup"]["id"]
        assert data["backup"]["app_name"] == "api-app"

        # 2. GET /api/backup/apps (List app backups - Feature 21c)
        res = client.get("/api/backup/apps", headers=auth_headers)
        assert res.status_code == 200
        list_data = res.json()
        assert any(b["id"] == backup_id for b in list_data["backups"])

        # 3. GET /api/backup/apps/{id}/download (Download archive - Feature 21c)
        res = client.get(f"/api/backup/apps/{backup_id}/download", headers=auth_headers)
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/gzip"
        assert len(res.content) > 0

        # 4. POST /api/backup/apps/{id}/restore (Restore app - Feature 21c)
        test_db.write_text("corrupted-db")
        res = client.post(f"/api/backup/apps/{backup_id}/restore", headers=auth_headers, json={"recreate_container": False})
        assert res.status_code == 200
        assert res.json()["result"]["success"] is True
        assert test_db.read_text() == "database-v1-data"

        # 5. DELETE /api/backup/apps/{id} (Delete backup - Feature 21c)
        res = client.delete(f"/api/backup/apps/{backup_id}", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        # 6. DELETE /api/docker/containers/{cid} with archive_data=True (Uninstall archive - Feature 21a)
        res = client.delete("/api/docker/containers/api-app?archive_data=true&force=true", headers=auth_headers)
        assert res.status_code == 200
        del_data = res.json()
        assert del_data["success"] is True
        assert del_data["archived"] is True
        assert del_data["archive_record"]["reason"] == "uninstall"

