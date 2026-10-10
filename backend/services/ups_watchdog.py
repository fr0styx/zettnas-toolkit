"""
ZettNAS Toolkit - UPS Power Integrity & Automated Disaster Recovery Watchdog
Executes the atomic 4-phase safe shutdown sequence, debounces transient power loss,
logs power events in SQLite, and provides homelab outage drills.
"""

import os
import threading
import time
from typing import Any, Dict, Optional

from backend.config import logger
from backend.db import log_ups_event
from backend.hardware.ups import load_ups_config, read_ups_status
from backend.state import Z_STATE, add_event

_outage_start_ts: Optional[float] = None
_outage_start_charge: Optional[float] = None
_outage_start_volts: Optional[float] = None
_failsafe_engaged = False
_simulation_active = False
_simulation_end_ts = 0.0


def is_simulation_active() -> bool:
    global _simulation_active, _simulation_end_ts
    if _simulation_active and time.time() > _simulation_end_ts:
        _simulation_active = False
    return _simulation_active


def trigger_outage_simulation(duration_sec: int = 15) -> Dict[str, Any]:
    """Triggers a simulated power outage to test desktop warning overlays and alerts."""
    global _simulation_active, _simulation_end_ts
    _simulation_active = True
    _simulation_end_ts = time.time() + max(5, min(duration_sec, 60))

    log_ups_event(
        event_type="OUTAGE_SIMULATION",
        status="ACTIVE",
        duration_sec=float(duration_sec),
        start_battery_pct=100.0,
        end_battery_pct=100.0,
        action_taken="Simulated power outage drill for desktop UI.",
        details="User initiated simulation drill from Mission Control.",
    )

    add_event(
        "warning",
        "Power Outage Simulation",
        f"Simulating power outage drill for {duration_sec}s. No hardware will be shut down.",
    )

    return {
        "simulation_active": True,
        "duration_sec": duration_sec,
        "expires_in_sec": round(_simulation_end_ts - time.time(), 1),
    }


def graceful_docker_teardown(timeout_sec: int = 30):
    """Gracefully stops running Docker containers, allowing databases to flush WAL."""
    try:
        from backend.hardware.docker_stats import container_action, read_docker_containers
        containers = read_docker_containers()
        running = [c for c in containers if c.get("state") == "running"]
        if not running:
            logger.info("[UPS FAILSAFE] No running Docker containers to stop.")
            return

        logger.warning(f"[UPS FAILSAFE] Stopping {len(running)} running Docker container(s) before poweroff...")
        for c in running:
            cid = c.get("id") or c.get("name")
            if cid:
                try:
                    container_action(cid, "stop")
                    logger.info(f"[UPS FAILSAFE] Sent stop to container: {c.get('name', cid)}")
                except Exception as ce:
                    logger.debug(f"[UPS FAILSAFE] Container stop failed for {cid}: {ce}")
    except Exception as e:
        logger.error(f"[UPS FAILSAFE] Docker container teardown encountered error: {e}")


def send_ups_cut_power():
    """Issues shutdown command to UPS controller so it drops outlets after host halts."""
    cfg = load_ups_config()
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 3551)
    mode = cfg.get("mode", "auto")
    ups_name = cfg.get("ups_name", "ups")

    logger.warning("[UPS FAILSAFE] Issuing delayed power-cut command to UPS...")
    # Attempt NUT socket command: load.off.delay
    if mode in ("nut_client", "nut") or port == 3493:
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((host, port))
                if cfg.get("username"):
                    s.sendall(f"USERNAME {cfg['username']}\n".encode("utf-8"))
                    s.recv(1024)
                if cfg.get("password"):
                    s.sendall(f"PASSWORD {cfg['password']}\n".encode("utf-8"))
                    s.recv(1024)
                s.sendall(f"INSTCMD {ups_name} load.off.delay 60\n".encode("utf-8"))
                s.recv(1024)
                logger.info("[UPS FAILSAFE] Issued 'load.off.delay 60' to NUT.")
        except Exception as e:
            logger.debug(f"[UPS FAILSAFE] Failed sending NUT power-cut: {e}")


def signal_host_powerdown():
    """Triggers host powerdown using available trigger binaries."""
    for trigger_path in ("/host/powerdown", "/usr/local/sbin/powerdown", "/sbin/poweroff"):
        if os.path.exists(trigger_path) and os.access(trigger_path, os.X_OK):
            try:
                import subprocess
                subprocess.Popen([trigger_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.critical(f"[UPS FAILSAFE] Successfully executed {trigger_path}")
                return True
            except Exception as e:
                logger.error(f"[UPS FAILSAFE] Failed executing {trigger_path}: {e}")
    return False


def execute_atomic_failsafe_shutdown(charge: Optional[float], runtime: Optional[float], reason: str):
    """Executes the complete 4-phase atomic failsafe shutdown sequence."""
    global _failsafe_engaged
    if _failsafe_engaged:
        return
    _failsafe_engaged = True

    cfg = load_ups_config()
    logger.critical(f"[UPS FAILSAFE] ENGAGING ATOMIC SAFE SHUTDOWN: {reason} (charge={charge}%, runtime={runtime}m)")

    add_event(
        "critical",
        "UPS Emergency Safe Shutdown",
        f"Failsafe threshold met: {reason}. Quiescing storage and shutting down system.",
    )

    log_ups_event(
        event_type="FAILSAFE_SHUTDOWN",
        status="EXECUTING",
        duration_sec=0.0,
        start_battery_pct=_outage_start_charge,
        end_battery_pct=charge,
        action_taken="Atomic safe shutdown sequence initiated.",
        details=f"Reason: {reason}",
    )

    # Step 1: Disarm I/O
    if getattr(Z_STATE, "copy_active", False):
        Z_STATE.copy_paused = True
        Z_STATE.ui_wake.set()
        logger.warning("[UPS FAILSAFE] Paused active copy engine job.")

    # Step 2: Gracefully stop Docker containers
    container_timeout = int(cfg.get("container_shutdown_timeout_sec", 30))
    graceful_docker_teardown(timeout_sec=container_timeout)

    # Step 3: Flush filesystem buffers to physical disks
    try:
        os.sync()
        logger.info("[UPS FAILSAFE] Flushed all OS buffers via os.sync().")
    except Exception as e:
        logger.error(f"[UPS FAILSAFE] os.sync failed: {e}")

    # Step 4: Issue UPS cut power if configured
    if cfg.get("poweroff_ups"):
        send_ups_cut_power()

    # Step 5: Powerdown host
    logger.critical("[UPS FAILSAFE] Initiating host ACPI powerdown.")
    signal_host_powerdown()


def check_ups_power_watchdog(ups_data: Dict[str, Any], now: float):
    """Called every stats collection tick to evaluate UPS state, log events, and enforce policies."""
    global _outage_start_ts, _outage_start_charge, _outage_start_volts, _failsafe_engaged

    if not ups_data or not ups_data.get("available"):
        return

    status = (ups_data.get("status") or "").upper()
    charge = ups_data.get("battery_charge_pct")
    runtime = ups_data.get("time_left_min")
    line_v = ups_data.get("line_volts")
    load_pct = ups_data.get("load_pct")

    is_on_batt = any(k in status for k in ("OB", "ONBATT", "ON BATT", "LB", "LOWBATT")) or is_simulation_active()
    is_online = any(k in status for k in ("OL", "ONLINE")) and not is_on_batt

    cfg = load_ups_config()
    policy = cfg.get("shutdown_policy", "runtime_left")
    batt_thresh = float(cfg.get("battery_threshold_pct", 20.0))
    time_thresh = float(cfg.get("runtime_threshold_min", 5.0))
    timer_thresh = float(cfg.get("shutdown_timer_sec", 300.0))

    if is_on_batt:
        if _outage_start_ts is None:
            _outage_start_ts = now
            _outage_start_charge = charge
            _outage_start_volts = line_v

        elapsed = now - _outage_start_ts

        # Debounce filter: only evaluate after 5 seconds to ignore momentary grid blips
        if elapsed >= 5.0 and not _failsafe_engaged:
            # Policy evaluation
            policy_tripped = False
            trip_reason = ""

            if "LB" in status or "LOWBATT" in status:
                policy_tripped = True
                trip_reason = "Hardware Low-Battery Flag (LB)"
            elif policy == "runtime_left" and runtime is not None and runtime <= time_thresh:
                policy_tripped = True
                trip_reason = f"Runtime remaining below threshold ({runtime}m <= {time_thresh}m)"
            elif policy == "battery_pct" and charge is not None and charge <= batt_thresh:
                policy_tripped = True
                trip_reason = f"Battery charge below threshold ({charge}% <= {batt_thresh}%)"
            elif policy == "timer" and elapsed >= timer_thresh:
                policy_tripped = True
                trip_reason = f"Time on battery exceeded threshold ({int(elapsed)}s >= {int(timer_thresh)}s)"

            if policy_tripped:
                execute_atomic_failsafe_shutdown(charge, runtime, trip_reason)

    elif is_online:
        # Power restored
        if _outage_start_ts is not None:
            duration = round(now - _outage_start_ts, 1)
            # Only record if the outage lasted at least 3 seconds
            if duration >= 3.0:
                log_ups_event(
                    event_type="OUTAGE_RECOVERED",
                    status="RESOLVED",
                    duration_sec=duration,
                    start_battery_pct=_outage_start_charge,
                    end_battery_pct=charge,
                    min_line_volts=_outage_start_volts,
                    max_load_pct=load_pct,
                    action_taken="Mains power restored. Normal operation resumed.",
                    details=f"Outage lasted {duration}s. Battery recovered to {charge}%.",
                )
                add_event(
                    "info",
                    "Utility Power Restored",
                    f"Mains power restored after {duration}s. Battery charge: {charge}%.",
                )
            _outage_start_ts = None
            _outage_start_charge = None
            _outage_start_volts = None
            _failsafe_engaged = False
