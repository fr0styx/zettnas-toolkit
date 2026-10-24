import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from backend.config import EVENTS_FILE, logger
from backend.fsutil import atomic_write_json


def _fan_tracker(now: float) -> dict[str, dict[str, float]]:
    def one(current: int) -> dict[str, float]:
        return {
            "current": current,
            "last_up_time": 0.0,
            "kickstart_until": 0.0,
            "last_spinup_time": now,
            "standby_since": 0.0,
        }

    return {"pwm1": one(67), "pwm2": one(67), "pwm3": one(85)}


# Typed state per domain, each with its own lock (ARCH-5). New code uses Z_STATE.copy.active
# under Z_STATE.copy.lock; the flat names (Z_STATE.copy_active) stay as typed aliases.
@dataclass
class CopyState:
    """The front-panel copy and media import."""

    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    active: bool = False
    status: str = "idle"
    progress: dict[str, Any] = field(default_factory=dict)
    paused: bool = False
    confirm_event: threading.Event = field(default_factory=threading.Event, repr=False)
    overwrite_choice: str = "cancel"
    abort_flag: bool = False
    pending_ingest: Any = None


@dataclass
class FanState:
    """Fan control: per-channel tracking, driver mode and the safety overrides."""

    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    tracker: dict[str, dict[str, float]] = field(default_factory=lambda: _fan_tracker(time.time()))
    known_active: set[int] = field(default_factory=set)
    released: bool = False
    locked: bool = False
    driver_mode: str = "none"
    critical_temp_active: bool = False
    thermal_watchdog_engaged: bool = False


@dataclass
class LcdState:
    """The front LCD renderer and page cycling."""

    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    renderer_active: bool = False
    current_page: int = 0
    cycle_seconds: int = 0
    last_cycle_time: float = field(default_factory=time.time)


@dataclass
class AiState:
    """What the AI is doing right now, for the accelerator gauges."""

    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    active: bool = False
    accelerator: str = ""
    model: str = ""


@dataclass
class SmartState:
    """SMART readings, failure-risk estimates and running self-tests."""

    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    cached_data: dict[str, Any] = field(default_factory=dict)
    cached_time: dict[str, float] = field(default_factory=dict)
    disk_risk: dict[str, Any] = field(default_factory=dict)  # dev -> predicted failure risk (D6)
    last_scan: dict[str, float] = field(default_factory=dict)
    active_tests: dict[str, Any] = field(default_factory=dict)


class _Alias[T]:
    """Z_STATE.copy_active reads and writes Z_STATE.copy.active."""

    def __init__(self, domain: str, name: str) -> None:
        self.domain, self.name = domain, name

    def __get__(self, obj: Any, objtype: Any = None) -> T:
        if obj is None:
            return self  # type: ignore[return-value]
        return getattr(getattr(obj, self.domain), self.name)

    def __set__(self, obj: Any, value: T) -> None:
        setattr(getattr(obj, self.domain), self.name, value)


class ZettState:
    # flat names kept for existing code (typed aliases of the domain fields)
    copy_active = _Alias[bool]("copy", "active")
    copy_status = _Alias[str]("copy", "status")
    copy_progress = _Alias[dict]("copy", "progress")
    copy_paused = _Alias[bool]("copy", "paused")
    copy_confirm_event = _Alias[threading.Event]("copy", "confirm_event")
    copy_overwrite_choice = _Alias[str]("copy", "overwrite_choice")
    copy_abort_flag = _Alias[bool]("copy", "abort_flag")
    pending_ingest = _Alias[Any]("copy", "pending_ingest")
    fan_state_tracker = _Alias[dict]("fans", "tracker")
    known_active_fans = _Alias[set]("fans", "known_active")
    fans_released = _Alias[bool]("fans", "released")
    fans_locked = _Alias[bool]("fans", "locked")
    fan_driver_mode = _Alias[str]("fans", "driver_mode")
    critical_temp_active = _Alias[bool]("fans", "critical_temp_active")
    thermal_watchdog_engaged = _Alias[bool]("fans", "thermal_watchdog_engaged")
    lcd_renderer_active = _Alias[bool]("lcd", "renderer_active")
    current_lcd_page = _Alias[int]("lcd", "current_page")
    lcd_cycle_seconds = _Alias[int]("lcd", "cycle_seconds")
    last_lcd_cycle_time = _Alias[float]("lcd", "last_cycle_time")
    ai_active = _Alias[bool]("ai", "active")
    ai_accelerator = _Alias[str]("ai", "accelerator")
    ai_model = _Alias[str]("ai", "model")
    cached_smart_data = _Alias[dict]("smart", "cached_data")
    cached_smart_time = _Alias[dict]("smart", "cached_time")
    disk_risk = _Alias[dict]("smart", "disk_risk")
    last_smart_scan = _Alias[dict]("smart", "last_scan")
    active_smart_tests = _Alias[dict]("smart", "active_tests")

    def __init__(self) -> None:
        self.lock = threading.RLock()  # the shared lock for everything not in a domain below
        self.copy = CopyState()
        self.fans = FanState()
        self.lcd = LcdState()
        self.ai = AiState()
        self.smart = SmartState()
        self.ui_wake = threading.Event()
        self.prev: dict[str, Any] = {"idle": 0, "total": 0}
        self.prev_net: dict[str, Any] = {"time": 0.0, "rx": 0, "tx": 0, "iface": "bond0"}
        self.prev_disk_io: dict[str, Any] = {}
        self.cached_hwmon: Any = None
        self.cached_cpu_temp_path: str | None = None
        self.cached_disk_list: Any = None
        self.cached_disk_list_time = 0.0
        self.cached_chassis_model: str | None = None
        self.client_preferences: Any = None
        self.event_log: list[dict[str, Any]] = []
        self.alert_active = False
        self.rainbow_thread: threading.Thread | None = None
        self.rainbow_stop = threading.Event()
        self.boot_time = time.time()
        self.cached_stats: dict[str, Any] | None = None
        self.static_cache: dict[str, Any] = {}
        self.shutting_down = False
        self.collector_heartbeat = 0.0

    def cycle_lcd_page(self, count: int = 4) -> int:
        with self.lcd.lock:
            self.lcd.current_page = (self.lcd.current_page + 1) % count
            self.lcd.last_cycle_time = time.time()
        self.ui_wake.set()
        return self.lcd.current_page

    def set_lcd_page(self, page: int, count: int = 4) -> int:
        with self.lcd.lock:
            self.lcd.current_page = max(0, min(count - 1, int(page)))
            self.lcd.last_cycle_time = time.time()
        self.ui_wake.set()
        return self.lcd.current_page


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
