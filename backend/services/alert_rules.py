import os
import threading
import time

from backend.config import logger
from backend.ignored_errors import ignored
from backend.state import Z_STATE, add_event

_active_alerts = {}

# PERF-31: no memory limit by default (Docker would kill the app mid-write); a warning instead
MEMORY_CHECK_SECS = 60.0
MEMORY_CLEAR_SHARE = 0.9  # the warning clears below 90 % of the level
_MEMORY = {"at": 0.0}


def app_memory_mb(proc: str = "/proc") -> float:
    """What ZettNAS itself holds: the resident memory of the processes in its container, except
    QEMU (a virtual machine's memory is the VM's, not the app's)."""
    total_kb = 0
    for name in os.listdir(proc):
        if not name.isdigit():
            continue
        try:
            with open(os.path.join(proc, name, "cmdline"), "rb") as f:
                exe = f.read().split(b"\0", 1)[0].rsplit(b"/", 1)[-1]
            if exe.startswith(b"qemu-system"):
                continue
            with open(os.path.join(proc, name, "status")) as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        total_kb += int(line.split()[1])
                        break
        except (OSError, ValueError, IndexError):
            continue
    return total_kb / 1024


def check_app_memory(now: float | None = None, measure=app_memory_mb) -> None:
    """At most once a minute: warn when the app's memory passes APP_MEMORY_WARN_MB, and say so
    when it is back under 90 % of it."""
    from backend import config

    now = time.time() if now is None else now
    if now - _MEMORY["at"] < MEMORY_CHECK_SECS:
        return
    _MEMORY["at"] = now
    warn = int(getattr(config, "APP_MEMORY_WARN_MB", 0) or 0)
    if warn <= 0:
        _resolve_alert("app_memory")
        return
    mb = measure()
    if mb > warn:
        _trigger_alert(
            "app_memory",
            "ZettNAS is using a lot of memory",
            f"ZettNAS uses {mb:.0f} MB, over the {warn} MB warning level (APP_MEMORY_WARN_MB; virtual "
            "machines are not counted). If it keeps growing, restart the container and report it.",
            "warning",
            now,
        )
    elif mb < warn * MEMORY_CLEAR_SHARE:
        _resolve_alert("app_memory", f"ZettNAS memory is back to normal ({mb:.0f} MB).")


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
    _MEMORY["at"] = 0.0


def evaluate_system_alerts(unraid_data, ups_data):
    """Evaluates built-in rules for system alerts, debounces them, and triggers automated failsafes."""
    global _failsafe_active, _low_batt_start_ts, _copy_paused_by_failsafe
    now = time.time()
    try:
        check_app_memory(now)
    except Exception:
        logger.debug("alert_rules: memory check failed", exc_info=True)

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
            ignored("backend.services.alert_rules.evaluate_system_alerts")

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
