import time
import threading
from backend.config import logger
from backend.state import Z_STATE, add_event
from backend.hardware.disks import run_disk_smart_test, _discover_disks
from backend.hardware.unraid import read_unraid_status


_SCHEDULER_STOP_EVENT = threading.Event()
_SCHEDULER_THREAD: threading.Thread | None = None


def _run_scheduled_tasks():
    logger.info("[Scheduler] System background scheduler started.")
    while not _SCHEDULER_STOP_EVENT.is_set():
        if _SCHEDULER_STOP_EVENT.wait(60):
            break

        now = time.time()
        t = time.localtime(now)

        # Monthly SMART short test at 2 AM on the 1st
        if t.tm_mday == 1 and t.tm_hour == 2:
            last_run = getattr(Z_STATE, "last_monthly_smart", 0)
            if now - last_run > 86400:  # ensure it only runs once per day
                logger.info("[Scheduler] Starting monthly SMART short tests")
                Z_STATE.last_monthly_smart = now

                # Check unraid state, don't spin up disks if parity check is running
                unraid = read_unraid_status()
                if not unraid.get("parity_check_running"):
                    for d in _discover_disks():
                        run_disk_smart_test(d["dev"], "short", skip_if_standby=True)
                    add_event("info", "Scheduled Task", "Monthly SMART short tests started (sleeping disks preserved).")


def start_scheduler():
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
        return
    _SCHEDULER_STOP_EVENT.clear()
    _SCHEDULER_THREAD = threading.Thread(target=_run_scheduled_tasks, daemon=True, name="zett_scheduler")
    _SCHEDULER_THREAD.start()


def stop_scheduler():
    _SCHEDULER_STOP_EVENT.set()
