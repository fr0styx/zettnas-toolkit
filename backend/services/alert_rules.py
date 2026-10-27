import os
import threading
import time

from backend.config import logger
from backend.state import Z_STATE, add_event

_active_alerts = {}


def get_failsafe_status() -> dict:
    """The UPS failsafe's state; the failsafe itself is ups_watchdog's (REL-10)."""
    from backend.services import ups_watchdog

    return {
        "failsafe_active": ups_watchdog._failsafe_engaged,
        "copy_paused_by_failsafe": ups_watchdog._copy_paused_by_failsafe,
    }


def reset_failsafe_state() -> None:
    """Reset alert and failsafe state (useful for test suites)."""
    from backend.services import ups_watchdog

    ups_watchdog._failsafe_engaged = False
    ups_watchdog._copy_paused_by_failsafe = False
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
        try:
            from backend.services.ups_watchdog import is_simulation_active

            if is_simulation_active():
                return
        except Exception:
            logger.debug("backend.services.alert_rules.evaluate_system_alerts: ignored error", exc_info=True)

        status = ups_data.get("status", "").upper()
        charge = ups_data.get("battery_charge_pct")
        runtime = ups_data.get("time_left_min")

        try:
            from backend.hardware.ups import load_ups_config

            ups_cfg = load_ups_config()
            batt_thresh = float(ups_cfg.get("battery_threshold_pct", 20.0))
            time_thresh = float(ups_cfg.get("runtime_threshold_min", 5.0))
        except Exception:
            batt_thresh = float(os.getenv("UPS_FAILSAFE_BATTERY_MIN", "20.0"))
            time_thresh = float(os.getenv("UPS_FAILSAFE_RUNTIME_MIN", "5.0"))

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

            # The low-battery failsafe itself is ups_watchdog's (one UPS engine, REL-10)
            if (
                "LB" in status
                or "LOWBATT" in status
                or (charge is not None and charge <= batt_thresh)
                or (runtime is not None and runtime <= time_thresh)
            ):
                _trigger_alert(
                    "ups_critical",
                    "UPS Critical Battery",
                    f"Critical UPS battery ({charge or '?'}% remaining, ~{runtime or '?'} min). The safe shutdown runs "
                    "when the UPS settings say so.",
                    "critical",
                    now,
                )

        elif is_online:
            _resolve_alert("ups_onbatt", "UPS power restored.")
            _resolve_alert("ups_critical", "Mains power restored; UPS battery recovering.")


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
