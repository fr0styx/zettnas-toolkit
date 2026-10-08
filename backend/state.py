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
        self.prev_net = {"time": 0.0, "rx": 0, "tx": 0, "iface": "bond0"}
        self.prev_disk_io = {}
        self.cached_hwmon = None
        self.cached_cpu_temp_path = None
        self.known_active_fans = set()
        self.cached_disk_list = None
        self.cached_disk_list_time = 0.0
        self.cached_chassis_model = None
        self.lcd_renderer_active = False
        self.client_preferences = None
        self.event_log = []
        self.alert_active = False
        self.rainbow_thread = None
        self.rainbow_stop = threading.Event()
        now = time.time()
        self.boot_time = now
        self.fan_state_tracker = {
            "pwm1": {
                "current": 67,
                "last_up_time": 0.0,
                "kickstart_until": 0.0,
                "last_spinup_time": now,
                "standby_since": 0.0,
            },
            "pwm2": {
                "current": 67,
                "last_up_time": 0.0,
                "kickstart_until": 0.0,
                "last_spinup_time": now,
                "standby_since": 0.0,
            },
            "pwm3": {
                "current": 85,
                "last_up_time": 0.0,
                "kickstart_until": 0.0,
                "last_spinup_time": now,
                "standby_since": 0.0,
            },
        }
        self.cached_smart_data = {}
        self.cached_smart_time = {}
        self.last_smart_scan = {}
        self.copy_active = False
        self.copy_status = "idle"
        self.copy_progress = {}
        self.copy_paused = False
        self.copy_confirm_event = threading.Event()
        self.copy_overwrite_choice = "cancel"
        self.copy_abort_flag = False
        self.pending_ingest = None
        self.cached_stats = None
        self.static_cache = {}
        self.fans_released = False
        self.fans_locked = False
        self.shutting_down = False
        self.collector_heartbeat = 0.0
        self.critical_temp_active = False
        self.thermal_watchdog_engaged = False
        self.current_lcd_page = 0
        self.lcd_cycle_seconds = 0
        self.last_lcd_cycle_time = time.time()

    def cycle_lcd_page(self, count: int = 4) -> int:
        with self.lock:
            self.current_lcd_page = (self.current_lcd_page + 1) % count
            self.last_lcd_cycle_time = time.time()
        self.ui_wake.set()
        return self.current_lcd_page

    def set_lcd_page(self, page: int, count: int = 4) -> int:
        with self.lock:
            self.current_lcd_page = max(0, min(count - 1, int(page)))
            self.last_lcd_cycle_time = time.time()
        self.ui_wake.set()
        return self.current_lcd_page


Z_STATE = ZettState()


def _load_events():
    try:
        if os.path.exists(EVENTS_FILE):
            with open(EVENTS_FILE) as f:
                Z_STATE.event_log = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load events: {e}")


_event_dedup_cache = {}


def add_event(level, title, message, details=None):
    global _event_dedup_cache
    now = int(time.time())
    events_to_persist = None
    with Z_STATE.lock:
        dedup_key = (level, title)
        last_seen = _event_dedup_cache.get(dedup_key, 0)
        if now - last_seen < 60:
            return
        _event_dedup_cache[dedup_key] = now
        if len(_event_dedup_cache) > 200:
            _event_dedup_cache = {k: v for k, v in _event_dedup_cache.items() if now - v < 300}

        entry = {"ts": now, "level": level, "title": title, "message": message}
        if details is not None:
            entry["details"] = details
        Z_STATE.event_log.insert(0, entry)
        Z_STATE.event_log = Z_STATE.event_log[:100]
        events_to_persist = list(Z_STATE.event_log)

    if events_to_persist is not None:
        try:
            atomic_write_json(EVENTS_FILE, events_to_persist)
        except OSError as e:
            logger.warning(f"Failed to save events: {e}")
