import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from backend.config import EVENTS_FILE, logger
from backend.fsutil import CORRUPT_LISTENERS, UNREADABLE_LISTENERS, atomic_write_json
from backend.settings import test_mode


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
    pending_usb: Any = None  # a USB disk offered for a backup or a photo import (FEAT-07)

    # The copy thread changes progress while the stats loop serialises it for the live view:
    # both go through these, under the lock (ARC-9), so a reader never sees the dict mid-change.
    def update(self, **fields: Any) -> None:
        with self.lock:
            self.progress.update(fields)

    def add(self, key: str, amount: int | float) -> None:
        with self.lock:
            self.progress[key] = self.progress.get(key, 0) + amount

    def start(self, **progress: Any) -> None:
        with self.lock:
            self.progress = dict(progress)

    def snapshot(self) -> dict[str, Any]:
        """A copy of the progress, safe to serialise while the copy runs."""
        with self.lock:
            return dict(self.progress)


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


class WakeEvent(threading.Event):
    """
    An Event that also sets its follower events. Several loops wait on ui_wake and the
    first one to wake clears it, so a loop that must never miss a wake-up gets its own
    follower event instead (the LCD: lcd_wake).
    """

    def __init__(self, *followers: threading.Event) -> None:
        super().__init__()
        self._followers = followers

    def set(self) -> None:
        super().set()
        for follower in self._followers:
            follower.set()


@dataclass
class LcdState:
    """The front LCD renderer and page cycling."""

    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    renderer_active: bool = False
    renderer: str = ""  # "chromium" or "pil" while running
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
    verdicts: dict[str, Any] = field(default_factory=dict)  # dev -> latest Drive Health verdict

    # ARC-33: every change goes through these, under the lock; readers that iterate take a copy
    def set_reading(self, dev: str, temp: Any, health: Any) -> None:
        with self.lock:
            self.cached_data[dev] = (temp, health)

    def set_time(self, dev: str, when: float) -> None:
        with self.lock:
            self.cached_time[dev] = when

    def set_scanned(self, dev: str, when: float) -> None:
        with self.lock:
            self.last_scan[dev] = when

    def set_risk(self, dev: str, risk: dict[str, Any]) -> None:
        with self.lock:
            self.disk_risk[dev] = risk

    def set_verdict(self, dev: str, verdict: dict[str, Any]) -> None:
        with self.lock:
            self.verdicts[dev] = verdict

    def start_test(self, dev: str, info: dict[str, Any]) -> None:
        with self.lock:
            self.active_tests[dev] = info

    def end_test(self, dev: str) -> None:
        with self.lock:
            self.active_tests.pop(dev, None)

    def update_test(self, dev: str, **changes: Any) -> None:
        with self.lock:
            if dev in self.active_tests:
                self.active_tests[dev] = {**self.active_tests[dev], **changes}

    def snapshot(self, name: str) -> dict[str, Any]:
        """A copy of one of the maps above, safe to iterate while the pollers write."""
        with self.lock:
            return dict(getattr(self, name))


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
    pending_usb = _Alias[Any]("copy", "pending_usb")
    fan_state_tracker = _Alias[dict]("fans", "tracker")
    known_active_fans = _Alias[set]("fans", "known_active")
    fans_released = _Alias[bool]("fans", "released")
    fans_locked = _Alias[bool]("fans", "locked")
    fan_driver_mode = _Alias[str]("fans", "driver_mode")
    critical_temp_active = _Alias[bool]("fans", "critical_temp_active")
    thermal_watchdog_engaged = _Alias[bool]("fans", "thermal_watchdog_engaged")
    lcd_renderer_active = _Alias[bool]("lcd", "renderer_active")
    lcd_renderer_name = _Alias[str]("lcd", "renderer")
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
    drive_verdicts = _Alias[dict]("smart", "verdicts")

    def __init__(self) -> None:
        self.lock = threading.RLock()  # the shared lock for everything not in a domain below
        self.copy = CopyState()
        self.fans = FanState()
        self.lcd = LcdState()
        self.ai = AiState()
        self.smart = SmartState()
        # lcd_wake: set by every ui_wake.set() and by each new stats sample; only the LCD clears it
        self.lcd_wake = threading.Event()
        self.lcd_blanked = False  # the LCD is off: stats samples don't wake it (PERF-20)
        self.ui_wake = WakeEvent(self.lcd_wake)
        self.prev: dict[str, Any] = {"idle": 0, "total": 0}
        self.prev_net: dict[str, Any] = {"time": 0.0, "rx": 0, "tx": 0, "iface": "bond0"}
        self.prev_net_ifaces: dict[str, Any] | None = None  # per-interface samples for the traffic rates
        self.discovered_host_ip: str | None = None  # found once by read_ip
        self.prev_disk_sectors: dict[str, Any] | None = None  # disk throughput samples (disks.py)
        self.prev_disk_time: float = 0.0
        self.disk_throughput: dict[str, Any] = {}
        self.zone_watchdog_engaged: dict[str, bool] = {}  # per fan zone (fans.py)
        self.last_monthly_smart: float = 0.0  # when the scheduled SMART tests last started
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


# The event file is written at most every few seconds, not on every event, and an unchanged
# condition (same level, title and message) is logged again only after an hour (PERF-27).
EVENT_FLUSH_SECS = 0.0 if test_mode() else 5.0
EVENT_REPEAT_SECS = 3600
_event_last_message: dict[tuple, str] = {}
_event_flush_timer: threading.Timer | None = None
_event_flush_lock = threading.Lock()


def events_snapshot() -> list[dict[str, Any]]:
    """The event log as it is now, safe to iterate (ARC-33)."""
    with Z_STATE.lock:
        return list(Z_STATE.event_log)


def clear_events() -> None:
    with Z_STATE.lock:
        Z_STATE.event_log = []


def flush_events() -> None:
    """Writes the event log now (the debounce timer, shutdown)."""
    global _event_flush_timer
    with _event_flush_lock:
        _event_flush_timer = None
    with Z_STATE.lock:
        events = list(Z_STATE.event_log)
    try:
        atomic_write_json(EVENTS_FILE, events)
    except OSError as e:
        logger.warning(f"Failed to save events: {e}")


def _persist_events_soon() -> None:
    global _event_flush_timer
    if EVENT_FLUSH_SECS <= 0:
        flush_events()
        return
    with _event_flush_lock:
        if _event_flush_timer is not None:
            return
        _event_flush_timer = threading.Timer(EVENT_FLUSH_SECS, flush_events)
        _event_flush_timer.daemon = True
        _event_flush_timer.start()


def add_event(level, title, message, details=None):
    global _event_dedup_cache
    now = int(time.time())
    events_to_persist = None
    with Z_STATE.lock:
        dedup_key = (level, title)
        last_seen = _event_dedup_cache.get(dedup_key, 0)
        quiet = EVENT_REPEAT_SECS if _event_last_message.get(dedup_key) == message else 60
        if now - last_seen < quiet:
            return
        _event_dedup_cache[dedup_key] = now
        _event_last_message[dedup_key] = message
        if len(_event_dedup_cache) > 200:
            _event_dedup_cache = {k: v for k, v in _event_dedup_cache.items() if now - v < EVENT_REPEAT_SECS}
            for k in list(_event_last_message):
                if k not in _event_dedup_cache:
                    _event_last_message.pop(k, None)

        entry = {"ts": now, "level": level, "title": title, "message": message}
        if details is not None:
            entry["details"] = details
        Z_STATE.event_log.insert(0, entry)
        Z_STATE.event_log = Z_STATE.event_log[:100]
        events_to_persist = list(Z_STATE.event_log)

    if events_to_persist is not None:
        _persist_events_soon()


def _record_damaged_file(path: str, dest: str) -> None:
    add_event(
        "error",
        "Damaged settings file",
        f"{os.path.basename(path)} was damaged and was set aside as {os.path.basename(dest)}; the newest good "
        "copy from the daily snapshot is used when there is one, otherwise its defaults.",
    )


CORRUPT_LISTENERS.append(_record_damaged_file)


def _record_unreadable_file(path: str, error: str) -> None:
    add_event(
        "error",
        "Settings file can't be opened",
        f"{os.path.basename(path)} exists but could not be opened ({error}). It was not changed; its "
        "defaults are used until it can be read again. Check the data folder's permissions and disk.",
    )


UNREADABLE_LISTENERS.append(_record_unreadable_file)
