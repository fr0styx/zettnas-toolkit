import time
import threading
from backend.config import logger
from backend.state import Z_STATE, add_event
from backend.hardware.disks import run_disk_smart_test, _discover_disks
from backend.hardware.unraid import read_unraid_status

def _run_scheduled_tasks():
    while True:
        now = time.time()
        time.sleep(3600)  # Check every hour
        
        # We could implement a full cron parser, but for now we'll do simple logic.
        # Example: Weekly health digest on Sunday at 12:00
        # Example: Short SMART test on all disks on the 1st of the month at 02:00
        
        t = time.localtime(now)
        
        # Monthly SMART short test at 2 AM on the 1st
        if t.tm_mday == 1 and t.tm_hour == 2:
            last_run = getattr(Z_STATE, "last_monthly_smart", 0)
            if now - last_run > 86400: # ensure it only runs once
                logger.info("[Scheduler] Starting monthly SMART short tests")
                Z_STATE.last_monthly_smart = now
                
                # Check unraid state, don't spin up disks if parity check is running
                unraid = read_unraid_status()
                if not unraid.get("parity_check_running"):
                    for d in _discover_disks():
                        run_disk_smart_test(d["dev"], "short")
                    add_event("info", "Scheduled Task", "Monthly SMART short tests started on all disks.")

def start_scheduler():
    t = threading.Thread(target=_run_scheduled_tasks, daemon=True, name="zett_scheduler")
    t.start()
