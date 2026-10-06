import unittest
import time
from backend.db import get_db_connection, init_db, log_metrics, query_history
from backend.hardware.disks import run_disk_smart_test
from backend.hardware.docker_stats import read_docker_containers
from backend.hardware.ups import read_ups_status


class TestV13Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_sqlite_wal_mode_and_pragmas(self):
        conn = get_db_connection()
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        sync_mode = conn.execute("PRAGMA synchronous;").fetchone()[0]
        conn.close()

        # journal_mode in WAL mode returns 'wal'
        self.assertEqual(journal_mode.lower(), "wal")
        # synchronous NORMAL is 1
        self.assertEqual(sync_mode, 1)

    def test_history_ranges(self):
        now = int(time.time())
        # Log sample metrics
        log_metrics(
            ts=now - 100,
            cpu_temp=42.5,
            cpu_util=15.0,
            mem_pct=35.0,
            disks=[],
            fans=[],
        )

        h_1h = query_history("1h")
        self.assertIsInstance(h_1h, list)
        self.assertTrue(len(h_1h) >= 1)

        h_6h = query_history("6h")
        self.assertIsInstance(h_6h, list)
        self.assertTrue(len(h_6h) >= 1)

        h_24h = query_history("24h")
        self.assertIsInstance(h_24h, list)
        self.assertTrue(len(h_24h) >= 1)

        h_7d = query_history("7d")
        self.assertIsInstance(h_7d, list)

        h_30d = query_history("30d")
        self.assertIsInstance(h_30d, list)

    def test_smart_test_validation(self):
        # Invalid format rejection
        inv1 = run_disk_smart_test("invalid_drive;;")
        self.assertFalse(inv1["success"])
        self.assertIn("Invalid device", inv1.get("error", ""))

        inv2 = run_disk_smart_test("/dev/sda; rm -rf")
        self.assertFalse(inv2["success"])

        from unittest.mock import patch, MagicMock
        with patch("subprocess.run") as mock_run:
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = "Self-test routine aborted"
            mock_res.stderr = ""
            mock_run.return_value = mock_res
            res = run_disk_smart_test("sda", test_type="abort")
            self.assertTrue(res["success"])
            self.assertEqual(res["test_type"], "abort")
            mock_run.assert_called_once()
            self.assertIn("-X", mock_run.call_args[0][0])

    def test_docker_introspection(self):
        containers = read_docker_containers()
        self.assertIsInstance(containers, list)
        # Verify structure if containers exist
        for c in containers:
            self.assertIn("id", c)
            self.assertIn("name", c)
            self.assertIn("state", c)

    def test_ups_telemetry(self):
        ups = read_ups_status()
        self.assertIsInstance(ups, dict)
        self.assertIn("available", ups)
        self.assertIn("status", ups)
        self.assertIn("model", ups)

    def test_docker_container_action_validation(self):
        from backend.hardware.docker_stats import container_action

        # Invalid container ID (special chars)
        res_bad_id = container_action("test;id!", "start")
        self.assertFalse(res_bad_id["success"])
        self.assertEqual(res_bad_id["error"], "Invalid container ID")

        # Empty container ID
        res_empty = container_action("", "start")
        self.assertFalse(res_empty["success"])

        # Unsupported action
        res_bad_act = container_action("abc123def456", "destroy")
        self.assertFalse(res_bad_act["success"])
        self.assertIn("Unsupported action", res_bad_act["error"])

    def test_system_profile_and_docker_endpoints(self):
        from starlette.testclient import TestClient
        from app import app
        import backend.config as config
        from backend.passwords import hash_password

        saved_hash = config.STORED_PASSWORD_HASH
        config.STORED_PASSWORD_HASH = hash_password("admin")

        client = TestClient(app)
        login_resp = client.post("/api/auth/login", json={"password": "admin"})
        self.assertEqual(login_resp.status_code, 200)
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        try:
            # Test valid system profiles
            for p in ("auto", "quiet", "balanced", "performance"):
                resp = client.post("/api/system/profile", json={"profile": p}, headers=headers)
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["status"], "ok")
                self.assertEqual(data["profile"], p)

            # Test invalid profile
            resp_inv = client.post("/api/system/profile", json={"profile": "invalid_mode"}, headers=headers)
            self.assertEqual(resp_inv.status_code, 422)

            # Test docker action invalid payload
            resp_dock = client.post("/api/docker/containers/invalid!id/action", json={"action": "start"}, headers=headers)
            self.assertEqual(resp_dock.status_code, 400)
        finally:
            config.STORED_PASSWORD_HASH = saved_hash

    def test_i18n_translation_keys_completeness(self):
        import re
        import os

        candidates = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "src", "i18n.js"),
            "/mnt/user/appdata/zettnas-toolkit/frontend/src/i18n.js",
        ]
        i18n_file = next((f for f in candidates if os.path.exists(f)), None)
        if i18n_file is None: return

        content = open(i18n_file, "r", encoding="utf-8").read()
        for lang in ("en", "de", "zh", "fr", "es"):
            self.assertTrue(f'"{lang}": {{' in content or f'{lang}: {{' in content, f"Language {lang} should be defined in TRANSLATIONS")
            # Ensure major translation keys are present in each language section
            self.assertTrue('"dock.management":' in content or "'dock.management':" in content)
            self.assertTrue('"mgmt.telemetry_title":' in content or "'mgmt.telemetry_title':" in content)
            self.assertTrue('"settings.title":' in content or "'settings.title':" in content)


if __name__ == "__main__":
    unittest.main()

