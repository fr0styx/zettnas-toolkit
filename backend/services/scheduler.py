import threading
import time
from typing import Any, Dict

from backend.config import SMART_SCHEDULE_FILE, logger
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.disks import _discover_disks, run_disk_smart_test
from backend.hardware.unraid import read_unraid_status
from backend.state import Z_STATE, add_event

_SCHEDULER_STOP_EVENT = threading.Event()
_SCHEDULER_THREAD: threading.Thread | None = None

DEFAULT_SMART_SCHEDULE: Dict[str, Any] = {
    "enabled": True,
    "short_test_interval": "monthly",  # "disabled", "daily", "weekly", "monthly"
    "short_test_day": 1,  # Day of month (1-28) or day of week (0=Mon, 6=Sun)
    "short_test_hour": 2,  # 0-23
    "extended_test_interval": "monthly",  # "disabled", "monthly"
    "extended_test_day": 15,  # 15th of the month
    "extended_test_hour": 3,  # 3 AM
    "skip_if_standby": True,  # INVIOLABLE: never wake sleeping disks
    "last_short_run": 0,
    "last_extended_run": 0,
}


def get_smart_schedule() -> Dict[str, Any]:
    """Retrieve the current SMART testing schedule with defaults fallback."""
    cfg = read_json(SMART_SCHEDULE_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}
    merged = dict(DEFAULT_SMART_SCHEDULE)
    merged.update(cfg)
    return merged


def save_smart_schedule(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Persist updated SMART test schedule configuration."""
    current = get_smart_schedule()

    # Validate interval options
    valid_short = {"disabled", "daily", "weekly", "monthly"}
    valid_ext = {"disabled", "monthly"}

    short_int = str(cfg.get("short_test_interval", current["short_test_interval"])).lower()
    ext_int = str(cfg.get("extended_test_interval", current["extended_test_interval"])).lower()

    if short_int not in valid_short:
        short_int = "monthly"
    if ext_int not in valid_ext:
        ext_int = "monthly"

    current["enabled"] = bool(cfg.get("enabled", current.get("enabled", True)))
    current["short_test_interval"] = short_int
    current["short_test_day"] = max(0, min(31, int(cfg.get("short_test_day", current["short_test_day"]))))
    current["short_test_hour"] = max(0, min(23, int(cfg.get("short_test_hour", current["short_test_hour"]))))
    current["extended_test_interval"] = ext_int
    current["extended_test_day"] = max(1, min(31, int(cfg.get("extended_test_day", current["extended_test_day"]))))
    current["extended_test_hour"] = max(0, min(23, int(cfg.get("extended_test_hour", current["extended_test_hour"]))))
    current["skip_if_standby"] = bool(cfg.get("skip_if_standby", True))

    if "last_short_run" in cfg:
        current["last_short_run"] = float(cfg["last_short_run"])
    if "last_extended_run" in cfg:
        current["last_extended_run"] = float(cfg["last_extended_run"])

    atomic_write_json(SMART_SCHEDULE_FILE, current)
    return current


def _run_scheduled_tasks():
    logger.info("[Scheduler] System background scheduler started.")
    while not _SCHEDULER_STOP_EVENT.is_set():
        if _SCHEDULER_STOP_EVENT.wait(60):
            break

        now = time.time()
        t = time.localtime(now)
        cfg = get_smart_schedule()

        if not cfg.get("enabled", True):
            continue

        skip_standby = bool(cfg.get("skip_if_standby", True))

        # 1. Short SMART Test evaluation
        short_interval = cfg.get("short_test_interval", "monthly")
        short_day = int(cfg.get("short_test_day", 1))
        short_hour = int(cfg.get("short_test_hour", 2))
        last_short = float(cfg.get("last_short_run", 0))

        should_run_short = False
        if short_interval != "disabled" and (now - last_short > 86400):
            if short_interval == "daily" and t.tm_hour == short_hour:
                should_run_short = True
            elif short_interval == "weekly" and t.tm_wday == (short_day % 7) and t.tm_hour == short_hour:
                should_run_short = True
            elif short_interval == "monthly" and t.tm_mday == short_day and t.tm_hour == short_hour:
                should_run_short = True

        if should_run_short:
            unraid = read_unraid_status()
            if not unraid.get("parity_check_running"):
                logger.info("[Scheduler] Starting scheduled SMART short tests")
                cfg["last_short_run"] = now
                save_smart_schedule(cfg)
                Z_STATE.last_monthly_smart = now

                disks = _discover_disks()
                for d in disks:
                    run_disk_smart_test(d["dev"], "short", skip_if_standby=skip_standby)
                add_event(
                    "info",
                    "Scheduled Task",
                    f"Scheduled SMART short tests started for {len(disks)} disks (sleeping disks preserved: {skip_standby}).",
                )

        # 2. Extended SMART Test evaluation
        ext_interval = cfg.get("extended_test_interval", "monthly")
        ext_day = int(cfg.get("extended_test_day", 15))
        ext_hour = int(cfg.get("extended_test_hour", 3))
        last_ext = float(cfg.get("last_extended_run", 0))

        should_run_ext = False
        if ext_interval != "disabled" and (now - last_ext > 86400):
            if ext_interval == "monthly" and t.tm_mday == ext_day and t.tm_hour == ext_hour:
                should_run_ext = True

        if should_run_ext:
            unraid = read_unraid_status()
            if not unraid.get("parity_check_running"):
                logger.info("[Scheduler] Starting scheduled SMART extended tests")
                cfg["last_extended_run"] = now
                save_smart_schedule(cfg)

                disks = _discover_disks()
                for d in disks:
                    run_disk_smart_test(d["dev"], "long", skip_if_standby=skip_standby)
                add_event(
                    "info",
                    "Scheduled Task",
                    f"Scheduled SMART extended tests started for {len(disks)} disks (sleeping disks preserved: {skip_standby}).",
                )


def start_scheduler():
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
        return
    _SCHEDULER_STOP_EVENT.clear()
    _SCHEDULER_THREAD = threading.Thread(target=_run_scheduled_tasks, daemon=True, name="zett_scheduler")
    _SCHEDULER_THREAD.start()


def stop_scheduler():
    _SCHEDULER_STOP_EVENT.set()
