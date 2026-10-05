import json
import os
import threading
import time

from backend.config import EVENTS_FILE, logger
from backend.fsutil import atomic_write_json


class ZettState:
    def __init__(self):
        self.lock = threading.RLock()
        self.ui_wake = threading.Event()
        self.prev = {"idle": 0, "total": 0}
        self.prev_net = {"time": 0.0, "rx": 0, "tx": 0}
        self.prev_disk_io = {}
        self.cached_hwmon = None
        self.cached_cpu_temp_path = None
        self.known_active_fans = set()
        self.cached_disk_list = None
        self.cached_disk_list_time = 0.0
        self.cached_chassis_model = None
        self.lcd_renderer_active = False
        self.event_log = []
        self.alert_active = False
        self.rainbow_thread = None
        self.rainbow_stop = threading.Event()
        self.fan_state_tracker = {
            "zone1": {"target": 120, "active": 120, "hold_until": 0},
            "zone2": {"target": 120, "active": 120, "hold_until": 0},
            "zone3": {"target": 85, "active": 85, "hold_until": 0},
        }
        self.cached_smart_data = {}
        self.copy_active = False
        self.copy_status = "idle"
        self.copy_progress = {}
        self.copy_paused = False
        self.copy_confirm_event = threading.Event()
        self.copy_overwrite_choice = "cancel"
        self.copy_abort_flag = False
        self.cached_stats = None
        self.static_cache = {}
        self.fans_released = False
        self.fans_locked = False
        self.shutting_down = False
        self.collector_heartbeat = 0.0
        self.critical_temp_active = False


Z_STATE = ZettState()


def _load_events():
    try:
        if os.path.exists(EVENTS_FILE):
            with open(EVENTS_FILE) as f:
                Z_STATE.event_log = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load events: {e}")


def add_event(level, title, message, details=None):
    now = int(time.time())
    with Z_STATE.lock:
        if (
            Z_STATE.event_log
            and Z_STATE.event_log[0].get("title") == title
            and Z_STATE.event_log[0].get("message") == message
            and (now - Z_STATE.event_log[0].get("ts", 0) < 3600)
        ):
            return
        entry = {"ts": now, "level": level, "title": title, "message": message}
        if details is not None:
            entry["details"] = details
        Z_STATE.event_log.insert(0, entry)
        Z_STATE.event_log = Z_STATE.event_log[:100]
        try:
            atomic_write_json(EVENTS_FILE, Z_STATE.event_log)
        except OSError as e:
            logger.warning(f"Failed to save events: {e}")
