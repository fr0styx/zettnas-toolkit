import threading
import time
from typing import Any

from backend.config import SMART_SCHEDULE_FILE, logger
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.hardware.disks import _discover_disks, run_disk_smart_test
from backend.hardware.unraid import read_unraid_status
from backend.state import Z_STATE, add_event

_SCHEDULER_STOP_EVENT = threading.Event()
_SCHEDULER_THREAD: threading.Thread | None = None

DEFAULT_SMART_SCHEDULE: dict[str, Any] = {
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
    "scrub_interval": "disabled",  # "disabled", "monthly"
    "scrub_day": 1,  # 1st of month
    "scrub_hour": 4,  # 4 AM
    "last_scrub_run": 0,
}


def get_smart_schedule() -> dict[str, Any]:
    """Retrieve the current SMART testing schedule with defaults fallback."""
    cfg = read_json(SMART_SCHEDULE_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}
    merged = dict(DEFAULT_SMART_SCHEDULE)
    merged.update(cfg)
    return merged


@json_locked(lambda *a, **k: SMART_SCHEDULE_FILE)
def save_smart_schedule(cfg: dict[str, Any]) -> dict[str, Any]:
    """Persist updated SMART test and storage scrub schedule configuration."""
    current = get_smart_schedule()

    # Validate interval options
    valid_short = {"disabled", "daily", "weekly", "monthly"}
    valid_ext = {"disabled", "monthly"}
    valid_scrub = {"disabled", "monthly"}

    short_int = str(cfg.get("short_test_interval", current["short_test_interval"])).lower()
    ext_int = str(cfg.get("extended_test_interval", current["extended_test_interval"])).lower()
    scrub_int = str(cfg.get("scrub_interval", current.get("scrub_interval", "disabled"))).lower()

    if short_int not in valid_short:
        short_int = "monthly"
    if ext_int not in valid_ext:
        ext_int = "monthly"
    if scrub_int not in valid_scrub:
        scrub_int = "disabled"

    current["enabled"] = bool(cfg.get("enabled", current.get("enabled", True)))
    current["short_test_interval"] = short_int
    current["short_test_day"] = max(0, min(31, int(cfg.get("short_test_day", current["short_test_day"]))))
    current["short_test_hour"] = max(0, min(23, int(cfg.get("short_test_hour", current["short_test_hour"]))))
    current["extended_test_interval"] = ext_int
    current["extended_test_day"] = max(1, min(31, int(cfg.get("extended_test_day", current["extended_test_day"]))))
    current["extended_test_hour"] = max(0, min(23, int(cfg.get("extended_test_hour", current["extended_test_hour"]))))
    current["skip_if_standby"] = bool(cfg.get("skip_if_standby", True))
    current["scrub_interval"] = scrub_int
    current["scrub_day"] = max(1, min(31, int(cfg.get("scrub_day", current.get("scrub_day", 1)))))
    current["scrub_hour"] = max(0, min(23, int(cfg.get("scrub_hour", current.get("scrub_hour", 4)))))

    if "last_short_run" in cfg:
        current["last_short_run"] = float(cfg["last_short_run"])
    if "last_extended_run" in cfg:
        current["last_extended_run"] = float(cfg["last_extended_run"])
    if "last_scrub_run" in cfg:
        current["last_scrub_run"] = float(cfg["last_scrub_run"])

    atomic_write_json(SMART_SCHEDULE_FILE, current)
    return current


_LAST_AI_RETENTION = {"at": 0.0}


def _run_ai_retention(now: float) -> None:
    """Hourly: delete AI conversations older than the configured retention (AI-20)."""
    if now - _LAST_AI_RETENTION["at"] < 3600:
        return
    _LAST_AI_RETENTION["at"] = now
    try:
        from backend.services.ai_conversations_db import purge_conversations_older_than
        from backend.services.rag_engine import get_rag_engine

        days = int(get_rag_engine().get_config().get("conversation_retention_days") or 0)
        if days > 0:
            n = purge_conversations_older_than(days)
            if n:
                logger.info(f"[Scheduler] Deleted {n} AI conversation(s) older than {days} days.")
    except Exception as e:
        logger.warning(f"[Scheduler] AI conversation retention failed: {e}")


def _run_alert_retries(now: float) -> None:
    """Alerts that could not be sent are tried again (REL-22)."""
    try:
        from backend.services.notifications import retry_outbox

        retry_outbox(now)
    except Exception as e:
        logger.warning(f"[Scheduler] Alert retries failed: {e}")


def _run_replication(now: float) -> None:
    """Replication jobs on their schedule (REL-5)."""
    try:
        from backend.services.replication_engine import get_replication_engine

        get_replication_engine().run_due(now)
    except Exception as e:
        logger.warning(f"[Scheduler] Replication schedules failed: {e}")


def _run_pool_checks(now: float) -> None:
    """Degraded pools, disks, scrub errors and full pools (REL-11), and the weekly report."""
    try:
        from backend.services import pool_alerts

        pool_alerts.check_and_alert(now)
        pool_alerts.send_weekly_if_due(now)
    except Exception as e:
        logger.warning(f"[Scheduler] Pool health check failed: {e}")
    try:
        from backend.services import protection_jobs

        protection_jobs.run_scrubs_due(now)  # monthly scrubs where ZettNAS owns the pools (REL-12)
    except Exception as e:
        logger.warning(f"[Scheduler] Monthly scrub failed: {e}")


def _run_usb_disks() -> None:
    """A newly plugged-in USB disk is offered for a backup or a photo import (FEAT-07), and
    two-way cloud syncs run when due (FEAT-06)."""
    try:
        from backend.services import usb_copy

        usb_copy.tick()
    except (OSError, ValueError, KeyError, LookupError, RuntimeError) as e:
        logger.warning("[Scheduler] USB disk check failed: %s", e)
    try:
        from backend.services import two_way_sync

        two_way_sync.run_due()
    except (OSError, ValueError, KeyError, RuntimeError) as e:
        logger.warning("[Scheduler] Two-way sync failed: %s", e)
    try:
        from backend.services import frigate_events

        frigate_events.tick()  # camera detections as alerts (COMP-11); nothing to do when off
    except (OSError, ValueError, KeyError, RuntimeError) as e:
        logger.warning("[Scheduler] Frigate events failed: %s", e)


def _run_scheduled_tasks():
    logger.info("[Scheduler] System background scheduler started.")
    from backend.services.supervisor import beat

    while not _SCHEDULER_STOP_EVENT.is_set():
        beat("TaskScheduler")
        if _SCHEDULER_STOP_EVENT.wait(60):
            break

        now = time.time()
        t = time.localtime(now)
        _run_ai_retention(now)
        try:
            from backend.services.snapshot_service import run_due

            run_due(now)
        except Exception as e:
            logger.warning(f"[Scheduler] Snapshot schedules failed: {e}")
        try:
            from backend.services.backup_migration import retire_replaced_jobs
            from backend.services.offsite_backup import run_due as run_offsite

            run_offsite(now)
            retire_replaced_jobs()  # a moved copy job goes off after the first good backup (NREL-19)
        except Exception as e:
            logger.warning(f"[Scheduler] Offsite backups failed: {e}")
        try:
            from backend.services.notifications import send_digest_if_due

            send_digest_if_due(now)
        except Exception as e:
            logger.warning(f"[Scheduler] Notification digest failed: {e}")
        _run_pool_checks(now)
        _run_alert_retries(now)
        _run_replication(now)
        _run_usb_disks()
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
            if (
                short_interval == "daily"
                and t.tm_hour == short_hour
                or short_interval == "weekly"
                and t.tm_wday == (short_day % 7)
                and t.tm_hour == short_hour
                or short_interval == "monthly"
                and t.tm_mday == short_day
                and t.tm_hour == short_hour
            ):
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

        # 3. Storage Scrub evaluation
        scrub_interval = cfg.get("scrub_interval", "disabled")
        scrub_day = int(cfg.get("scrub_day", 1))
        scrub_hour = int(cfg.get("scrub_hour", 4))
        last_scrub = float(cfg.get("last_scrub_run", 0))

        should_run_scrub = False
        if scrub_interval != "disabled" and (now - last_scrub > 86400):
            if scrub_interval == "monthly" and t.tm_mday == scrub_day and t.tm_hour == scrub_hour:
                should_run_scrub = True

        if should_run_scrub:
            from backend.hardware.pal_storage import get_storage_platform

            adapter = get_storage_platform()
            caps = adapter.get_capabilities()
            if not caps.can_trigger_scrub:
                logger.info(
                    f"[Scheduler] Skipping scheduled scrub: platform {adapter.get_platform_type().value} does not permit direct scrub."
                )
            elif not adapter.is_storage_busy():
                logger.info("[Scheduler] Starting scheduled storage scrub")
                cfg["last_scrub_run"] = now
                save_smart_schedule(cfg)
                res = adapter.trigger_scrub(pool_id="default", action="start")
                add_event(
                    "info",
                    "Scheduled Task",
                    f"Scheduled storage scrub initiated on {adapter.get_platform_type().value}: {res.get('message', 'Started')}",
                )


def scheduler_daemon():
    """The task scheduler loop for the supervisor: restarted if it crashes (ARC-10)."""
    _SCHEDULER_STOP_EVENT.clear()
    _run_scheduled_tasks()


def start_scheduler():
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
        return
    _SCHEDULER_STOP_EVENT.clear()
    _SCHEDULER_THREAD = threading.Thread(target=_run_scheduled_tasks, daemon=True, name="zett_scheduler")
    _SCHEDULER_THREAD.start()


def stop_scheduler():
    _SCHEDULER_STOP_EVENT.set()
