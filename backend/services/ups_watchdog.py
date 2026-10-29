"""
ZettNAS Toolkit - UPS Power Integrity & Automated Disaster Recovery Watchdog
Executes the atomic 4-phase safe shutdown sequence, debounces transient power loss,
logs power events in SQLite, and provides homelab outage drills.

The one UPS engine (REL-10, D10). When the battery runs low ZettNAS pauses copies, stops the
apps it installed (in parallel, within the timeout) and flushes the disks. On Unraid and TrueNAS
the host's own UPS service then shuts the server down: ZettNAS never powers those hosts off and
never cuts the UPS outlets there. Elsewhere ZettNAS shuts the host down itself, and tells the UPS
to cut its outlets only after that shutdown command succeeded. The drill reports which path will
shut the server down, or that there is none.
"""

import os
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Optional

from backend.config import logger
from backend.db import log_ups_event
from backend.hardware.ups import load_ups_config, read_ups_status
from backend.services.nut_server import forced_shutdown as nut_forced_shutdown
from backend.settings import test_mode
from backend.state import Z_STATE, add_event

_outage_start_ts: float | None = None
_outage_start_charge: float | None = None
_outage_start_volts: float | None = None
_failsafe_engaged = False
_simulation_active = False
_simulation_end_ts = 0.0
_copy_paused_by_failsafe = False
HOST_OWNED = {"unraid": "Unraid", "truenas": "TrueNAS"}


def is_simulation_active() -> bool:
    global _simulation_active, _simulation_end_ts
    if _simulation_active and time.time() > _simulation_end_ts:
        _simulation_active = False
    return _simulation_active


def trigger_outage_simulation(duration_sec: int = 15) -> dict[str, Any]:
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
        "shutdown_path": shutdown_path_report(),  # who shuts the server down when it is real
    }


def end_simulation_drill():
    global _simulation_active, _simulation_end_ts
    _simulation_active = False
    _simulation_end_ts = 0.0


def _catalog_ids() -> set[str]:
    try:
        from backend.services.app_catalog import get_all_catalog_apps

        return {str(a.get("app_slug") or a.get("id") or "") for a in get_all_catalog_apps()} - {""}
    except Exception:
        return set()


def zettnas_containers(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The running apps ZettNAS installed (labelled, or a catalog app's stack). ZettNAS itself and
    its helpers (fan watchdog, sidecars) keep running to the end; other people's containers are
    left to the host's own shutdown."""
    ids = _catalog_ids()
    out = []
    for c in containers:
        if c.get("state") != "running":
            continue
        name = (c.get("name") or "").lower().lstrip("/")
        if name.startswith("zettnas"):
            continue
        if c.get("zettnas_app") or (c.get("stack") and c["stack"] in ids):
            out.append(c)
    return out


def graceful_docker_teardown(timeout_sec: int = 30) -> dict[str, list[str]]:
    """Stops the apps ZettNAS installed, all at once, so databases flush before the power goes;
    gives up waiting after timeout_sec (REL-10)."""
    result: dict[str, list[str]] = {"stopped": [], "failed": [], "timed_out": []}
    try:
        from backend.hardware.docker_stats import container_action, read_docker_containers

        mine = zettnas_containers(read_docker_containers())
    except Exception as e:
        logger.error(f"[UPS FAILSAFE] Could not list the apps: {e}")
        return result
    if not mine:
        logger.info("[UPS FAILSAFE] No ZettNAS apps to stop.")
        return result
    logger.warning(f"[UPS FAILSAFE] Stopping {len(mine)} ZettNAS app container(s) before the power goes...")
    pool = ThreadPoolExecutor(max_workers=min(8, len(mine)), thread_name_prefix="UpsStop")
    futures = {
        pool.submit(container_action, str(c.get("id") or c.get("name") or ""), "stop"): c.get("name") or c.get("id")
        for c in mine
    }
    done, pending = wait(futures, timeout=max(1, int(timeout_sec)))
    for f in done:
        name = str(futures[f])
        try:
            ok = (f.result() or {}).get("success", True)
        except Exception:
            ok = False
        result["stopped" if ok else "failed"].append(name)
    result["timed_out"] = [str(futures[f]) for f in pending]
    pool.shutdown(wait=False, cancel_futures=True)
    if result["timed_out"]:
        logger.warning(f"[UPS FAILSAFE] Still stopping after {timeout_sec}s: {', '.join(result['timed_out'])}")
    return result


def shutdown_owner() -> str:
    """'unraid' / 'truenas' when the host's own UPS service shuts the server down (D10), else
    'zettnas'."""
    try:
        from backend.hardware.pal_storage import get_storage_platform

        platform = str(get_storage_platform().get_platform_type().value)
    except Exception:
        platform = ""
    return platform if platform in HOST_OWNED else "zettnas"


def _gateway(route_file: str = "/proc/net/route") -> str | None:
    """The host as seen from this container: the default route's gateway."""
    try:
        with open(route_file, encoding="utf-8") as f:
            for line in f.read().splitlines()[1:]:
                fields = line.split()
                if len(fields) > 2 and fields[1] == "00000000":
                    return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    except (OSError, ValueError):
        return None
    return None


def _nut_answers(host: str, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, 3493), timeout=timeout) as s:
            s.sendall(b"LIST UPS\n")
            return b"BEGIN LIST UPS" in s.recv(4096)
    except OSError:
        return False


def host_ups_service() -> dict[str, Any] | None:
    """The host's own UPS service (apcupsd or NUT), if this container can reach it."""
    from backend.hardware.ups import _query_apcupsd_socket

    hosts = [h for h in dict.fromkeys([_gateway(), "127.0.0.1"]) if h]
    for host in hosts:
        try:
            d = _query_apcupsd_socket(host, 3551, 1.5)
        except Exception:
            d = {}
        if d.get("STATUS"):
            return {
                "kind": "apcupsd",
                "battery_pct": (str(d.get("MBATTCHG") or "").split() or [""])[0],
                "minutes": (str(d.get("MINTIMEL") or "").split() or [""])[0],
            }
    for host in hosts:
        if _nut_answers(host):
            return {"kind": "nut", "battery_pct": "", "minutes": ""}
    return None


def shutdown_path_report() -> dict[str, Any]:
    """What shuts the server down when the battery runs out: {by, ok, detail} (REL-10)."""
    owner = shutdown_owner()
    if owner in HOST_OWNED:
        host = HOST_OWNED[owner]
        svc = host_ups_service()
        if not svc:
            return {
                "by": owner,
                "ok": False,
                "detail": f"{host}'s UPS service does not answer, so nothing shuts the server down when the battery "
                f"runs out. Turn it on in {host}'s UPS settings.",
            }
        when = ""
        if svc.get("battery_pct") or svc.get("minutes"):
            when = f" at {svc['battery_pct'] or '?'}% battery or {svc['minutes'] or '?'} minutes left"
        return {
            "by": owner,
            "ok": True,
            "detail": f"{host}'s UPS service ({svc['kind']}) shuts the server down{when}. "
            "Before that ZettNAS stops its apps and saves what is in memory.",
        }
    paths = host_shutdown_paths()
    if paths:
        return {"by": "zettnas", "ok": True, "detail": f"ZettNAS shuts the server down with {paths[0]}."}
    return {
        "by": "zettnas",
        "ok": False,
        "detail": "ZettNAS has no way to shut this server down (no host shutdown command is mounted). "
        "Set up the host's own UPS shutdown, or mount a powerdown command at /host/powerdown.",
    }


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
                    s.sendall(f"USERNAME {cfg['username']}\n".encode())
                    s.recv(1024)
                if cfg.get("password"):
                    s.sendall(f"PASSWORD {cfg['password']}\n".encode())
                    s.recv(1024)
                s.sendall(f"INSTCMD {ups_name} load.off.delay 60\n".encode())
                s.recv(1024)
                logger.info("[UPS FAILSAFE] Issued 'load.off.delay 60' to NUT.")
        except Exception as e:
            logger.debug(f"[UPS FAILSAFE] Failed sending NUT power-cut: {e}")


def host_shutdown_paths() -> list[str]:
    """Commands that shut down the HOST (REL-10). Inside a container /sbin/poweroff only stops the
    container, so it counts only when ZettNAS runs directly on the host."""
    paths = ["/host/powerdown", "/usr/local/sbin/powerdown"]
    if not os.path.exists("/.dockerenv"):
        paths.append("/sbin/poweroff")
    return [p for p in paths if os.path.exists(p) and os.access(p, os.X_OK)]


def signal_host_powerdown() -> bool:
    """Shuts the host down; True only when a host shutdown command ran and reported success."""
    if test_mode():
        logger.info("[UPS FAILSAFE] Test mode active; skipping host powerdown.")
        return True
    import subprocess

    for trigger_path in host_shutdown_paths():
        try:
            res = subprocess.run([trigger_path], capture_output=True, text=True, timeout=60)
        except Exception as e:
            logger.error(f"[UPS FAILSAFE] {trigger_path} could not run: {e}")
            continue
        if res.returncode == 0:
            logger.critical(f"[UPS FAILSAFE] Host shutdown started with {trigger_path}")
            return True
        logger.error(
            f"[UPS FAILSAFE] {trigger_path} failed (exit {res.returncode}): {(res.stderr or '').strip()[:200]}"
        )
    return False


def execute_atomic_failsafe_shutdown(charge: float | None, runtime: float | None, reason: str):
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

    # Step 0: the PCs watching this UPS over NUT get the forced-shutdown flag and go first (FEAT-11)
    nut_forced_shutdown()

    # Step 1: Disarm I/O
    global _copy_paused_by_failsafe
    if getattr(Z_STATE, "copy_active", False) and not getattr(Z_STATE, "copy_paused", False):
        Z_STATE.copy_paused = True
        _copy_paused_by_failsafe = True
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

    # Step 4a: on Unraid and TrueNAS the host's own UPS service shuts the server down (D10)
    owner = shutdown_owner()
    if owner in HOST_OWNED:
        host = HOST_OWNED[owner]
        msg = (
            f"The UPS battery is low. ZettNAS stopped its apps and saved what was in memory; "
            f"{host}'s own UPS settings shut the server down."
        )
        logger.critical(f"[UPS FAILSAFE] {msg}")
        add_event("critical", "UPS: handed to the host", msg)
        log_ups_event(
            event_type="FAILSAFE_SHUTDOWN",
            status="HANDED_TO_HOST",
            duration_sec=0.0,
            start_battery_pct=_outage_start_charge,
            end_battery_pct=charge,
            action_taken=f"Apps stopped, disks flushed; {host} shuts down.",
            details=f"Reason: {reason}",
        )
        return

    # Step 4b: shut the host down; only then may the UPS be told to cut its outlets (REL-10)
    logger.critical("[UPS FAILSAFE] Initiating host powerdown.")
    if signal_host_powerdown():
        if cfg.get("poweroff_ups"):
            send_ups_cut_power()
        return
    msg = (
        "ZettNAS could not shut down this server on its own (no working host shutdown command). "
        "The UPS outlets were NOT switched off. Shut the NAS down by hand now to avoid a hard power loss."
    )
    logger.critical(f"[UPS FAILSAFE] {msg}")
    add_event("critical", "UPS: shut the NAS down by hand", msg)
    try:
        from backend.services.notifications import send_notification

        send_notification(title="UPS: shut the NAS down by hand", message=msg, level="critical", event_type="ups")
    except Exception:
        logger.debug("ups_watchdog: notification failed", exc_info=True)


def check_ups_power_watchdog(ups_data: dict[str, Any], now: float):
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

        # Debounce filter: only evaluate after 5 seconds to ignore momentary grid blips (immediate for drills)
        if (elapsed >= 5.0 or is_simulation_active()) and not _failsafe_engaged:
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
                if is_simulation_active():
                    end_simulation_drill()
                    logger.warning(
                        f"[UPS SIMULATION DRILL] Safe shutdown policy tripped ({trip_reason}). Simulation drill completed successfully — host shutdown skipped."
                    )
                    path = shutdown_path_report()
                    add_event(
                        "warning" if path["ok"] else "error",
                        "UPS Simulation Drill Completed",
                        f"Failsafe shutdown policy tripped: {trip_reason}. Host shutdown was NOT executed because "
                        f"drill simulation mode is active. When it is real: {path['detail']}",
                    )
                else:
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
        resume_copy_after_outage()


def resume_copy_after_outage() -> bool:
    """Mains power is back: a copy the failsafe paused carries on."""
    global _copy_paused_by_failsafe
    if not _copy_paused_by_failsafe:
        return False
    _copy_paused_by_failsafe = False
    Z_STATE.copy_paused = False
    Z_STATE.ui_wake.set()
    add_event("info", "Copy Job Resumed", "Mains power is back; the paused copy carries on.")
    return True
