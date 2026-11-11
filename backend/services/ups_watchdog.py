"""
Kiboto - UPS Power Integrity & Automated Disaster Recovery Watchdog
Executes the atomic 4-phase safe shutdown sequence, debounces transient power loss,
logs power events in SQLite, and provides homelab outage drills.

The one UPS engine (REL-10, D10). When the battery runs low Kiboto pauses copies, stops the
apps it installed (in parallel, within the timeout) and flushes the disks. On Unraid and TrueNAS
the host's own UPS service then shuts the server down: Kiboto never powers those hosts off and
never cuts the UPS outlets there. Elsewhere Kiboto shuts the host down itself, and tells the UPS
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
from backend.errors import said
from backend.hardware import ups_state
from backend.hardware.ups import load_ups_config, read_ups_status
from backend.services.nut_server import forced_shutdown as nut_forced_shutdown
from backend.settings import test_mode
from backend.state import Z_STATE, add_event, event_text

_outage_start_ts: float | None = None
_outage_start_charge: float | None = None
_outage_start_volts: float | None = None
_failsafe_engaged = False
_host_shutdown_started = False
_silent_alerted = False
_simulation_active = False
_outage_is_drill = False  # the current "outage" is the practice run, not the mains (SET-15, Power B4)
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
        event_text("ups_drill", secs=duration_sec),
    )

    path = shutdown_path_report()  # who shuts the server down when it is real
    _remember_practice(path)
    return {
        "simulation_active": True,
        "duration_sec": duration_sec,
        "expires_in_sec": round(_simulation_end_ts - time.time(), 1),
        "shutdown_path": path,
        "practice": last_practice(),
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


def kiboto_containers(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The running apps Kiboto installed (labelled, or a catalog app's stack). Kiboto itself and
    its helpers (fan watchdog, sidecars) keep running to the end; other people's containers are
    left to the host's own shutdown."""
    ids = _catalog_ids()
    out = []
    for c in containers:
        if c.get("state") != "running":
            continue
        name = (c.get("name") or "").lower().lstrip("/")
        if name.startswith(("kiboto", "zettnas")):  # Kiboto itself, under either name
            continue
        if c.get("kiboto_app") or c.get("zettnas_app") or (c.get("stack") and c["stack"] in ids):
            out.append(c)
    return out


def graceful_docker_teardown(timeout_sec: int = 30) -> dict[str, list[str]]:
    """Stops the apps Kiboto installed, all at once, so databases flush before the power goes;
    gives up waiting after timeout_sec (REL-10)."""
    result: dict[str, list[str]] = {"stopped": [], "failed": [], "timed_out": []}
    try:
        from backend.hardware.docker_stats import container_action, read_docker_containers

        mine = kiboto_containers(read_docker_containers())
    except Exception as e:
        logger.error("[UPS FAILSAFE] Could not list the apps: %s", e)
        return result
    if not mine:
        logger.info("[UPS FAILSAFE] No Kiboto apps to stop.")
        return result
    logger.warning("[UPS FAILSAFE] Stopping %s Kiboto app container(s) before the power goes...", len(mine))
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
    _remember_stopped(result["stopped"] + result["timed_out"])
    if result["timed_out"]:
        logger.warning("[UPS FAILSAFE] Still stopping after %ss: %s", timeout_sec, ", ".join(result["timed_out"]))
    return result


def _stopped_file() -> str:
    from backend.config import DATA_DIR

    return os.path.join(DATA_DIR, "ups_stopped_apps.json")


def _practice_file() -> str:
    from backend.config import DATA_DIR

    return os.path.join(DATA_DIR, "ups_last_practice.json")


def _remember_practice(path: dict[str, Any]) -> None:
    """The last practice run and its answer (who would switch the NAS off), kept for the page
    (SET-15, Power B4: the answer was a pop-up that vanished after 6.5 s, in English)."""
    from backend.fsutil import atomic_write_json

    try:
        atomic_write_json(
            _practice_file(),
            {"at": time.time(), "ok": bool(path.get("ok")), "text": path.get("text"), "detail": path.get("detail", "")},
        )
    except OSError:
        logger.warning("[UPS] Could not keep the practice run's result", exc_info=True)


def last_practice() -> dict[str, Any]:
    """The last practice run: {at, ok, text, detail}, or {} when there has been none."""
    from backend.fsutil import read_json

    rec = read_json(_practice_file(), {}) or {}
    return rec if isinstance(rec, dict) and rec.get("at") else {}


def _remember_stopped(names: list[str]) -> None:
    """The apps stopped for a power event, so they come back when the power does (NREL-10)."""
    if not names:
        return
    from backend.fsutil import atomic_write_json

    try:
        atomic_write_json(_stopped_file(), {"apps": sorted(set(names)), "at": time.time()})
    except OSError:
        logger.warning("[UPS] could not record the stopped apps", exc_info=True)


def restart_stopped_apps() -> list[str]:
    """Starts the apps Kiboto stopped for a power event: when mains is back, or at the next
    start after a real shutdown. Docker won't, for a container stopped before (NREL-10)."""
    from backend.fsutil import read_json

    path = _stopped_file()
    names = list((read_json(path, {}) or {}).get("apps") or [])
    if not names:
        return []
    from backend.hardware.docker_stats import container_action

    started = []
    for name in names:
        try:
            if (container_action(name, "start") or {}).get("success", True):
                started.append(name)
        except (OSError, RuntimeError, ValueError):
            logger.warning("[UPS] could not start %s again", name, exc_info=True)
    try:
        os.remove(path)
    except OSError:
        logger.debug("[UPS] stopped-apps list already gone", exc_info=True)
    if started:
        apps = ", ".join(started)
        add_event(
            "info", "Apps started again", "After the power event: " + apps, event_text("ups_apps_back", apps=apps)
        )
    return started


def shutdown_owner() -> str:
    """'unraid' / 'truenas' when the host's own UPS service shuts the server down (D10), else
    'kiboto'."""
    try:
        from backend.hardware.pal_storage import get_storage_platform

        platform = str(get_storage_platform().get_platform_type().value)
    except Exception:
        platform = ""
    return platform if platform in HOST_OWNED else "kiboto"


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
                "text": said("power_host_silent", host=host),
            }
        when = ""
        if svc.get("battery_pct") or svc.get("minutes"):
            when = f" at {svc['battery_pct'] or '?'}% battery or {svc['minutes'] or '?'} minutes left"
        return {
            "by": owner,
            "ok": True,
            "detail": f"{host}'s UPS service ({svc['kind']}) shuts the server down{when}. "
            "Before that Kiboto stops its apps and saves what is in memory.",
            "text": said("power_host_shuts", host=host, kind=svc["kind"]),
        }
    paths = host_shutdown_paths()
    if paths:
        return {
            "by": "kiboto",
            "ok": True,
            "detail": f"Kiboto shuts the server down with {paths[0]}.",
            "text": said("power_kiboto_shuts"),
        }
    return {
        "by": "kiboto",
        "ok": False,
        "detail": "Kiboto has no way to shut this server down (no host shutdown command is mounted). "
        "Set up the host's own UPS shutdown, or mount a powerdown command at /host/powerdown.",
        "text": said("power_nobody"),
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
    container, so it counts only when Kiboto runs directly on the host."""
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
            logger.critical("[UPS FAILSAFE] Host shutdown started with %s", trigger_path)
            return True
        logger.error(
            "[UPS FAILSAFE] %s failed (exit %s): %s", trigger_path, res.returncode, (res.stderr or "").strip()[:200]
        )
    return False


def execute_atomic_failsafe_shutdown(charge: float | None, runtime: float | None, reason: str):
    """Executes the complete 4-phase atomic failsafe shutdown sequence."""
    global _failsafe_engaged
    if _failsafe_engaged:
        return
    _failsafe_engaged = True

    global _host_shutdown_started
    cfg = _step("read the settings", load_ups_config) or {}
    logger.critical(
        "[UPS FAILSAFE] ENGAGING ATOMIC SAFE SHUTDOWN: %s (charge=%s%%, runtime=%sm)", reason, charge, runtime
    )

    add_event(
        "critical",
        "UPS Emergency Safe Shutdown",
        f"Failsafe threshold met: {reason}. Quiescing storage and shutting down system.",
        event_text("ups_shutdown", reason=reason),
    )

    _step(
        "record the event",
        lambda: log_ups_event(
            event_type="FAILSAFE_SHUTDOWN",
            status="EXECUTING",
            duration_sec=0.0,
            start_battery_pct=_outage_start_charge,
            end_battery_pct=charge,
            action_taken="Atomic safe shutdown sequence initiated.",
            details=f"Reason: {reason}",
        ),
    )
    # every step is guarded: one that fails is logged and the next one runs (SET-08)
    _step("say that the shutdown starts", _say_shutdown_starts, reason, charge, runtime)
    # Step 0: the PCs watching this UPS over NUT get the forced-shutdown flag and go first (FEAT-11)
    _step("warn the PCs that share this UPS", nut_forced_shutdown)
    # Step 1: Disarm I/O
    _step("pause the copy", _pause_copy)
    # Step 2: virtual machines and apps are asked to stop
    _step("shut the virtual machines down", _machines_first)
    container_timeout = int(cfg.get("container_shutdown_timeout_sec", 30))
    _step("stop the apps", graceful_docker_teardown, container_timeout)
    # Step 3: Flush filesystem buffers to physical disks
    _step("flush the disks", os.sync)

    # Step 4a: on Unraid and TrueNAS the host's own UPS service shuts the server down (D10)
    owner = shutdown_owner()
    if owner in HOST_OWNED:
        host = HOST_OWNED[owner]
        msg = (
            f"The UPS battery is low. Kiboto stopped its apps and saved what was in memory; "
            f"{host}'s own UPS settings shut the server down."
        )
        logger.critical("[UPS FAILSAFE] %s", msg)
        add_event("critical", "UPS: handed to the host", msg, event_text("ups_handed", host=host))
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
        _host_shutdown_started = True  # from here on nothing is started again, also if mains returns
        if cfg.get("poweroff_ups"):
            _step("switch the UPS sockets off", send_ups_cut_power)
        return
    msg = (
        "Kiboto could not shut down this server on its own (no working host shutdown command). "
        "The UPS outlets were NOT switched off. Shut the NAS down by hand now to avoid a hard power loss."
    )
    logger.critical("[UPS FAILSAFE] %s", msg)
    from backend.services.notifications import alert_text

    text = alert_text("ups_manual")
    add_event("critical", "UPS: shut the NAS down by hand", msg, details=text)
    try:
        from backend.services.notifications import send_notification

        send_notification(
            title="UPS: shut the NAS down by hand",
            message=msg,
            level="critical",
            event_type="ups",
            text=text,
            record=False,
        )
    except Exception:
        logger.debug("ups_watchdog: notification failed", exc_info=True)


def _step(name: str, fn, *args) -> Any:
    """One step of the safe shutdown. A step that fails is logged as an error and the sequence
    goes on: an error while warning the PCs or stopping the apps used to end the whole sequence,
    with no power-off and no second try (SET-08)."""
    try:
        return fn(*args)
    except Exception as e:
        logger.error("[UPS FAILSAFE] step '%s' failed, going on: %s", name, e)
        return None


def _pause_copy() -> None:
    global _copy_paused_by_failsafe
    if getattr(Z_STATE, "copy_active", False) and not getattr(Z_STATE, "copy_paused", False):
        Z_STATE.copy_paused = True
        _copy_paused_by_failsafe = True
        Z_STATE.ui_wake.set()
        logger.warning("[UPS FAILSAFE] Paused active copy engine job.")


def _machines_first() -> None:
    from backend.services import vm_qemu

    vm_qemu.shut_down_all(wait_secs=45, come_back=False)  # they were not in the sequence at all


def _say_shutdown_starts(reason: str, charge: float | None, runtime: float | None) -> None:
    """One message that the safe shutdown starts, whatever limit was reached. With the "time on
    battery" limit nobody was told: only the two battery limits pushed a message."""
    from backend.services.notifications import alert_text, send_notification

    send_notification(
        title="UPS: the safe shutdown starts",
        message=f"The NAS is on battery and a limit was reached ({reason}). Apps are stopped and the NAS shuts down now.",
        level="critical",
        event_type="ups",
        text=alert_text(
            "ups_shutdown_now", charge="?" if charge is None else charge, runtime="?" if runtime is None else runtime
        ),
        record=False,  # the shutdown has its own entry
    )


def ups_went_silent() -> bool:
    """The UPS stopped answering during a power cut and has not answered since (for the Overview)."""
    return bool(_silent_alerted and _outage_start_ts is not None)


def _ups_fell_silent(now: float) -> None:
    """The UPS gives no reading. During a power cut that is said once, loudly: the watchdog used to
    stop looking, and a network UPS that answered with an error was taken for "online", which
    recorded "power restored" and started the apps again while the power was still out."""
    global _silent_alerted
    if _outage_start_ts is None or _silent_alerted or _failsafe_engaged:
        return
    _silent_alerted = True
    from backend.services.notifications import alert_text, send_notification

    secs = int(now - _outage_start_ts)
    msg = (
        f"The UPS stopped answering {secs} seconds into a power cut. Kiboto can no longer see the battery, "
        "so it cannot shut the NAS down in time by itself. Check the UPS connection, or shut the NAS down by hand."
    )
    logger.critical("[UPS] %s", msg)
    text = alert_text("ups_silent", secs=secs)
    add_event("critical", "UPS stopped answering during a power cut", msg, details=text)
    _step(
        "tell the household",
        lambda: send_notification(
            title="UPS stopped answering during a power cut",
            message=msg,
            level="critical",
            event_type="ups",
            text=text,
            record=False,
        ),
    )


def check_ups_power_watchdog(ups_data: dict[str, Any], now: float):
    """Called every stats collection tick to evaluate UPS state, log events, and enforce policies."""
    global \
        _outage_start_ts, \
        _outage_start_charge, \
        _outage_start_volts, \
        _failsafe_engaged, \
        _silent_alerted, \
        _outage_is_drill

    if not ups_data or not ups_data.get("available"):
        _ups_fell_silent(now)
        return

    status = ups_data.get("status")
    charge = ups_data.get("battery_charge_pct")
    runtime = ups_data.get("time_left_min")
    line_v = ups_data.get("line_volts")
    load_pct = ups_data.get("load_pct")

    # one reader of the status (hardware/ups_state): "on mains with a low battery" and "battery
    # unplugged" are not "on battery"
    state = ups_state.power_state(status)
    drill = is_simulation_active()
    is_on_batt = state == ups_state.ON_BATTERY or drill
    is_online = state == ups_state.ONLINE and not drill

    if is_on_batt:
        _silent_alerted = False
        if _outage_start_ts is None:
            _outage_start_ts = now
            _outage_start_charge = charge
            _outage_start_volts = line_v
            _outage_is_drill = state != ups_state.ON_BATTERY
        elif state == ups_state.ON_BATTERY:
            _outage_is_drill = False  # the mains really went during the practice run

        elapsed = now - _outage_start_ts

        # Debounce filter: only evaluate after 5 seconds to ignore momentary grid blips (immediate for drills)
        if (elapsed >= 5.0 or drill) and not _failsafe_engaged:
            # a practice run plays "on battery" over whatever the UPS says
            seen = status if state == ups_state.ON_BATTERY else "OB"
            trip_reason = ups_state.shutdown_reason(seen, charge, runtime, elapsed, load_ups_config())

            if trip_reason:
                if drill:
                    end_simulation_drill()
                    logger.warning(
                        "[UPS SIMULATION DRILL] Safe shutdown policy tripped (%s). Simulation drill completed successfully — host shutdown skipped.",
                        trip_reason,
                    )
                    path = shutdown_path_report()
                    add_event(
                        "warning" if path["ok"] else "error",
                        "UPS Simulation Drill Completed",
                        f"Failsafe shutdown policy tripped: {trip_reason}. Host shutdown was NOT executed because "
                        f"drill simulation mode is active. When it is real: {path['detail']}",
                        event_text("ups_drill_done", reason=trip_reason, detail=path["detail"]),
                    )
                else:
                    execute_atomic_failsafe_shutdown(charge, runtime, trip_reason)

    elif is_online:
        # Power restored
        if _outage_start_ts is not None:
            duration = round(now - _outage_start_ts, 1)
            # Only record if the outage lasted at least 3 seconds; a practice run is no outage: it wrote
            # "Mains power restored" into the history for a cut that never happened (SET-15, Power B4)
            if duration >= 3.0 and not _outage_is_drill:
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
                    event_text("ups_power_back", secs=duration, charge=charge),
                )
            _outage_start_ts = None
            _outage_start_charge = None
            _outage_start_volts = None
            _outage_is_drill = False
            _silent_alerted = False
            if _host_shutdown_started:
                # the NAS is going down: starting the apps again would start them into a shutdown
                # and delete the list of what to start after the next boot
                logger.warning("[UPS] mains is back, but the host shutdown has started: nothing is restarted")
                return
            _failsafe_engaged = False
            restart_stopped_apps()
        resume_copy_after_outage()


def resume_copy_after_outage() -> bool:
    """Mains power is back: a copy the failsafe paused carries on."""
    global _copy_paused_by_failsafe
    if not _copy_paused_by_failsafe:
        return False
    _copy_paused_by_failsafe = False
    Z_STATE.copy_paused = False
    Z_STATE.ui_wake.set()
    add_event(
        "info", "Copy Job Resumed", "Mains power is back; the paused copy carries on.", event_text("ups_copy_resumed")
    )
    return True
