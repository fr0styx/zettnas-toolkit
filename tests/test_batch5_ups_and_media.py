import os
import time
import unittest
from unittest.mock import MagicMock, patch

from backend.hardware.ups import _query_nut_socket, read_ups_status
from backend.services.alert_rules import (
    evaluate_system_alerts,
    get_failsafe_status,
    reset_failsafe_state,
)
from backend.services.copy_engine import (
    check_media_slot_transitions,
    reset_media_slot_state,
)
from backend.state import Z_STATE


class TestBatch5UpsAndMedia(unittest.TestCase):
    def setUp(self):
        reset_failsafe_state()
        reset_media_slot_state()
        Z_STATE.copy_active = False
        Z_STATE.copy_paused = False
        Z_STATE.copy_status = "idle"

    def tearDown(self):
        reset_failsafe_state()
        reset_media_slot_state()
        Z_STATE.copy_active = False
        Z_STATE.copy_paused = False

    # -------------------------------------------------------------------------
    # 1. Native NUT Protocol Socket Client Tests (B5_1)
    # -------------------------------------------------------------------------
    @patch("socket.socket")
    def test_nut_socket_parsing_and_auto_discovery(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value.__enter__.return_value = mock_sock

        # Simulate socket stream for:
        # 1. LIST UPS -> BEGIN LIST UPS ... UPS qnapups "UPS on QNAP" ... END LIST UPS
        # 2. LIST VAR qnapups -> BEGIN LIST VAR qnapups ... VAR ... END LIST VAR qnapups
        # 3. LOGOUT
        responses = [
            b"BEGIN LIST UPS\nUPS qnapups \"UPS on QNAP\"\nEND LIST UPS\n",
            (
                b"BEGIN LIST VAR qnapups\n"
                b"VAR qnapups battery.charge \"98.5\"\n"
                b"VAR qnapups battery.runtime \"2400\"\n"
                b"VAR qnapups ups.load \"18.2\"\n"
                b"VAR qnapups input.voltage \"120.5\"\n"
                b"VAR qnapups battery.voltage \"27.4\"\n"
                b"VAR qnapups ups.status \"OL CHRG\"\n"
                b"VAR qnapups ups.model \"CyberPower CP1500\"\n"
                b"VAR qnapups ups.mfr \"CyberPower Systems\"\n"
                b"END LIST VAR qnapups\n"
            ),
            b"OK Goodbye\n",
        ]
        mock_sock.recv.side_effect = responses

        res = _query_nut_socket("127.0.0.1", 3493)
        self.assertEqual(res.get("BCHARGE"), "98.5")
        self.assertEqual(res.get("TIMELEFT"), "40.0")  # 2400s / 60
        self.assertEqual(res.get("LOADPCT"), "18.2")
        self.assertEqual(res.get("LINEV"), "120.5")
        self.assertEqual(res.get("BATTV"), "27.4")
        self.assertEqual(res.get("STATUS"), "OL CHRG")
        self.assertEqual(res.get("MODEL"), "CyberPower CP1500")

    @patch("backend.hardware.ups._query_nut_socket")
    def test_read_ups_status_with_nut_driver(self, mock_nut_query):
        mock_nut_query.return_value = {
            "BCHARGE": "85.0",
            "TIMELEFT": "25.5",
            "LOADPCT": "12.0",
            "LINEV": "121.0",
            "BATTV": "13.6",
            "STATUS": "OL",
            "MODEL": "Eaton 5S",
        }

        with patch.dict(os.environ, {"UPS_TYPE": "nut", "NUT_PORT": "3493"}):
            status = read_ups_status(force=True)

        self.assertTrue(status["available"])
        self.assertEqual(status["protocol"], "nut_socket")
        self.assertEqual(status["model"], "Eaton 5S")
        self.assertEqual(status["battery_charge_pct"], 85.0)
        self.assertEqual(status["time_left_min"], 25.5)
        self.assertEqual(status["load_pct"], 12.0)
        self.assertEqual(status["line_volts"], 121.0)
        self.assertEqual(status["battery_volts"], 13.6)

    # -------------------------------------------------------------------------
    # 2. Automated UPS Failsafe Engine Tests (B5_2)
    # -------------------------------------------------------------------------
    @patch("os.sync")
    @patch("backend.services.notifications.send_notification")
    def test_ups_failsafe_engagement_and_recovery(self, mock_notify, mock_sync):
        unraid_ok = {"available": True, "state": "STARTED"}

        # 1. Normal Online Power
        ups_online = {
            "available": True,
            "status": "OL",
            "battery_charge_pct": 100.0,
            "time_left_min": 60.0,
        }
        evaluate_system_alerts(unraid_ok, ups_online)
        fs_state = get_failsafe_status()
        self.assertFalse(fs_state["failsafe_active"])
        self.assertFalse(Z_STATE.copy_paused)

        # 2. On Battery, but healthy charge (e.g., 75%, 35 min remaining)
        ups_onbatt_healthy = {
            "available": True,
            "status": "OB DISCHRG",
            "battery_charge_pct": 75.0,
            "time_left_min": 35.0,
        }
        evaluate_system_alerts(unraid_ok, ups_onbatt_healthy)
        fs_state = get_failsafe_status()
        self.assertFalse(fs_state["failsafe_active"])

        # 3. Simulate Active Copy Operation
        Z_STATE.copy_active = True
        Z_STATE.copy_paused = False
        Z_STATE.copy_status = "copying"

        # 4. Critical Low Battery Trigger (< 20% charge)
        ups_crit = {
            "available": True,
            "status": "OB LB DISCHRG",
            "battery_charge_pct": 15.0,
            "time_left_min": 3.5,
        }

        # Step 4a: First sample records timestamp for grace period
        with patch.dict(os.environ, {"UPS_FAILSAFE_GRACE_SEC": "10.0"}):
            evaluate_system_alerts(unraid_ok, ups_crit)
            # Before grace period finishes, failsafe should not engage yet
            self.assertFalse(get_failsafe_status()["failsafe_active"])
            self.assertFalse(Z_STATE.copy_paused)

            # Step 4b: Simulate time passing past grace period (12 seconds later)
            with patch("time.time", return_value=time.time() + 15.0):
                evaluate_system_alerts(unraid_ok, ups_crit)

        fs_state = get_failsafe_status()
        self.assertTrue(fs_state["failsafe_active"])
        self.assertTrue(fs_state["copy_paused_by_failsafe"])
        # Verify copy was paused to protect filesystem writes!
        self.assertTrue(Z_STATE.copy_paused)
        # Verify os.sync() was executed to flush disk caches!
        mock_sync.assert_called_once()
        # Verify critical notification was dispatched
        mock_notify.assert_called()

        # 5. Mains Power Restored (OL) -> Auto-recovery
        evaluate_system_alerts(unraid_ok, ups_online)
        fs_state_after = get_failsafe_status()
        self.assertFalse(fs_state_after["failsafe_active"])
        # Verify copy operation was automatically unpaused and resumed!
        self.assertFalse(Z_STATE.copy_paused)

    # -------------------------------------------------------------------------
    # 3. Media Slot Edge Detection & Auto-Ingest Tests (B5_3)
    # -------------------------------------------------------------------------
    @patch("backend.services.copy_engine.send_notification")
    def test_media_slot_insertion_and_removal_detection(self, mock_notify):
        # Initial empty state
        empty_slots = {
            "sd": {"size": 0, "dev": None},
            "tf": {"size": 0, "dev": None},
        }
        transitions = check_media_slot_transitions(empty_slots)
        self.assertEqual(len(transitions), 0)

        # Card inserted into SD slot: 0 -> 32GB
        inserted_sd = {
            "sd": {"size": 32 * 1024 * 1024 * 1024, "dev": "sdd"},
            "tf": {"size": 0, "dev": None},
        }
        transitions = check_media_slot_transitions(inserted_sd)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["event"], "inserted")
        self.assertEqual(transitions[0]["slot"], "sd")
        self.assertEqual(transitions[0]["dev"], "sdd")
        mock_notify.assert_called()

        # Subsequent check with card still inserted -> no new transition
        transitions = check_media_slot_transitions(inserted_sd)
        self.assertEqual(len(transitions), 0)

        # Card removed: 32GB -> 0
        transitions = check_media_slot_transitions(empty_slots)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["event"], "removed")
        self.assertEqual(transitions[0]["slot"], "sd")

    @patch("threading.Thread")
    @patch("backend.fsutil.read_json")
    def test_auto_ingest_triggers_direct_copy_when_confirmation_disabled(self, mock_read_json, mock_thread):
        mock_read_json.return_value = {
            "enabled": True,
            "auto_ingest": True,
            "require_confirmation": False,
            "source": "auto",
            "dest": "/mnt/user/photos",
            "use_exif": True,
            "verify_checksum": True,
            "on_collision": "skip",
        }

        inserted_tf = {
            "sd": {"size": 0, "dev": None},
            "tf": {"size": 64 * 1024 * 1024 * 1024, "dev": "sde"},
        }
        check_media_slot_transitions(inserted_tf)

        # Verify background copy thread was launched directly when confirmation is false
        mock_thread.assert_called_once()
        self.assertTrue(Z_STATE.copy_active)
        self.assertEqual(Z_STATE.copy_status, "copying")
        self.assertIsNone(Z_STATE.pending_ingest)

    @patch("threading.Thread")
    @patch("backend.fsutil.read_json")
    def test_auto_ingest_prompts_confirmation_by_default(self, mock_read_json, mock_thread):
        Z_STATE.copy_active = False
        Z_STATE.copy_status = "idle"
        Z_STATE.pending_ingest = None
        mock_read_json.return_value = {
            "enabled": True,
            "auto_ingest": True,
            "require_confirmation": True,
            "source": "auto",
            "dest": "/mnt/user/photos",
            "use_exif": True,
            "verify_checksum": True,
            "on_collision": "skip",
        }

        inserted_sd = {
            "sd": {"size": 32 * 1024 * 1024 * 1024, "dev": "sdf"},
            "tf": {"size": 0, "dev": None},
        }
        check_media_slot_transitions(inserted_sd)

        # Thread must NOT be launched automatically; pending_ingest must be set
        mock_thread.assert_not_called()
        self.assertFalse(Z_STATE.copy_active)
        self.assertIsNotNone(Z_STATE.pending_ingest)
        self.assertEqual(Z_STATE.pending_ingest["slot"], "sd")
        self.assertEqual(Z_STATE.pending_ingest["dest"], "/mnt/user/photos")

        # Card removal should clear pending_ingest
        empty_slots = {
            "sd": {"size": 0, "dev": None},
            "tf": {"size": 0, "dev": None},
        }
        check_media_slot_transitions(empty_slots)
        self.assertIsNone(Z_STATE.pending_ingest)

    @patch("backend.fsutil.read_json")
    def test_eject_slot_suppresses_reprompt_when_card_left_in(self, mock_read_json):
        from backend.services.copy_engine import _EJECTED_SLOTS, eject_media_slot

        Z_STATE.copy_active = False
        Z_STATE.copy_status = "idle"
        Z_STATE.pending_ingest = None
        mock_read_json.return_value = {
            "enabled": True,
            "auto_ingest": True,
            "require_confirmation": True,
            "source": "auto",
            "dest": "/mnt/user/photos",
        }

        inserted_sd = {
            "sd": {"size": 32 * 1024 * 1024 * 1024, "dev": "sdf"},
            "tf": {"size": 0, "dev": None},
        }

        # 1. Insert card -> pending ingest offered
        check_media_slot_transitions(inserted_sd)
        self.assertIsNotNone(Z_STATE.pending_ingest)

        # 2. User clicks EJECT while leaving card in slot
        eject_media_slot("sd")
        self.assertIsNone(Z_STATE.pending_ingest)
        self.assertIn("sd", _EJECTED_SLOTS)

        # 3. Next telemetry ticks occur while card remains in slot -> MUST NOT re-prompt
        check_media_slot_transitions(inserted_sd)
        self.assertIsNone(Z_STATE.pending_ingest)
        self.assertFalse(Z_STATE.copy_active)

        # 4. User physically removes card -> ejected state clears
        empty_slots = {
            "sd": {"size": 0, "dev": None},
            "tf": {"size": 0, "dev": None},
        }
        check_media_slot_transitions(empty_slots)
        self.assertNotIn("sd", _EJECTED_SLOTS)

        # 5. User re-inserts card -> prompt offered again
        check_media_slot_transitions(inserted_sd)
        self.assertIsNotNone(Z_STATE.pending_ingest)
        self.assertEqual(Z_STATE.pending_ingest["slot"], "sd")

    def test_button_config_schema_with_auto_ingest(self):
        from backend.models.schemas import ButtonConfigRequest

        req = ButtonConfigRequest(auto_ingest=True, require_confirmation=True, verify_checksum=True, source="tf")
        d = req.model_dump(exclude_unset=True)
        self.assertEqual(d["auto_ingest"], True)
        self.assertEqual(d["require_confirmation"], True)
        self.assertEqual(d["verify_checksum"], True)
        self.assertEqual(d["source"], "tf")


if __name__ == "__main__":
    unittest.main()
