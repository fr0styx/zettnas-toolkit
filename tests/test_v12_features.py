import json
import unittest
import urllib.request

from backend.db import init_db, log_copy_event, query_copy_history
from backend.hardware.unraid import read_unraid_status
from backend.state import Z_STATE


class TestV12Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_lcd_page_cycling(self):
        # Initial state
        Z_STATE.set_lcd_page(0)
        self.assertEqual(Z_STATE.current_lcd_page, 0)

        # Advance page
        p1 = Z_STATE.cycle_lcd_page()
        self.assertEqual(p1, 1)

        p2 = Z_STATE.cycle_lcd_page()
        self.assertEqual(p2, 2)

        p3 = Z_STATE.cycle_lcd_page()
        self.assertEqual(p3, 3)

        # Wrap around to 0
        p0 = Z_STATE.cycle_lcd_page()
        self.assertEqual(p0, 0)

        # Set specific page
        p_set = Z_STATE.set_lcd_page(2)
        self.assertEqual(p_set, 2)
        self.assertEqual(Z_STATE.current_lcd_page, 2)

    def test_copy_history_logging_and_query(self):
        ts = 1728100500
        log_copy_event(
            ts=ts,
            source="sd",
            dest="/mnt/user/Backups",
            files_count=15,
            total_bytes=52428800,
            status="success",
            checksum_verified=True,
            duration_sec=8.5,
            error="",
        )

        history = query_copy_history(limit=5)
        self.assertTrue(len(history) >= 1)
        found = [h for h in history if h["dest"] == "/mnt/user/Backups"]
        self.assertTrue(len(found) >= 1)
        item = found[0]
        self.assertEqual(item["source"], "sd")
        self.assertEqual(item["files_count"], 15)
        self.assertEqual(item["total_bytes"], 52428800)
        self.assertEqual(item["status"], "success")
        self.assertTrue(item["checksum_verified"])

    def test_unraid_status_reading(self):
        status = read_unraid_status(force=True)
        self.assertIn("available", status)
        self.assertIn("state", status)
        self.assertIn("color", status)
        self.assertIn("is_healthy", status)
        self.assertIn("disks", status)
        self.assertIn("parity_check", status)
        self.assertIn("mover", status)


if __name__ == "__main__":
    unittest.main()
