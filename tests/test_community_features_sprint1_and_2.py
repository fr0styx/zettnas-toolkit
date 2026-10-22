"""
Unit and Integration Tests for Community Features (Sprints 1, 2, and 3):
1. Notification Wiring in Backup, Replication & Sync engines
2. Rclone Engine async Popen, live %, ETA, per-file error logs, CLI flags
3. App Catalog Sideloading (URL, compose parsing, security sanitization)
4. SFTP Inbound Service (status, users, chroot config, credentials masking)
5. Media Organizer & Renamer (FileBot heuristics, preview diffs, atomic renames)
"""

import json
import os
import shutil
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.services.app_catalog import (
    get_all_catalog_apps,
    get_sideloaded_apps,
    sideload_app_manifest,
)
from backend.services.media_organizer import (
    apply_organize,
    clean_title,
    parse_media_filename,
    preview_organize,
)
from backend.services.rclone_engine import RcloneEngine
from backend.services.sftp_engine import SFTPEngine


# =========================================================================
# 1. Feature 2 & 5: Rclone Engine Async Streaming, Flags & Notifications
# =========================================================================
def test_rclone_engine_start_sync_job_streaming(tmp_path):
    engine = RcloneEngine()
    engine.config_file = str(tmp_path / "rclone.conf")

    fake_json_lines = [
        json.dumps(
            {
                "level": "info",
                "stats": {"bytes": 1048576, "totalBytes": 10485760, "speed": 5242880, "eta": 2},
                "msg": "Transferred stats",
            }
        ),
        json.dumps(
            {
                "level": "info",
                "msg": "Copied (new)",
                "object": "document.pdf",
            }
        ),
        json.dumps(
            {
                "level": "error",
                "msg": "Failed to copy: permission denied",
                "object": "restricted.log",
            }
        ),
        json.dumps(
            {
                "level": "info",
                "stats": {"bytes": 10485760, "totalBytes": 10485760, "speed": 5242880, "eta": 0},
                "msg": "Transferred stats final",
            }
        ),
    ]

    mock_proc = MagicMock()
    mock_proc.stdout.readline.side_effect = [f"{line}\n" for line in fake_json_lines] + [""]
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0

    with (
        patch("shutil.which", return_value="/usr/bin/rclone"),
        patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
        patch("backend.services.notifications.send_notification") as mock_notify,
    ):
        job = engine.start_sync_job(
            src="/tmp/src",
            dst="/tmp/dst",
            action="sync",
            ignore_errors=True,
            retries=5,
            verbose=True,
            notify=True,
        )

        assert job["id"] is not None
        assert job["status"] in ("running", "success")

        # Wait briefly for worker thread to finish processing mock lines
        for _ in range(50):
            if job["status"] != "running":
                break
            time.sleep(0.05)

        assert job["status"] == "success"
        assert job["percent"] == 100.0
        assert len(job["successful_files"]) == 1
        assert job["successful_files"][0]["file"] == "document.pdf"
        assert len(job["failed_files"]) == 1
        assert job["failed_files"][0]["file"] == "restricted.log"
        assert len(job["transfer_log"]) >= 4

        # Verify command flags passed to Popen
        cmd_args = mock_popen.call_args[0][0]
        assert "--ignore-errors" in cmd_args
        assert "-v" in cmd_args
        assert "--use-json-log" in cmd_args
        assert "--retries" in cmd_args
        assert "5" in cmd_args

        # Verify notification was sent
        assert mock_notify.called
        call_payload = mock_notify.call_args[0][0]
        assert call_payload["type"] == "sync"
        assert "Completed" in call_payload["title"]


# =========================================================================
# 2. Feature 1: App Catalog Sideloading & Security Assessment
# =========================================================================
def test_sideload_app_manifest_zett_app_json(tmp_path):
    manifest = {
        "id": "my-gitea",
        "name": "Gitea Self-Hosted Git",
        "category": "utilities",
        "description": "Lightweight code hosting solution",
        "image": "gitea/gitea:latest",
        "default_port": 3000,
        "ports": [3000, 222],
        "volumes": {"data": "/data"},
        "env": {"USER_UID": "1000"},
    }

    with patch("backend.services.app_catalog.SIDELOADED_APPS_FILE", str(tmp_path / "sideloaded.json")):
        res = sideload_app_manifest(manifest_content=json.dumps(manifest))
        assert res["status"] == "ok"
        app = res["app"]
        assert app["id"] == "sideload_my-gitea"
        assert app["name"] == "Gitea Self-Hosted Git"
        assert app["security_rating"] == "verified"
        assert len(res["security_flags"]) == 0

        # Verify it appears in get_sideloaded_apps
        sideloaded = get_sideloaded_apps()
        assert len(sideloaded) == 1
        assert sideloaded[0]["id"] == "sideload_my-gitea"


def test_sideload_app_manifest_docker_compose_security_warning(tmp_path):
    compose_yaml = """
version: '3.8'
services:
  agent:
    image: portainer/agent:latest
    privileged: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /:/host
    ports:
      - "9001:9001"
"""
    with patch("backend.services.app_catalog.SIDELOADED_APPS_FILE", str(tmp_path / "sideloaded.json")):
        res = sideload_app_manifest(manifest_content=compose_yaml)
        assert res["status"] == "ok"
        app = res["app"]
        assert "sideload_agent" in app["id"]
        assert res["security_rating"] == "elevated"
        assert any("Privileged Mode" in f for f in res["security_flags"])
        assert any("Docker Unix Socket" in f for f in res["security_flags"])
        assert any("Root Filesystem" in f for f in res["security_flags"])


# =========================================================================
# 3. Feature 4: Inbound SFTP Engine Service
# =========================================================================
def test_sftp_engine_user_lifecycle(tmp_path):
    with (
        patch("backend.services.sftp_engine.SFTP_DIR", str(tmp_path)),
        patch("backend.services.sftp_engine.SFTP_CONFIG_FILE", str(tmp_path / "config.json")),
        patch("backend.services.sftp_engine.SFTP_USERS_FILE", str(tmp_path / "users.json")),
        patch("backend.services.sftp_engine.SFTP_CONF_FILE", str(tmp_path / "sshd_config")),
    ):
        engine = SFTPEngine()
        status = engine.get_status()
        assert status.port == 2222
        assert status.users_count == 0

        # Add user
        user = engine.add_user(
            {
                "username": "backup_client",
                "password": "SecretPassword123",
                "shares": ["documents", "media"],
                "read_only": True,
            }
        )
        assert user["username"] == "backup_client"
        assert user["read_only"] is True

        # Check status reflects new user
        status = engine.get_status()
        assert status.users_count == 1
        assert status.shares_count == 2
        assert "sftp -P 2222 backup_client@" in status.quick_connect

        # Verify sshd_config generation
        cfg = engine.save_config({"port": 2223})
        assert cfg["port"] == 2223
        with open(tmp_path / "sshd_config") as f:
            conf_text = f.read()
            assert "Port 2223" in conf_text
            assert "Subsystem sftp internal-sftp" in conf_text
            assert "ChrootDirectory /home/%u" in conf_text

        # Delete user
        assert engine.delete_user("backup_client") is True
        assert len(engine.list_users()) == 0


# =========================================================================
# 4. Feature 3: Media Organizer & Renamer (FileBot Heuristics)
# =========================================================================
def test_parse_media_filename_tv_standard():
    meta = parse_media_filename("Breaking.Bad.S02E05.Breakage.1080p.BluRay.x265-RARBG.mkv")
    assert meta["is_video"] is True
    assert meta["media_type"] == "tv"
    assert meta["title"] == "Breaking Bad"
    assert meta["season"] == 2
    assert meta["episode"] == 5
    assert meta["resolution"] == "1080p"
    assert meta["codec"] == "x265"
    assert "Breaking Bad/Season 02" in meta["proposed_relative_path"]
    assert "Breaking Bad - S02E05" in meta["proposed_relative_path"]


def test_parse_media_filename_movie_standard():
    meta = parse_media_filename("Oppenheimer.2023.2160p.UHD.Remux.HEVC.mkv")
    assert meta["is_video"] is True
    assert meta["media_type"] == "movie"
    assert meta["title"] == "Oppenheimer"
    assert meta["year"] == 2023
    assert meta["resolution"] == "2160p"
    assert meta["codec"] == "x265"
    assert "Oppenheimer (2023)" in meta["proposed_relative_path"]


def test_preview_and_apply_media_organization(tmp_path):
    src_dir = tmp_path / "downloads"
    dst_dir = tmp_path / "organized"
    src_dir.mkdir()
    dst_dir.mkdir()

    # Create dummy video file
    dummy_file = src_dir / "Severance.S01E01.Good.News.About.Hell.1080p.x264.mkv"
    dummy_file.write_text("dummy-video-content")

    # 1. Preview
    preview = preview_organize(str(src_dir), str(dst_dir))
    assert preview["total_files"] == 1
    item = preview["items"][0]
    assert item["media_type"] == "tv"
    assert item["title"] == "Severance"
    assert item["season"] == 1
    assert item["episode"] == 1
    assert item["destination_exists"] is False

    # 2. Apply organization (move)
    res = apply_organize(preview["items"], action="move")
    assert res["status"] == "ok"
    assert res["success_count"] == 1
    assert not dummy_file.exists()
    assert os.path.exists(item["destination_path"])
