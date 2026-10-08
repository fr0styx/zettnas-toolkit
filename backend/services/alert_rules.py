import os
import threading
import time
from backend.config import logger
from backend.state import Z_STATE, add_event

_active_alerts = {}

# UPS Failsafe state tracking
_failsafe_active = False
_low_batt_start_ts: float | None = None
_copy_paused_by_failsafe = False


def get_failsafe_status() -> dict:
    """Returns current UPS failsafe engine telemetry and configuration."""
    return {
        "failsafe_active": _failsafe_active,
        "copy_paused_by_failsafe": _copy_paused_by_failsafe,
        "low_batt_start_ts": _low_batt_start_ts,
        "battery_threshold": float(os.getenv("UPS_FAILSAFE_BATTERY_MIN", "20.0")),
        "runtime_threshold": float(os.getenv("UPS_FAILSAFE_RUNTIME_MIN", "5.0")),
        "grace_period_sec": float(os.getenv("UPS_FAILSAFE_GRACE_SEC", "15.0")),
    }


def reset_failsafe_state() -> None:
    """Reset failsafe state (useful for test suites)."""
    global _failsafe_active, _low_batt_start_ts, _copy_paused_by_failsafe, _active_alerts
    _failsafe_active = False
    _low_batt_start_ts = None
    _copy_paused_by_failsafe = False
    _active_alerts.clear()


def evaluate_system_alerts(unraid_data, ups_data):
    """Evaluates built-in rules for system alerts, debounces them, and triggers automated failsafes."""
    global _failsafe_active, _low_batt_start_ts, _copy_paused_by_failsafe
    now = time.time()

    # 1. Unraid Array
    if unraid_data.get("available"):
        state = unraid_data.get("state", "").upper()
        if state == "ERROR":
            _trigger_alert(
                "unraid_error", "Unraid Array Error", "The Unraid array has encountered an error state.", "error", now
            )
        else:
            _resolve_alert("unraid_error")

    # 2. UPS Power & Automated Failsafes
    if ups_data.get("available"):
        status = ups_data.get("status", "").upper()
        charge = ups_data.get("battery_charge_pct")
        runtime = ups_data.get("time_left_min")

        batt_thresh = float(os.getenv("UPS_FAILSAFE_BATTERY_MIN", "20.0"))
        time_thresh = float(os.getenv("UPS_FAILSAFE_RUNTIME_MIN", "5.0"))
        grace_period = float(os.getenv("UPS_FAILSAFE_GRACE_SEC", "15.0"))
        shutdown_enabled = os.getenv("UPS_FAILSAFE_SHUTDOWN", "0").lower() in ("1", "true", "yes")

        is_on_batt = any(k in status for k in ("OB", "ONBATT", "ON BATT", "LB", "LOWBATT"))
        is_online = any(k in status for k in ("OL", "ONLINE")) and not is_on_batt

        if is_on_batt:
            # Standard on-battery warning alert
            _trigger_alert(
                "ups_onbatt",
                "UPS On Battery",
                f"The system is running on battery power. Estimated runtime: {runtime if runtime is not None else '?'} min",
                "warning",
                now,
            )

            # Check for critical battery threshold or low battery flag
            is_critical = (
                "LB" in status
                or "LOWBATT" in status
                or (charge is not None and charge <= batt_thresh)
                or (runtime is not None and runtime <= time_thresh)
            )

            if is_critical:
                if _low_batt_start_ts is None:
                    _low_batt_start_ts = now

                elapsed = now - _low_batt_start_ts
                if elapsed >= grace_period and not _failsafe_active:
                    _failsafe_active = True
                    logger.warning(
                        f"[UPS FAILSAFE] Engaging automated failsafe: battery={charge}%, runtime={runtime}m (grace={elapsed:.1f}s)"
                    )

                    # 1. Protect file copy operation by pausing it cleanly
                    if getattr(Z_STATE, "copy_active", False) and not getattr(Z_STATE, "copy_paused", False):
                        Z_STATE.copy_paused = True
                        _copy_paused_by_failsafe = True
                        Z_STATE.ui_wake.set()
                        add_event(
                            "warning",
                            "Copy Job Paused",
                            "Photo/media copy job paused to prevent data corruption during low UPS battery.",
                        )
                        logger.warning("[UPS FAILSAFE] Paused active copy engine job.")

                    # 2. Flush dirty filesystem buffers to persistent disks asynchronously
                    def _sync_worker():
                        try:
                            os.sync()
                            logger.info("[UPS FAILSAFE] Flushed filesystem buffers via os.sync().")
                        except Exception as e:
                            logger.error(f"[UPS FAILSAFE] os.sync failed: {e}")

                    threading.Thread(target=_sync_worker, daemon=True, name="UpsFailsafeSync").start()

                    # 3. Dispatch critical priority notification and alert
                    crit_msg = (
                        f"Critical UPS battery ({charge or '?'}% remaining, ~{runtime or '?'} min). "
                        "Filesystem buffers synced to disk. Active copy operations paused."
                    )
                    _trigger_alert("ups_critical", "UPS Critical Battery: Failsafe Active", crit_msg, "critical", now)

                    # 4. Signal host powerdown if explicitly configured
                    if shutdown_enabled:
                        logger.critical("[UPS FAILSAFE] Initiating safe system powerdown sequence.")
                        add_event(
                            "critical",
                            "Emergency Powerdown",
                            "Low UPS battery threshold reached; initiating safe host shutdown.",
                        )
                        _signal_host_powerdown()
            else:
                # Still on battery but charge recovered above critical threshold
                if not _failsafe_active:
                    _low_batt_start_ts = None

        elif is_online:
            _resolve_alert("ups_onbatt", "UPS power restored.")

            # If failsafe was active, disengage and resume normal operation
            if _failsafe_active:
                logger.info("[UPS FAILSAFE] AC mains power restored. Disengaging failsafe.")
                _failsafe_active = False
                _low_batt_start_ts = None

                # Resume copy job if it was paused by the failsafe
                if _copy_paused_by_failsafe:
                    Z_STATE.copy_paused = False
                    _copy_paused_by_failsafe = False
                    Z_STATE.ui_wake.set()
                    add_event(
                        "info",
                        "Copy Job Resumed",
                        "UPS mains power restored; resumed paused photo/media copy operation.",
                    )
                    logger.info("[UPS FAILSAFE] Resumed paused copy engine job.")

                _resolve_alert(
                    "ups_critical", "Mains power restored; UPS battery recovering. Normal operation resumed."
                )


def _signal_host_powerdown():
    """Triggers graceful host powerdown if trigger script or poweroff command is available."""
    # Check for custom host shutdown trigger script (e.g. mounted from Unraid host)
    for trigger_path in ("/host/powerdown", "/usr/local/sbin/powerdown", "/sbin/poweroff"):
        if os.path.exists(trigger_path) and os.access(trigger_path, os.X_OK):
            try:
                import subprocess

                subprocess.Popen([trigger_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info(f"[UPS FAILSAFE] Executed {trigger_path}")
                return
            except Exception as e:
                logger.error(f"[UPS FAILSAFE] Failed executing {trigger_path}: {e}")


def _trigger_alert(alert_id, title, message, level, now):
    from backend.services.notifications import send_notification

    last_triggered = _active_alerts.get(alert_id, 0)
    # Re-alert every 15 minutes while active (or immediately on critical)
    debounce_interval = 300 if level == "critical" else 900
    if now - last_triggered > debounce_interval:
        _active_alerts[alert_id] = now
        add_event(level, title, message)
        send_notification({"type": "system", "title": title, "message": message, "level": level})


def _resolve_alert(alert_id, resolve_msg=None):
    from backend.services.notifications import send_notification

    if alert_id in _active_alerts:
        del _active_alerts[alert_id]
        if resolve_msg:
            add_event("info", "Alert Resolved", resolve_msg)
            send_notification({"type": "system", "title": "Alert Resolved", "message": resolve_msg, "level": "info"})
