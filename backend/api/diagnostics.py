# ZettNAS Toolkit - System Diagnostics & Support Bundle Router
import asyncio
import io
import json
import os
import platform
import sys
import time
import zipfile
from datetime import UTC, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response

import backend.config as config
from backend import __version__
from backend.auth import require_scope
from backend.config import EVENTS_FILE, FAN_STATE_FILE, LED_STATE_FILE, logger
from backend.fsutil import read_json
from backend.hardware.docker_stats import read_docker_containers
from backend.hardware.fans import set_fan_pwm
from backend.hardware.led import apply_led_state
from backend.hardware.memory import read_mem
from backend.hardware.pal_storage import get_storage_platform
from backend.hardware.screen import get_screen_state
from backend.hardware.storage import detect_chassis_model, get_chassis_friendly_name
from backend.hardware.ups import read_ups_status
from backend.ignored_errors import snapshot as ignored_snapshot
from backend.logging_config import get_recent_logs, sanitize_dict, sanitize_string
from backend.services.notifications import DEFAULT_NOTIFICATION_CONFIG, NOTIFICATIONS_FILE
from backend.state import Z_STATE

router = APIRouter(tags=["System Diagnostics"])

_DIAGNOSTICS_LOCK = asyncio.Lock()


def _build_bundle_sync(payload_dict: dict[str, Any] | None = None) -> bytes:
    t0 = time.time()

    # 1. System summary
    uptime_sec = 0.0
    try:
        if os.path.exists("/proc/uptime"):
            with open("/proc/uptime") as f:
                uptime_sec = float(f.read().split()[0])
        else:
            uptime_sec = round(time.time() - Z_STATE.boot_time, 1)
    except Exception:
        uptime_sec = round(time.time() - Z_STATE.boot_time, 1)

    ram_stats = {}
    try:
        ram_stats = read_mem()
    except Exception:
        logger.debug("backend.api.diagnostics._build_bundle_sync: ignored error", exc_info=True)

    try:
        pal_adapter = get_storage_platform()
        pal_caps = pal_adapter.get_capabilities().model_dump()
    except Exception:
        pal_caps = {"platform": "unknown"}

    system_summary = {
        "toolkit_version": __version__,
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": sys.version,
        },
        "chassis_model": get_chassis_friendly_name(detect_chassis_model()),
        "chassis_slug": detect_chassis_model(),
        "pal_capabilities": pal_caps,
        "cpu_count": os.cpu_count(),
        "memory": ram_stats,
        "uptime_seconds": uptime_sec,
    }

    # 2. Hardware telemetry
    fan_cfg = read_json(FAN_STATE_FILE, {})
    led_cfg = read_json(LED_STATE_FILE, {})
    ups_status = read_ups_status()
    screen_state = get_screen_state()
    detailed_fans = {}
    try:
        from backend.hardware.fans import get_detailed_fan_telemetry

        detailed_fans = get_detailed_fan_telemetry()
    except Exception as e:
        logger.debug(f"[Diagnostics] Error collecting fan telemetry: {e}")

    detailed_ups = {}
    try:
        from backend.hardware.ups import get_ups_diagnostic_telemetry

        detailed_ups = get_ups_diagnostic_telemetry()
    except Exception as e:
        logger.debug(f"[Diagnostics] Error collecting UPS telemetry: {e}")

    hardware_telemetry = {
        "fan_state_tracker": Z_STATE.fan_state_tracker,
        "fan_config": fan_cfg,
        "fan_telemetry_detailed": detailed_fans,
        "led_config": led_cfg,
        "ups_status": ups_status,
        "ups_telemetry_detailed": detailed_ups,
        "screen_state": screen_state,
        "fans_released": Z_STATE.fans_released,
        "critical_temp_active": Z_STATE.critical_temp_active,
    }

    # 3. Storage and SMART (decoupled from UI card layout, strictly spindown safe)
    storage_and_smart = {}
    try:
        from backend.hardware.storage_diagnostics import collect_storage_diagnostics

        storage_and_smart = collect_storage_diagnostics()
    except Exception as e:
        logger.warning(f"[Diagnostics] Error collecting storage diagnostics: {e}")
        storage_and_smart = {"error": str(e), "live_disk_telemetry": [], "pal_storage": {}}

    # 4. Kernel, CPU & Bus Telemetry
    kernel_telemetry = {}
    try:
        from backend.hardware.kernel_telemetry import collect_kernel_telemetry

        kernel_telemetry = collect_kernel_telemetry()
    except Exception as e:
        logger.warning(f"[Diagnostics] Error collecting kernel telemetry: {e}")
        kernel_telemetry = {"error": str(e)}

    # 5. Network topology
    net_topology = {}
    try:
        from backend.hardware.network import get_network_topology

        net_topology = get_network_topology()
    except Exception as e:
        logger.warning(f"[Diagnostics] Error collecting network topology: {e}")
        net_topology = {"error": str(e)}

    # 6. Docker Diagnostics & Container Manifests
    docker_diagnostics = {}
    sanitized_containers = []
    try:
        from backend.services.docker_diagnostics import collect_docker_diagnostics

        docker_diagnostics = collect_docker_diagnostics()
        containers = read_docker_containers()
        sanitized_containers = sanitize_dict(containers)
    except Exception as e:
        logger.warning(f"[Diagnostics] Error collecting docker diagnostics: {e}")
        docker_diagnostics = {"error": str(e), "containers_summary": {"total": 0, "running": 0, "troubled_names": []}}

    # 7. Virtual Machine Hypervisor Telemetry
    vm_hypervisor = {}
    try:
        from backend.api.vms import collect_vm_diagnostics

        vm_hypervisor = collect_vm_diagnostics()
    except Exception as e:
        logger.warning(f"[Diagnostics] Error collecting VM diagnostics: {e}")
        vm_hypervisor = {"error": str(e), "hypervisor_telemetry": {"active_vm_count": 0, "total_vm_count": 0}}

    # 8. Notifications (sanitized)
    notif_cfg = read_json(NOTIFICATIONS_FILE, DEFAULT_NOTIFICATION_CONFIG)
    try:
        from backend.services.notifications import mask_notification_config

        notif_cfg = mask_notification_config(notif_cfg)
    except Exception as e:
        logger.debug(f"[Diagnostics] Error masking notification config: {e}")
    sanitized_notifs = sanitize_dict(notif_cfg)

    # 9. System events (last 100)
    events = list(Z_STATE.event_log)
    if not events:
        try:
            events = read_json(EVENTS_FILE, [])
        except Exception:
            events = []

    # 10. Recent logs
    log_lines = get_recent_logs(max_lines=1000)
    recent_logs_text = "\n".join(log_lines)

    # 11. Executive Health Assessment
    degraded_disks = [
        str(d.get("name") or d.get("device") or "unnamed drive")
        for d in storage_and_smart.get("live_disk_telemetry", [])
        if isinstance(d, dict)
        and d.get("smart_status") in ("degraded", "failing", "error")
        or (
            isinstance(d, dict)
            and isinstance(d.get("smart"), dict)
            and d["smart"].get("status") in ("degraded", "failing", "error")
        )
    ]
    troubled_containers = docker_diagnostics.get("containers_summary", {}).get("troubled_names", [])
    has_cpu_throttle = kernel_telemetry.get("cpu_telemetry", {}).get("thermal_throttling_detected", False)
    port_conflicts = docker_diagnostics.get("port_conflicts", [])
    ups_blocked = detailed_ups.get("direct_usb_access", {}).get("permission_blocked", False)

    alerts = []
    if degraded_disks:
        alerts.append(
            {
                "level": "critical",
                "subsystem": "storage",
                "message": f"Degraded SMART health detected on drive(s): {', '.join(degraded_disks)}",
            }
        )
    if has_cpu_throttle:
        alerts.append(
            {
                "level": "warning",
                "subsystem": "cpu",
                "message": "CPU thermal throttling events detected in host dmesg",
            }
        )
    if troubled_containers:
        alerts.append(
            {
                "level": "warning",
                "subsystem": "docker",
                "message": f"Docker container(s) restarting, dead, or failing: {', '.join(troubled_containers)}",
            }
        )
    if port_conflicts:
        alerts.append(
            {
                "level": "warning",
                "subsystem": "network",
                "message": f"Host port conflicts detected on {len(port_conflicts)} port(s)",
            }
        )
    if ups_blocked:
        alerts.append(
            {
                "level": "warning",
                "subsystem": "ups",
                "message": "UPS USB device detected but container lacks read/write permissions to /dev/hidraw*",
            }
        )

    if any(a["level"] == "critical" for a in alerts):
        exec_status = "CRITICAL"
    elif alerts:
        exec_status = "ATTENTION_REQUIRED"
    else:
        exec_status = "HEALTHY"

    executive_summary = {
        "status": exec_status,
        "toolkit_version": __version__,
        "generated_at": datetime.now(UTC).isoformat(),
        "chassis": get_chassis_friendly_name(detect_chassis_model()),
        "platform": f"{platform.system()} {platform.release()}",
        "uptime_hours": round(uptime_sec / 3600, 1),
        "alerts": alerts,
        "metrics": {
            "ram_pct": ram_stats.get("pct", 0),
            "ram_used_gb": ram_stats.get("used_gb", 0),
            "ram_total_gb": ram_stats.get("total_gb", 0),
            "storage_pools": len(storage_and_smart.get("pal_storage", {}).get("pools", [])),
            "storage_drives": len(storage_and_smart.get("live_disk_telemetry", [])),
            "storage_standby": sum(1 for d in storage_and_smart.get("live_disk_telemetry", []) if d.get("standby")),
            "docker_total": docker_diagnostics.get("containers_summary", {}).get("total", 0),
            "docker_running": docker_diagnostics.get("containers_summary", {}).get("running", 0),
            "docker_troubled": len(troubled_containers),
            "vms_active": vm_hypervisor.get("hypervisor_telemetry", {}).get("active_vm_count", 0),
            "vms_total": vm_hypervisor.get("hypervisor_telemetry", {}).get("total_vm_count", 0),
        },
    }

    # Client-side telemetry if provided
    client_env = None
    frontend_logs_text = None
    if payload_dict:
        if "client_environment" in payload_dict and payload_dict["client_environment"]:
            client_env = sanitize_dict(payload_dict["client_environment"])
        if "frontend_logs" in payload_dict and payload_dict["frontend_logs"]:
            f_logs = payload_dict["frontend_logs"]
            f_lines = []
            for item in f_logs:
                ts = item.get("ts", "")
                lvl = item.get("level", "info").upper()
                src = item.get("source", "")
                msg = item.get("message", "")
                stack = item.get("stack", "")
                line_str = f"[{ts}] [{lvl}] [{src}] {msg}"
                if stack:
                    line_str += f"\n  Stack: {stack}"
                f_lines.append(sanitize_string(line_str))
            frontend_logs_text = "\n".join(f_lines)

    # Compress into zip in memory
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("executive_summary.json", json.dumps(sanitize_dict(executive_summary), indent=2))
        zf.writestr("system_summary.json", json.dumps(sanitize_dict(system_summary), indent=2))
        zf.writestr("hardware_telemetry.json", json.dumps(sanitize_dict(hardware_telemetry), indent=2))
        zf.writestr("storage_and_smart.json", json.dumps(sanitize_dict(storage_and_smart), indent=2))
        zf.writestr("kernel_telemetry.json", json.dumps(sanitize_dict(kernel_telemetry), indent=2))
        zf.writestr("docker_diagnostics.json", json.dumps(sanitize_dict(docker_diagnostics), indent=2))
        zf.writestr("vm_hypervisor.json", json.dumps(sanitize_dict(vm_hypervisor), indent=2))
        zf.writestr("network_topology.json", json.dumps(sanitize_dict(net_topology), indent=2))
        zf.writestr("container_manifests.json", json.dumps(sanitized_containers, indent=2))
        zf.writestr("notifications_summary.json", json.dumps(sanitized_notifs, indent=2))
        zf.writestr("system_events.json", json.dumps(sanitize_dict(events), indent=2))
        zf.writestr("ignored_errors.json", json.dumps(sanitize_dict(ignored_snapshot(top=100)), indent=2))
        zf.writestr("recent_logs.log", sanitize_string(recent_logs_text))
        # the log file and its rotated copies: what happened before the last restart (REL-28)
        from backend.logging_config import log_files

        for path in log_files():
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    zf.writestr(f"logs/{os.path.basename(path)}", sanitize_string(f.read()))
            except OSError:
                logger.debug("diagnostics: log file unreadable", exc_info=True)

        if client_env is not None:
            zf.writestr("client_environment.json", json.dumps(client_env, indent=2))
        if frontend_logs_text is not None:
            zf.writestr("frontend_console_errors.log", frontend_logs_text)

    zip_bytes = zip_buf.getvalue()
    elapsed = round(time.time() - t0, 3)
    logger.info(f"[DIAGNOSTICS] Generated bundle ({len(zip_bytes)} bytes) in {elapsed}s")
    return zip_bytes


def _build_summary_sync() -> dict[str, Any]:
    uptime_sec = 0.0
    try:
        if os.path.exists("/proc/uptime"):
            with open("/proc/uptime") as f:
                uptime_sec = float(f.read().split()[0])
        else:
            uptime_sec = round(time.time() - Z_STATE.boot_time, 1)
    except Exception:
        uptime_sec = round(time.time() - Z_STATE.boot_time, 1)

    ram = {}
    try:
        ram = read_mem()
    except Exception:
        logger.debug("backend.api.diagnostics._build_summary_sync: ignored error", exc_info=True)

    used_gb = ram.get("used_gb")
    total_gb = ram.get("total_gb")
    pct = ram.get("pct")
    if pct is None:
        pct = ram.get("used_percent", 0)
    if total_gb is None:
        total_gb = round(ram.get("total_bytes", 0) / (1024**3), 1)
    if used_gb is None:
        used_gb = round(ram.get("used_bytes", 0) / (1024**3), 1)

    chassis = get_chassis_friendly_name(detect_chassis_model())

    # Storage summary
    st = {}
    try:
        from backend.hardware.storage_diagnostics import collect_storage_diagnostics

        st = collect_storage_diagnostics()
    except Exception as e:
        logger.debug(f"[Diagnostics] Summary storage collection error: {e}")
    disks = st.get("live_disk_telemetry", [])
    standby_count = sum(1 for d in disks if d.get("standby"))
    pools = st.get("pal_storage", {}).get("pools", [])
    degraded_disks = [
        str(d.get("name") or d.get("device") or "unnamed drive")
        for d in disks
        if d.get("smart_status") in ("degraded", "failing", "error")
        or (
            isinstance(d, dict)
            and isinstance(d.get("smart"), dict)
            and d["smart"].get("status") in ("degraded", "failing", "error")
        )
    ]

    # Docker summary
    dock = {}
    try:
        from backend.services.docker_diagnostics import collect_docker_diagnostics

        dock = collect_docker_diagnostics()
    except Exception as e:
        logger.debug(f"[Diagnostics] Summary docker collection error: {e}")
    c_sum = dock.get("containers_summary", {})
    troubled_names = c_sum.get("troubled_names", [])

    # VM summary
    vms = {}
    try:
        from backend.api.vms import collect_vm_diagnostics

        vms = collect_vm_diagnostics()
    except Exception as e:
        logger.debug(f"[Diagnostics] Summary VM collection error: {e}")
    vm_tel = vms.get("hypervisor_telemetry", {})

    # Kernel & Throttling
    has_cpu_throttle = False
    try:
        from backend.hardware.kernel_telemetry import collect_kernel_telemetry

        kt = collect_kernel_telemetry()
        has_cpu_throttle = kt.get("cpu_telemetry", {}).get("thermal_throttling_detected", False)
    except Exception:
        logger.debug("backend.api.diagnostics._build_summary_sync: ignored error", exc_info=True)

    # UPS telemetry
    ups_tel = {}
    try:
        from backend.hardware.ups import get_ups_diagnostic_telemetry

        ups_tel = get_ups_diagnostic_telemetry()
    except Exception:
        logger.debug("backend.api.diagnostics._build_summary_sync: ignored error", exc_info=True)
    ups_mode = ups_tel.get("mode", "disabled")
    ups_connected = ups_tel.get("connected", False)
    ups_permission_blocked = ups_tel.get("direct_usb_access", {}).get("permission_blocked", False)

    # Compile Alerts
    alerts = []
    if degraded_disks:
        alerts.append(
            {
                "level": "critical",
                "message": f"Degraded SMART health detected on drive(s): {', '.join(degraded_disks)}",
            }
        )
    if has_cpu_throttle:
        alerts.append(
            {
                "level": "warning",
                "message": "CPU thermal throttling events detected in host dmesg",
            }
        )
    if troubled_names:
        alerts.append(
            {
                "level": "warning",
                "message": f"Containers requiring attention: {', '.join(troubled_names)}",
            }
        )
    if dock.get("port_conflicts"):
        alerts.append(
            {
                "level": "warning",
                "message": f"Host port conflicts detected across {len(dock['port_conflicts'])} port(s)",
            }
        )
    if ups_permission_blocked:
        alerts.append(
            {
                "level": "warning",
                "message": "UPS USB device detected but container lacks read/write permissions to /dev/hidraw*",
            }
        )

    if any(a["level"] == "critical" for a in alerts):
        executive_status = "CRITICAL"
    elif alerts:
        executive_status = "ATTENTION_REQUIRED"
    else:
        executive_status = "HEALTHY"

    # Generate Markdown
    md_lines = [
        "### ZettNAS Toolkit Support Diagnostics",
        f"- **Health Status:** `{executive_status}`",
        f"- **Toolkit Version:** `{__version__}`",
        f"- **Host OS / Kernel:** `{platform.system()} {platform.release()} ({platform.machine()})`",
        f"- **Chassis / Hardware:** `{chassis}`",
        f"- **Uptime:** `{round(uptime_sec / 3600, 1)} hours`",
        f"- **CPU / Cores:** `{os.cpu_count()} vCPUs`" + (" *(⚠️ Throttling Detected)*" if has_cpu_throttle else ""),
        f"- **Memory Usage:** `{pct}%` (`{used_gb} GB` of `{total_gb} GB` RAM)",
        f"- **Storage Topology:** `{len(pools)} pools`, `{len(disks)} drives` (`{standby_count} in standby`)"
        + (f" — ⚠️ Degraded: `{', '.join(degraded_disks)}`" if degraded_disks else ""),
        f"- **Docker Fleet:** `{c_sum.get('total', 0)} total` (`{c_sum.get('running', 0)} running`, `{c_sum.get('restarting', 0)} restarting`, `{c_sum.get('dead', 0)} dead`)"
        + (f" — ⚠️ Needs Attention: `{', '.join(troubled_names)}`" if troubled_names else ""),
        f"- **Virtual Machines:** `{vm_tel.get('total_vm_count', 0)} configured` (`{vm_tel.get('active_vm_count', 0)} running`)",
    ]
    _ign = ignored_snapshot(top=1)
    if _ign["total"]:
        md_lines.append(f"- **Ignored errors:** `{_ign['total']}` at {_ign['places']} place(s) since start")
    if ups_mode != "disabled":
        ups_status_str = "Connected (Online)" if ups_connected else "Standby / Offline"
        if ups_permission_blocked:
            ups_status_str += " — ⚠️ /dev/hidraw* Permission Blocked"
        md_lines.append(f"- **UPS Protection:** `{ups_status_str}` ({ups_mode.upper()} mode)")
    if dock.get("port_conflicts"):
        md_lines.append(f"- **Port Conflicts:** `⚠️ {len(dock['port_conflicts'])} conflict(s) detected`")

    return {
        "toolkit_version": __version__,
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": f"{platform.system()} {platform.release()}",
        "chassis": chassis,
        "uptime_hours": round(uptime_sec / 3600, 1),
        "executive_status": executive_status,
        "alerts": alerts,
        "memory": {
            "used_gb": used_gb,
            "total_gb": total_gb,
            "pct": pct,
            "used_percent": pct,
            "total_bytes": int(total_gb * (1024**3)),
            "used_bytes": int(used_gb * (1024**3)),
        },
        "storage": {
            "pools_count": len(pools),
            "disks_count": len(disks),
            "standby_count": standby_count,
            "degraded_disks": degraded_disks,
        },
        "docker": c_sum,
        "vms": vm_tel,
        "ups": {
            "mode": ups_mode,
            "connected": ups_connected,
            "permission_blocked": ups_permission_blocked,
        },
        "support_markdown": "\n".join(md_lines),
        "ignored_errors": ignored_snapshot(top=10),  # ARC-4
    }


@router.get(
    "/system/diagnostics-summary",
    dependencies=[Depends(require_scope("system:view", "system:read", "system:config"))],
)
async def get_diagnostics_summary():
    """
    Returns a fast diagnostic summary for in-browser inspection and support markdown generation.
    """
    return await asyncio.to_thread(_build_summary_sync)


@router.get(
    "/system/diagnostics-bundle",
    dependencies=[Depends(require_scope("system:config"))],
)
async def get_diagnostics_bundle():
    """Generates server-only diagnostics bundle via GET."""
    async with _DIAGNOSTICS_LOCK:
        zip_bytes = await asyncio.to_thread(_build_bundle_sync, None)

    timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"zettnas_diagnostics_{timestamp_str}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Content-Length": str(len(zip_bytes)),
        },
    )


@router.post(
    "/system/diagnostics-bundle",
    dependencies=[Depends(require_scope("system:config"))],
)
async def post_diagnostics_bundle(request: Request):
    """
    Generates an in-memory zip archive containing complete sanitized system & client diagnostics:
    - system_summary.json (platform, kernel, chassis, PAL mode, CPU/RAM, uptime)
    - hardware_telemetry.json (thermals, fan PWM/RPM, UPS status, screen)
    - storage_and_smart.json (disks layout, PAL pools, mounts audit, diskstats, SMART summary)
    - kernel_telemetry.json (dmesg alerts, CPU governors, thermal throttles, PCI/USB buses, hwmon)
    - docker_diagnostics.json (daemon health, system df, port conflicts, troubled container logs)
    - vm_hypervisor.json (KVM status, dynamic memory headroom, VM inventory, QEMU errors)
    - network_topology.json (physical NICs, speeds, duplex, bridges, bonds, routes, Docker bridge networks)
    - container_manifests.json (running containers and compose stacks with sensitive env vars redacted)
    - notifications_summary.json (configured channels with webhooks/tokens redacted)
    - system_events.json (last 100 system events)
    - recent_logs.log (sanitized structured log lines)
    - client_environment.json (optional, browser User-Agent, screen geometry, WebGL GPU telemetry)
    - frontend_console_errors.log (optional, sanitized client-side console errors ring buffer)
    """
    payload_dict = None
    try:
        body = await request.body()
        if body:
            payload_dict = json.loads(body)
    except Exception as e:
        logger.debug(f"[DIAGNOSTICS] Could not parse request body: {e}")

    async with _DIAGNOSTICS_LOCK:
        zip_bytes = await asyncio.to_thread(_build_bundle_sync, payload_dict)

    timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"zettnas_diagnostics_{timestamp_str}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Content-Length": str(len(zip_bytes)),
        },
    )
