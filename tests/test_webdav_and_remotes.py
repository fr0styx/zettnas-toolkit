"""
Tests for Universal WebDAV Engine and Rclone Remote Storage Subsystem (Sprint 4).
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import backend.config as config
from backend.main import app
from backend.services.rclone_engine import RcloneEngine, get_rclone_engine
from backend.services.webdav_engine import WebdavEngine, ensure_fuse_device, get_webdav_engine


class TestWebdavAndRemotes(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.orig_webdav_cfg = config.WEBDAV_CONFIG_FILE
        self.orig_rclone_cfg = config.RCLONE_CONFIG_FILE
        self.orig_remotes_path = config.REMOTES_PATH

        config.WEBDAV_CONFIG_FILE = os.path.join(self.test_dir, "webdav_config.json")
        config.RCLONE_CONFIG_FILE = os.path.join(self.test_dir, "rclone.conf")
        config.REMOTES_PATH = os.path.join(self.test_dir, "remotes")

        # Reset singleton state
        self.webdav_engine = WebdavEngine()
        self.rclone_engine = RcloneEngine()
        self.rclone_engine.config_file = config.RCLONE_CONFIG_FILE
        self.rclone_engine.remotes_dir = config.REMOTES_PATH

    def tearDown(self):
        try:
            self.webdav_engine.stop()
        except Exception:
            pass
        shutil.rmtree(self.test_dir, ignore_errors=True)
        config.WEBDAV_CONFIG_FILE = self.orig_webdav_cfg
        config.RCLONE_CONFIG_FILE = self.orig_rclone_cfg
        config.REMOTES_PATH = self.orig_remotes_path

    def test_ensure_fuse_device(self):
        # Should gracefully return boolean without raising exceptions
        res = ensure_fuse_device()
        self.assertIsInstance(res, bool)

    def test_webdav_config_defaults_and_mutation(self):
        cfg = self.webdav_engine.load_config()
        self.assertEqual(cfg["port"], config.WEBDAV_PORT)
        self.assertEqual(cfg["username"], "admin")
        self.assertTrue(cfg["enabled"])

        # Update config
        updated = self.webdav_engine.save_config({"port": 9090, "username": "nasuser", "read_only": True})
        self.assertEqual(updated["port"], 9090)
        self.assertEqual(updated["username"], "nasuser")
        self.assertTrue(updated["read_only"])

        # Reload
        reloaded = self.webdav_engine.load_config()
        self.assertEqual(reloaded["port"], 9090)
        self.assertEqual(reloaded["username"], "nasuser")

    def test_webdav_status_and_quick_connect(self):
        status = self.webdav_engine.get_status()
        self.assertIn("enabled", status)
        self.assertIn("running", status)
        self.assertIn("direct_url", status)
        self.assertIn("proxy_url", status)
        self.assertIn("quick_connect", status)
        qc = status["quick_connect"]
        self.assertIn("macos", qc)
        self.assertIn("windows", qc)
        self.assertIn("ios", qc)
        self.assertIn("linux", qc)

    @patch("shutil.which", return_value="/usr/bin/rclone")
    @patch("subprocess.Popen")
    def test_webdav_start_stop(self, mock_popen, mock_which):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 99999
        mock_popen.return_value = mock_proc

        res = self.webdav_engine.start()
        self.assertTrue(res["running"])
        self.assertEqual(res["pid"], 99999)

        stop_res = self.webdav_engine.stop()
        self.assertFalse(stop_res["running"])
        self.assertIsNone(stop_res["pid"])

    def test_rclone_providers_curated(self):
        providers = self.rclone_engine.get_providers()
        self.assertGreater(len(providers), 5)
        types = [p["type"] for p in providers]
        self.assertIn("s3", types)
        self.assertIn("b2", types)
        self.assertIn("drive", types)
        self.assertIn("onedrive", types)
        self.assertIn("sftp", types)
        self.assertIn("webdav", types)

    def test_rclone_remote_validation(self):
        # Invalid names
        with self.assertRaises(ValueError):
            self.rclone_engine.create_remote("invalid name with spaces", "s3", {})
        with self.assertRaises(ValueError):
            self.rclone_engine.create_remote("name/with/slashes", "s3", {})

    @patch("shutil.which", return_value="/usr/bin/rclone")
    @patch("subprocess.run")
    def test_rclone_list_remotes_sanitizes_secrets(self, mock_run, mock_which):
        # Mock rclone config dump output
        mock_output = {
            "my-s3": {
                "type": "s3",
                "provider": "AWS",
                "access_key_id": "AKIAIOSFODNN7EXAMPLE",
                "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            },
            "my-webdav": {
                "type": "webdav",
                "url": "https://nextcloud.lan/webdav",
                "pass": "SuperSecretPass123",
            },
        }
        import json

        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(mock_output), stderr="")
        with open(self.rclone_engine.config_file, "w") as f:
            f.write("# dummy")

        remotes = self.rclone_engine.list_remotes()
        self.assertEqual(len(remotes), 2)
        s3 = next(r for r in remotes if r["name"] == "my-s3")
        self.assertEqual(s3["parameters"]["secret_access_key"], "********")
        self.assertEqual(s3["parameters"]["access_key_id"], "AKIAIOSFODNN7EXAMPLE")

        wd = next(r for r in remotes if r["name"] == "my-webdav")
        self.assertEqual(wd["parameters"]["pass"], "********")

    def test_rclone_sync_job_lifecycle(self):
        job = self.rclone_engine.start_sync_job("/tmp/src", "/tmp/dst", action="copy", dry_run=True)
        self.assertIn("id", job)
        self.assertEqual(job["action"], "copy")
        self.assertTrue(job["dry_run"])

        jobs = self.rclone_engine.get_sync_jobs()
        self.assertGreater(len(jobs), 0)
        self.assertEqual(jobs[-1]["id"], job["id"])


def test_api_webdav_status(client, auth_headers):
    resp = client.get("/api/webdav/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "port" in data
    assert "quick_connect" in data


def test_api_webdav_toggle(client, auth_headers):
    resp = client.post("/api/webdav/toggle", json={"enabled": False}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False


def test_api_remotes_providers(client, auth_headers):
    resp = client.get("/api/remotes/providers", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(p["type"] == "s3" for p in data)


def test_api_remotes_list(client, auth_headers):
    resp = client.get("/api/remotes", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_remotes_create_validation_error(client, auth_headers):
    resp = client.post("/api/remotes", json={"name": "bad name!", "type": "s3", "parameters": {}}, headers=auth_headers)
    assert resp.status_code == 400
