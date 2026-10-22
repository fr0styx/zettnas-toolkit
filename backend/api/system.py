import asyncio
import functools
import io
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

import backend.config as config
from backend import __version__
from backend.api_tokens import load_tokens, revoke_token
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import (
    ALLOWED_BROWSE_ROOTS,
    BUTTON_CFG_FILE,
    DASH_LAYOUT_FILE,
    EVENTS_FILE,
    FAN_STATE_FILE,
    LED_STATE_FILE,
    logger,
)
from backend.confirmations import require_confirmation
from backend.db import query_copy_history
from backend.fsutil import atomic_write_json, read_json, resolve_within, root_for
from backend.hardware.disks import fetch_disk_smart_detail, locate_disk, run_disk_smart_test
from backend.hardware.docker_stats import container_action, read_docker_containers
from backend.hardware.fans import set_fan_pwm
from backend.hardware.led import apply_led_state
from backend.hardware.memory import read_mem
from backend.hardware.pal_storage import get_storage_platform
from backend.hardware.screen import get_screen_state, save_screen_state
from backend.hardware.storage import detect_chassis_model, get_chassis_friendly_name, get_current_layout
from backend.hardware.unraid import read_unraid_status
from backend.hardware.ups import read_ups_status
from backend.logging_config import get_recent_logs, sanitize_dict, sanitize_string
from backend.models.schemas import (
    ButtonConfigRequest,
    CopyConfirmRequest,
    DiskSmartTestRequest,
    DockerActionRequest,
    EjectMediaRequest,
    LayoutRequest,
    LcdPageRequest,
    MkdirRequest,
    ScreenConfigRequest,
    StartCopyRequest,
    StateRequest,
    SystemProfileRequest,
)
from backend.services.broadcaster import broadcaster
from backend.services.copy_engine import _do_copy
from backend.services.notifications import DEFAULT_NOTIFICATION_CONFIG, NOTIFICATIONS_FILE
from backend.state import Z_STATE, add_event

router = APIRouter(tags=["System & Storage"])


_PROCESS_STARTED = time.time()


def _daemon_status() -> dict:
    from backend.services.supervisor import daemon_status

    return daemon_status()


HEALTH_STARTUP_GRACE_SECS = 60.0


def _health_checks() -> dict[str, str]:
    """ok / starting / failed for each part the app can't work without (OPS-21)."""
    checks: dict[str, str] = {}
    hb = Z_STATE.collector_heartbeat
    if hb and time.time() - hb <= config.COLLECTOR_WATCHDOG_SECS:
        checks["collector"] = "ok"
    elif not hb and time.time() - _PROCESS_STARTED < HEALTH_STARTUP_GRACE_SECS:
        checks["collector"] = "starting"
    else:
        checks["collector"] = "failed"
    try:
        from backend.users_db import users_db_session

        with users_db_session(None) as conn:
            conn.execute("SELECT 1").fetchone()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "failed"
    checks["data_dir"] = "ok" if os.access(config.DATA_DIR, os.W_OK) else "failed"
    return checks


@router.get("/health")
def health():
    """Public health probe (no secrets) for Docker HEALTHCHECK, the updater and monitoring.

    HTTP 503 when a required part has failed (OPS-21); 200 while starting or healthy.
    """
    checks = _health_checks()
    hb = Z_STATE.collector_heartbeat
    if "failed" in checks.values():
        status = "degraded"
    elif "starting" in checks.values():
        status = "starting"
    else:
        status = "ok"
    body = {
        "status": status,
        "version": __version__,
        "checks": checks,
        "daemons": {k: {"state": v["state"], "restarts": v["restarts"]} for k, v in _daemon_status().items()},
        "collector_heartbeat_age": round(time.time() - hb, 1) if hb else None,
        "lcd_renderer_active": bool(Z_STATE.lcd_renderer_active),
        "fans_released": bool(Z_STATE.fans_released),
        "critical_temp_active": bool(Z_STATE.critical_temp_active),
    }
    return JSONResponse(body, status_code=503 if status == "degraded" else 200)


# Backward-compatibility re-exports for extracted domain routers
import logging

from backend.api.catalog import router as catalog_router
from backend.api.diagnostics import (
    _build_bundle_sync,
    _build_summary_sync,
)
from backend.api.diagnostics import (
    router as diagnostics_router,
)
from backend.api.docker import router as docker_router
from backend.api.fs import (
    ALLOWED_BROWSE_ROOTS,
    _contained,
    _do_mkdir,
    _safe_fs_target,
    _scan_remote_dir_isolated,
    check_user_path_access,
)
from backend.api.fs import (
    router as fs_router,
)
from backend.hardware.docker_stats import container_action, read_docker_containers

logger = logging.getLogger("ZettNAS")


@router.get("/disk_detail")
async def disk_detail(dev: str = "sda", wake: bool = False):
    if dev.startswith("/dev/"):
        dev = dev.replace("/dev/", "")
    m = re.match(r"^nv([0-9]+)$", dev)
    if m:
        dev = f"nvme{m.group(1)}n1"
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    return await asyncio.to_thread(fetch_disk_smart_detail, dev, wake)


@router.post("/disk_wake", dependencies=[Depends(require_scope("storage:write", "storage:admin"))])
async def disk_wake(payload: dict):
    dev = str(payload.get("dev", "sda"))
    if dev.startswith("/dev/"):
        dev = dev.replace("/dev/", "")
    m = re.match(r"^nv([0-9]+)$", dev)
    if m:
        dev = f"nvme{m.group(1)}n1"
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    detail = await asyncio.to_thread(fetch_disk_smart_detail, dev, True)
    return {"success": True, "dev": dev, "detail": detail}


@router.post("/disk/smart_test", dependencies=[Depends(require_scope("storage:admin"))])
async def disk_smart_test(req: DiskSmartTestRequest):
    dev = str(req.dev)
    test_type = str(req.test_type)
    if dev.startswith("/dev/"):
        dev = dev.replace("/dev/", "")
    m = re.match(r"^nv([0-9]+)$", dev)
    if m:
        dev = f"nvme{m.group(1)}n1"
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    return await asyncio.to_thread(run_disk_smart_test, dev, test_type)


@router.get("/disk/smart_tests")
async def get_disk_smart_tests(dev: str | None = None, limit: int = 20):
    """Returns persistent historical self-test runs and latest diagnostic report."""
    if dev:
        if dev.startswith("/dev/"):
            dev = dev.replace("/dev/", "")
        m = re.match(r"^nv([0-9]+)$", dev)
        if m:
            dev = f"nvme{m.group(1)}n1"
        if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
            raise HTTPException(status_code=400, detail="Invalid device parameter.")
    from backend.db import get_latest_smart_test_result, get_smart_test_history

    history = await asyncio.to_thread(get_smart_test_history, dev, limit)
    latest = await asyncio.to_thread(get_latest_smart_test_result, dev) if dev else None
    active = None
    if dev:
        with Z_STATE.lock:
            active = Z_STATE.active_smart_tests.get(dev)
    return {
        "success": True,
        "dev": dev,
        "active_test": active,
        "latest_report": latest,
        "history": history,
    }


@router.post("/disk/locate", dependencies=[Depends(require_scope("storage:write", "storage:admin"))])
async def disk_locate_endpoint(payload: dict):
    dev = str(payload.get("dev", "sda"))
    duration = int(payload.get("duration", 5))
    if dev.startswith("/dev/"):
        dev = dev.replace("/dev/", "")
    m = re.match(r"^nv([0-9]+)$", dev)
    if m:
        dev = f"nvme{m.group(1)}n1"
    from backend.hardware.disks import VALID_DEV_PATTERN

    if not VALID_DEV_PATTERN.fullmatch(dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    return await asyncio.to_thread(locate_disk, dev, duration)


@router.get("/screen")
def screen_state():
    return get_screen_state()


@router.post("/screen", dependencies=[Depends(require_scope("system:config"))])
async def post_screen_state(req: ScreenConfigRequest):
    data = req.model_dump(exclude_unset=True)
    return await asyncio.to_thread(save_screen_state, data)


@router.post(
    "/copy/eject",
    dependencies=[Depends(require_scope("storage:write", "storage:admin"))],
)
def eject_media(req: EjectMediaRequest | None = None):
    from backend.services.copy_engine import eject_media_slot

    slot = req.slot if req and req.slot else "sd"
    return eject_media_slot(slot)


BUTTON_DEFAULTS = {
    "enabled": False,
    "action": "copy",
    "auto_ingest": False,
    "require_confirmation": True,
    "source": "sd",
    "dest": "/mnt/user/",
    "use_exif": True,
    "verify_checksum": True,
    "on_collision": "skip",
}


def _load_buttons():
    state = dict(BUTTON_DEFAULTS)
    saved = read_json(BUTTON_CFG_FILE, {})
    if isinstance(saved, dict):
        state.update(saved)
    return state


@router.post(
    "/copy/cancel", dependencies=[Depends(require_scope("storage:write", "shares:user_write", "storage:admin"))]
)
def copy_cancel():
    Z_STATE.copy_abort_flag = True
    Z_STATE.copy_overwrite_choice = "cancel"
    Z_STATE.copy_confirm_event.set()
    if not Z_STATE.copy_active:
        Z_STATE.copy_status = "idle"
        Z_STATE.ui_wake.set()
    return {"status": "ok"}


@router.post(
    "/copy/confirm", dependencies=[Depends(require_scope("storage:write", "shares:user_write", "storage:admin"))]
)
def copy_confirm(req: CopyConfirmRequest):
    Z_STATE.copy_overwrite_choice = req.action
    Z_STATE.copy_confirm_event.set()
    return {"status": "ok"}


@router.post(
    "/copy/pause", dependencies=[Depends(require_scope("storage:write", "shares:user_write", "storage:admin"))]
)
def pause_copy():
    Z_STATE.copy_paused = True
    return {"status": "paused"}


@router.post(
    "/copy/resume", dependencies=[Depends(require_scope("storage:write", "shares:user_write", "storage:admin"))]
)
def resume_copy():
    Z_STATE.copy_paused = False
    return {"status": "resumed"}


@router.post(
    "/copy/start", dependencies=[Depends(require_scope("storage:write", "shares:user_write", "storage:admin"))]
)
def start_copy(req: StartCopyRequest | None = None):
    if Z_STATE.copy_active:
        raise HTTPException(status_code=409, detail="Copy operation already in progress")
    cfg = _load_buttons()
    if req:
        if req.source:
            cfg["source"] = req.source
        if req.dest:
            cfg["dest"] = req.dest
        if req.use_exif is not None:
            cfg["use_exif"] = req.use_exif
    Z_STATE.pending_ingest = None
    Z_STATE.copy_active = True
    Z_STATE.copy_status = "copying"
    Z_STATE.ui_wake.set()
    src_label = str(cfg.get("source", "media slot")).upper()
    add_event("info", "Copy Started", f"Starting ingest from {src_label}...")
    threading.Thread(target=lambda c: asyncio.run(_do_copy(c)), args=(cfg,), daemon=True).start()
    return {"status": "started"}


@router.post(
    "/copy/dismiss-ingest", dependencies=[Depends(require_scope("storage:write", "shares:user_write", "storage:admin"))]
)
def dismiss_pending_ingest():
    Z_STATE.pending_ingest = None
    Z_STATE.ui_wake.set()
    return {"status": "dismissed"}


@router.post(
    "/copy/rescan", dependencies=[Depends(require_scope("storage:write", "shares:user_write", "storage:admin"))]
)
def rescan_media():
    from backend.services.copy_engine import rescan_media_slots

    slots = rescan_media_slots(force_usb_reset=True)
    return {"status": "ok", "slots": slots}


@router.get("/buttons")
def get_buttons():
    return _load_buttons()


@router.post("/buttons", dependencies=[Depends(require_scope("system:config"))])
def post_buttons(req: ButtonConfigRequest):
    data = req.model_dump(exclude_unset=True)
    state = _load_buttons()
    if "dest" in data:
        real = _contained(data["dest"])
        if not os.path.isdir(real):
            raise HTTPException(status_code=400, detail="Destination must be a folder.")
        data["dest"] = real
    if "enabled" in data and "action" not in data:
        data["action"] = "copy" if data["enabled"] else "cycle_lcd"
    state.update(data)
    atomic_write_json(BUTTON_CFG_FILE, state)
    if data.get("auto_ingest") is False:
        with Z_STATE.lock:
            Z_STATE.pending_ingest = None
        Z_STATE.ui_wake.set()
    return state


@router.delete("/events/clear", dependencies=[Depends(require_scope("system:config"))])
def clear_events():
    with Z_STATE.lock:
        Z_STATE.event_log = []
    if os.path.exists(EVENTS_FILE):
        try:
            os.remove(EVENTS_FILE)
        except OSError:
            pass
    return {"status": "ok"}


@router.get("/layout")
def get_layout():
    return get_current_layout()


@router.post(
    "/layout",
    dependencies=[Depends(require_scope("system:config", "shares:user_write"))],
)
def post_layout(req: LayoutRequest):
    data = req.model_dump()
    data["sizes"] = {k: v for k, v in data["sizes"].items() if v in ("full", "compact")}
    data["version"] = int(time.time() * 1000)
    atomic_write_json(DASH_LAYOUT_FILE, data)
    with Z_STATE.lock:
        if Z_STATE.cached_stats:
            Z_STATE.cached_stats["layout"] = data
            stats_copy = dict(Z_STATE.cached_stats)
        else:
            stats_copy = {"layout": data}
    broadcaster.broadcast(stats_copy, full_data=stats_copy)
    Z_STATE.ui_wake.set()
    return {"status": "ok", "layout": data}


@router.post(
    "/state",
    dependencies=[Depends(require_scope("system:config", "shares:user_write"))],
)
def post_state(req: StateRequest):
    if req.fb is not None:
        config.ENABLE_FB = bool(req.fb)
    return {"status": "ok"}


@router.get("/lcd/page")
def get_lcd_page():
    return {
        "page": Z_STATE.current_lcd_page,
        "cycle_seconds": Z_STATE.lcd_cycle_seconds,
    }


@router.post("/lcd/page", dependencies=[Depends(require_scope("system:config", "hardware:fans"))])
def post_lcd_page(req: LcdPageRequest):
    if req.page is not None:
        Z_STATE.set_lcd_page(req.page)
    if req.cycle_seconds is not None:
        with Z_STATE.lock:
            Z_STATE.lcd_cycle_seconds = req.cycle_seconds
            Z_STATE.last_lcd_cycle_time = time.time()
        Z_STATE.ui_wake.set()
    return {
        "status": "ok",
        "page": Z_STATE.current_lcd_page,
        "cycle_seconds": Z_STATE.lcd_cycle_seconds,
    }


@router.post("/lcd/cycle", dependencies=[Depends(require_scope("system:config", "hardware:fans"))])
def post_lcd_cycle():
    new_page = Z_STATE.cycle_lcd_page()
    return {"status": "ok", "page": new_page}


@router.get("/copy/history")
def get_copy_history(limit: int = 50):
    return query_copy_history(limit)


@router.get("/unraid")
def get_unraid_telemetry():
    return read_unraid_status(force=True)


@router.post("/system/profile", dependencies=[Depends(require_scope("system:config"))])
def set_system_profile(req: SystemProfileRequest):
    profile = req.profile.lower()
    # Profile mappings:
    # auto: fan auto dynamic curve, LED dynamic/current
    # quiet: fan quiet (37%), LED 20%
    # balanced: fan balanced (60%), LED 50%
    # performance: fan performance (85%), LED 100%
    fan_cfg = read_json(FAN_STATE_FILE, {})
    led_cfg = read_json(LED_STATE_FILE, {})

    if profile == "auto":
        fan_cfg["profile"] = "auto"
        led_cfg["brightness"] = led_cfg.get("brightness", 50)
    elif profile == "quiet":
        fan_cfg["profile"] = "quiet"
        fan_cfg["manual_pct"] = 37
        led_cfg["brightness"] = 20
    elif profile == "performance":
        fan_cfg["profile"] = "performance"
        fan_cfg["manual_pct"] = 85
        led_cfg["brightness"] = 100
    else:  # balanced
        fan_cfg["profile"] = "balanced"
        fan_cfg["manual_pct"] = 60
        led_cfg["brightness"] = 50

    atomic_write_json(FAN_STATE_FILE, fan_cfg)
    atomic_write_json(LED_STATE_FILE, led_cfg)

    if not Z_STATE.critical_temp_active:
        set_fan_pwm(fan_cfg["profile"], fan_cfg.get("manual_pct", 60), ctrl_cpu_fan=fan_cfg.get("ctrl_cpu_fan", False))
    else:
        logger.warning("[FANS] Critical temperature active; preserving maximum fan PWM clamp.")
    apply_led_state(led_cfg)
    Z_STATE.ui_wake.set()

    return {"status": "ok", "profile": profile, "fan": fan_cfg, "led": led_cfg}


class TokenCreateRequest(BaseModel):
    name: str
    scopes: list[str] | None = None
    role_id: str | None = None
    expires_in_days: int | None = None


@router.get("/tokens", dependencies=[Depends(require_scope("users:read", "system:config"))])
def list_tokens(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    try:
        from backend.users_db import list_user_api_tokens

        user_id = principal.user_id if principal else "admin-00000000-0000-0000-0000-000000000001"
        tokens_db = list_user_api_tokens(user_id)
        if tokens_db:
            res = []
            for t in tokens_db:
                scopes_val = t.get("scopes_json")
                if isinstance(scopes_val, str):
                    try:
                        scopes_list = json.loads(scopes_val)
                    except Exception:
                        scopes_list = ["*"]
                else:
                    scopes_list = t.get("scopes", ["*"])
                res.append(
                    {
                        "id": str(t.get("token_id")),
                        "masked_token": t.get("masked_token", "zat_..."),
                        "name": t.get("name"),
                        "scopes": scopes_list,
                        "created": t.get("created_at"),
                        "expires_at": t.get("expires_at"),
                        "last_used_at": t.get("last_used_at"),
                    }
                )
            return res
    except Exception as e:
        logger.warning(f"Could not load tokens from users.db: {e}")

    tokens = load_tokens()
    res = []
    for tid, data in tokens.items():
        res.append(
            {
                "id": str(tid),
                "masked_token": data.get("masked_token", "zat_..."),
                "name": data.get("name"),
                "scopes": data.get("scopes", ["*"]),
                "created": data.get("created"),
            }
        )
    return res


@router.post("/tokens", dependencies=[Depends(require_scope("users:write", "system:config"))])
def create_token(req: TokenCreateRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    if principal and principal.role_id != "superadmin" and not principal.has_scope("*"):
        caller_scopes = set(principal.scopes or [])
        requested_scopes = set(req.scopes or [])
        if "*" in requested_scopes and "*" not in caller_scopes:
            raise HTTPException(status_code=403, detail="Cannot create wildcard token without wildcard privileges.")
        unheld_scopes = requested_scopes - caller_scopes
        if unheld_scopes:
            raise HTTPException(
                status_code=403,
                detail=f"Cannot grant scopes you do not possess: {', '.join(sorted(unheld_scopes))}",
            )

    user_id = principal.user_id if principal else "admin-00000000-0000-0000-0000-000000000001"
    try:
        from backend.users_db import create_scoped_api_token

        raw_token, meta = create_scoped_api_token(
            user_id=user_id,
            name=req.name,
            scopes=req.scopes,
            expires_in_days=req.expires_in_days,
        )
        add_event("success", "Security", f"Generated new scoped API token: {req.name}")
        try:
            from backend.users_db import log_security_event

            log_security_event(
                "api_token.created",
                "success",
                actor_id=getattr(principal, "user_id", None),
                actor_username=getattr(principal, "username", None),
                details={"name": req.name, "scopes": meta.get("scopes")},
            )
        except Exception:
            logger.debug("backend.api.system.create_token: ignored error", exc_info=True)
        return {
            "token": raw_token,
            "name": req.name,
            "token_id": meta["token_id"],
            "scopes": meta["scopes"],
            "masked_token": meta["masked_token"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Could not create API token: {e}")
        raise HTTPException(status_code=500, detail="Could not create the API token.") from e


@router.delete("/tokens/{token_id}", dependencies=[Depends(require_scope("users:write", "system:config"))])
def delete_token(token_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    user_id = None
    if principal and principal.role_id != "superadmin" and not principal.has_scope("*"):
        user_id = principal.user_id

    revoked = False
    try:
        from backend.users_db import revoke_scoped_api_token

        revoked = revoke_scoped_api_token(token_id, user_id=user_id)
    except Exception as e:
        logger.warning(f"Could not revoke token via users_db: {e}")
    if not revoked and (not user_id or (principal and (principal.role_id == "superadmin" or principal.has_scope("*")))):
        revoked = revoke_token(token_id)
    if revoked:
        add_event("info", "Security", "Revoked an API token")
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Token not found or unauthorized to revoke.")


def trigger_power_action(action: str) -> bool:
    """
    Triggers host system reboot or shutdown.
    Checks host trigger scripts, container-host volume mounts, and system power commands.
    """
    if os.environ.get("TESTING") == "1" or os.environ.get("ZETTNAS_TEST_MODE") == "1":
        logger.info(f"[Power] Test mode active; harmlessly mocked host trigger for '{action}'")
        return True

    if action == "reboot":
        triggers = [
            ["/host/reboot"],
            ["/usr/local/sbin/reboot"],
            ["reboot"],
            ["shutdown", "-r", "now"],
        ]
    else:
        triggers = [
            ["/host/powerdown"],
            ["/usr/local/sbin/powerdown"],
            ["/sbin/poweroff"],
            ["poweroff"],
            ["shutdown", "-h", "now"],
        ]

    for cmd in triggers:
        bin_path = cmd[0]
        if os.path.exists(bin_path) and os.access(bin_path, os.X_OK):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info(f"[Power] Executed host trigger: {cmd}")
                return True
            except Exception as e:
                logger.error(f"[Power] Failed executing host trigger {cmd}: {e}")
        elif shutil.which(bin_path):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info(f"[Power] Executed command: {cmd}")
                return True
            except Exception as e:
                logger.error(f"[Power] Failed executing command {cmd}: {e}")

    try:
        if os.path.exists("/proc/sysrq-trigger"):
            with open("/proc/sysrq-trigger", "w") as f:
                f.write("b" if action == "reboot" else "o")
            return True
    except Exception as e:
        logger.debug(f"[Power] Sysrq fallback failed: {e}")

    return False


@router.post(
    "/system/reboot",
    dependencies=[Depends(require_scope("system:power")), Depends(require_confirmation("system.reboot"))],
)
async def system_reboot():
    """Trigger system reboot (requires system:power scope)."""
    add_event("warning", "System", "System reboot sequence initiated by authorized user")
    success = await asyncio.to_thread(trigger_power_action, "reboot")
    return {"status": "ok", "action_dispatched": success, "message": "System reboot sequence initiated"}


@router.post(
    "/system/shutdown",
    dependencies=[Depends(require_scope("system:power")), Depends(require_confirmation("system.shutdown"))],
)
async def system_shutdown():
    """Trigger system poweroff (requires system:power scope)."""
    add_event("warning", "System", "System shutdown sequence initiated by authorized user")
    success = await asyncio.to_thread(trigger_power_action, "shutdown")
    return {"status": "ok", "action_dispatched": success, "message": "System shutdown sequence initiated"}


@router.get("/system/disks", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_system_disks() -> dict[str, Any]:
    """Compatibility endpoint returning physical disks discovered via HAL."""
    from backend.hardware.hal import DiskDiscoveryHAL

    records = DiskDiscoveryHAL.discover_physical_disks()
    return {
        "disks": [
            {
                "dev": r.dev_name,
                "name": r.dev_name,
                "size": getattr(r, "size_formatted", getattr(r, "size_human", "0 GB")),
                "size_bytes": r.size_bytes,
                "model": r.model,
                "serial": r.serial,
                "role": r.role,
                "transport": r.transport,
            }
            for r in records
        ]
    }


_last_update_check: dict[str, dict[str, Any]] = {
    "stable": {"ts": 0.0, "data": None},
    "edge": {"ts": 0.0, "data": None},
}


@functools.lru_cache(maxsize=1)
def _get_current_build_info_cached() -> dict[str, Any]:
    return _get_current_build_info_impl()


def _get_current_build_info() -> dict[str, Any]:
    if os.environ.get("TESTING") == "1" or os.environ.get("ZETTNAS_TEST_MODE") == "1":
        return _get_current_build_info_impl()
    return _get_current_build_info_cached()


def _get_current_build_info_impl() -> dict[str, Any]:
    """Returns detected build commit, build date, and container revision."""
    commit = os.environ.get("BUILD_COMMIT", "")
    created = os.environ.get("BUILD_DATE", "")

    # Try inspecting self container and image for authoritative OCI revision label
    if not commit:
        try:
            from backend.services.compose_synthesizer import fetch_container_raw_inspect
            from backend.services.container_mutator import _docker_request

            cid = socket.gethostname()
            data = fetch_container_raw_inspect(cid) or fetch_container_raw_inspect("zettnas-toolkit")
            if data and isinstance(data, dict):
                # 1. Authoritative check on underlying image metadata
                img_id = data.get("Image")
                if img_id:
                    try:
                        st_img, img_data = _docker_request("GET", f"/images/{img_id}/json")
                        if st_img == 200 and isinstance(img_data, dict):
                            img_labels = img_data.get("Config", {}).get("Labels", {})
                            commit = img_labels.get("org.opencontainers.image.revision", "")
                            if not created:
                                created = img_labels.get("org.opencontainers.image.created", "")
                    except Exception:
                        logger.debug("backend.api.system._get_current_build_info_impl: ignored error", exc_info=True)

                # 2. Container labels fallback
                if not commit:
                    labels = data.get("Config", {}).get("Labels", {})
                    commit = labels.get("org.opencontainers.image.revision", "")
                    if not created:
                        created = labels.get("org.opencontainers.image.created", "")
        except Exception:
            logger.debug("backend.api.system._get_current_build_info_impl: ignored error", exc_info=True)

    if not commit:
        for p in ("/app/.git_commit", "data/.git_commit", ".git_commit"):
            if os.path.exists(p):
                try:
                    with open(p) as f:
                        commit = f.read().strip()
                except Exception:
                    logger.debug("backend.api.system._get_current_build_info_impl: ignored error", exc_info=True)

    if not commit:
        try:
            import subprocess

            res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=2.0)
            if res.returncode == 0 and res.stdout.strip():
                commit = res.stdout.strip()
        except Exception:
            logger.debug("backend.api.system._get_current_build_info_impl: ignored error", exc_info=True)

    return {
        "commit": commit[:7] if commit else "",
        "full_commit": commit,
        "build_date": created,
    }


def _parse_version(v_str: str) -> list[int]:
    """Parse version string into integer tuple for comparison."""
    clean = re.sub(r"^[^\d]*", "", str(v_str or "").strip())
    parts = re.findall(r"\d+", clean)
    return [int(p) for p in parts] if parts else [0]


def _is_newer_version(latest_str: str, current_str: str) -> bool:
    try:
        latest = _parse_version(latest_str)
        current = _parse_version(current_str)
        max_len = max(len(latest), len(current))
        latest.extend([0] * (max_len - len(latest)))
        current.extend([0] * (max_len - len(current)))
        return latest > current
    except Exception:
        return latest_str.strip() != current_str.strip()


@router.get("/system/about")
async def get_system_about():
    """Returns high-level system information, current version, chassis twin, and runtime stats."""
    import platform
    import sys

    from backend.hardware.storage import detect_chassis_model, get_chassis_friendly_name

    chassis = detect_chassis_model()
    boot_time = getattr(Z_STATE, "boot_time", None) or time.time()
    uptime_secs = round(time.time() - boot_time, 1)
    binfo = _get_current_build_info()

    return {
        "name": "ZettNAS Workbench",
        "version": __version__,
        "tag": f"v{__version__}",
        "commit": binfo["commit"],
        "build_date": binfo["build_date"],
        "release_channel": "stable",
        "chassis_model": get_chassis_friendly_name(chassis),
        "chassis_slug": chassis,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "uptime_secs": uptime_secs,
        "containerized": os.path.exists("/.dockerenv")
        or os.environ.get("CONTAINERIZED") == "1"
        or os.path.exists("/app"),
        "github_repo": "https://github.com/fr0styx/zettnas-toolkit",
    }


_IMAGE_REPO = "ghcr.io/fr0styx/zettnas-toolkit"
_MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


async def _registry_digest(tag: str) -> str | None:
    """Digest GHCR currently serves for a tag of our image (anonymous pull token)."""
    import httpx

    repo = _IMAGE_REPO.split("/", 1)[1]
    async with httpx.AsyncClient(timeout=6.0) as client:
        tok = await client.get("https://ghcr.io/token", params={"scope": f"repository:{repo}:pull"})
        token = tok.json().get("token") if tok.status_code == 200 else None
        if not token:
            return None
        res = await client.head(
            f"https://ghcr.io/v2/{repo}/manifests/{tag}",
            headers={"Authorization": f"Bearer {token}", "Accept": _MANIFEST_ACCEPT},
        )
        return res.headers.get("docker-content-digest") if res.status_code == 200 else None


def _running_repo_digests() -> list[str]:
    """Registry digests of the image this container runs (empty for a locally built image)."""
    from backend.services.compose_synthesizer import fetch_container_raw_inspect
    from backend.services.container_mutator import _docker_request

    info = fetch_container_raw_inspect(socket.gethostname()) or fetch_container_raw_inspect("zettnas-toolkit") or {}
    image_id = info.get("Image")
    if not image_id:
        return []
    st, img = _docker_request("GET", f"/images/{image_id}/json")
    if st != 200 or not isinstance(img, dict):
        return []
    prefix = _IMAGE_REPO + "@"
    return [d[len(prefix) :] for d in img.get("RepoDigests") or [] if d.startswith(prefix)]


_IMAGE_REF_RE = re.compile(
    r"^ghcr\.io/fr0styx/zettnas-toolkit(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?(?:@sha256:[0-9a-f]{64})?$"
)


def _is_official_image_ref(ref: str) -> bool:
    return bool(_IMAGE_REF_RE.match(str(ref or "").strip()))


def _local_repo_digests(image_ref: str) -> list[str]:
    """Registry digests of a local image that belong to our repository."""
    from backend.services.container_mutator import _docker_request

    st, img = _docker_request("GET", f"/images/{image_ref}/json")
    if st != 200 or not isinstance(img, dict):
        return []
    prefix = _IMAGE_REPO + "@"
    return [d[len(prefix) :] for d in img.get("RepoDigests") or [] if d.startswith(prefix)]


@router.get("/system/updates")
async def check_system_updates(force: bool = False, channel: str = "stable"):
    """Release/commit check, then a registry digest check (OPS-18).

    Version strings and commit hashes say a newer release exists; only the image
    digest says whether the image this channel serves differs from the one running.
    When both digests are known they decide update_available.
    """
    result = await _check_system_updates_by_version(force=force, channel=channel)
    if result.get("digest_checked"):
        return result
    tag = "edge" if result.get("channel") == "edge" else "latest"
    try:
        remote = await _registry_digest(tag)
    except Exception as e:
        logger.debug(f"[System Update] Registry digest lookup failed: {e}")
        remote = None
    try:
        local = await asyncio.to_thread(_running_repo_digests)
    except Exception as e:
        logger.debug(f"[System Update] Could not read the running image digest: {e}")
        local = []
    result["registry_digest"] = remote
    result["running_digests"] = local
    result["digest_checked"] = True
    if remote and local:
        newer_by_version = bool(result.get("update_available"))
        result["update_available"] = remote not in local
        result["update_basis"] = "digest"
        if newer_by_version and not result["update_available"]:
            result["note"] = "A newer version exists, but its image is not published for this channel yet."
    else:
        result["update_basis"] = "version"
    return result


async def _check_system_updates_by_version(force: bool = False, channel: str = "stable"):
    """Check GitHub Releases (stable) or GitHub Commits on main (edge) with in-memory caching."""
    import httpx

    channel_key = "edge" if str(channel or "").lower() == "edge" else "stable"
    now = time.time()
    cache_entry = _last_update_check.get(channel_key, {"ts": 0.0, "data": None})
    if not force and cache_entry.get("data") and (now - cache_entry.get("ts", 0) < 300):
        return cache_entry["data"]

    binfo = _get_current_build_info()
    current_commit = binfo["commit"]

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": f"ZettNAS-Workbench/{__version__}",
    }

    if channel_key == "edge":
        url = "https://api.github.com/repos/fr0styx/zettnas-toolkit/commits/main"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    latest_sha = data.get("sha", "")[:7]
                    full_sha = data.get("sha", "")
                    commit_obj = data.get("commit", {})
                    msg = (commit_obj.get("message") or "").split("\n")[0]
                    author = commit_obj.get("author", {}).get("name", "fr0styx")
                    published_at = commit_obj.get("author", {}).get("date")
                    # If current commit is known, compare hashes (support both 7-char prefix and full SHA)
                    update_available = bool(
                        current_commit
                        and latest_sha
                        and not (
                            current_commit.lower().startswith(latest_sha[:7].lower())
                            or latest_sha.lower().startswith(current_commit[:7].lower())
                        )
                    )
                    result = {
                        "channel": "edge",
                        "current_version": __version__,
                        "current_commit": current_commit,
                        "latest_version": latest_sha,
                        "latest_tag": f"main@{latest_sha}",
                        "update_available": update_available,
                        "release_name": f"main @ {latest_sha}: {msg}",
                        "release_url": f"https://github.com/fr0styx/zettnas-toolkit/commit/{full_sha}",
                        "published_at": published_at,
                        "release_notes": f"Author: {author}\nCommit: {latest_sha}\nMessage: {msg}",
                        "checked_at": now,
                        "error": None,
                    }
                    _last_update_check["edge"] = {"ts": now, "data": result}
                    return result
                error_msg = f"GitHub API HTTP {resp.status_code}"
        except Exception as e:
            error_msg = str(e)

        fallback = {
            "channel": "edge",
            "current_version": __version__,
            "current_commit": current_commit,
            "latest_version": current_commit or "unknown",
            "latest_tag": f"main@{current_commit}" if current_commit else "main",
            "update_available": False,
            "release_name": "Edge Channel (Latest Commits)",
            "release_url": "https://github.com/fr0styx/zettnas-toolkit/commits/main",
            "published_at": None,
            "release_notes": "",
            "checked_at": now,
            "error": error_msg,
        }
        return fallback

    # Stable channel
    url = "https://api.github.com/repos/fr0styx/zettnas-toolkit/releases/latest"

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                tag = data.get("tag_name", "").strip()
                clean_tag = tag.lstrip("v")
                update_available = _is_newer_version(clean_tag, __version__)

                result = {
                    "channel": "stable",
                    "current_version": __version__,
                    "current_commit": current_commit,
                    "latest_version": clean_tag or tag,
                    "latest_tag": tag,
                    "update_available": update_available,
                    "release_name": data.get("name") or tag,
                    "release_url": data.get("html_url")
                    or f"https://github.com/fr0styx/zettnas-toolkit/releases/tag/{tag}",
                    "published_at": data.get("published_at"),
                    "release_notes": data.get("body", ""),
                    "checked_at": now,
                    "error": None,
                }
                _last_update_check["stable"] = {"ts": now, "data": result}
                return result
            elif resp.status_code == 404:
                # Fallback to tags endpoint if no releases are formally drafted
                tags_resp = await client.get(
                    "https://api.github.com/repos/fr0styx/zettnas-toolkit/tags", headers=headers
                )
                if tags_resp.status_code == 200 and tags_resp.json():
                    latest_tag = tags_resp.json()[0].get("name", "")
                    clean_tag = latest_tag.lstrip("v")
                    update_available = _is_newer_version(clean_tag, __version__)
                    result = {
                        "channel": "stable",
                        "current_version": __version__,
                        "current_commit": current_commit,
                        "latest_version": clean_tag or latest_tag,
                        "latest_tag": latest_tag,
                        "update_available": update_available,
                        "release_name": f"Release {latest_tag}",
                        "release_url": f"https://github.com/fr0styx/zettnas-toolkit/releases/tag/{latest_tag}",
                        "published_at": None,
                        "release_notes": "",
                        "checked_at": now,
                        "error": None,
                    }
                    _last_update_check["stable"] = {"ts": now, "data": result}
                    return result

            error_msg = f"GitHub API HTTP {resp.status_code}"
    except Exception as e:
        error_msg = str(e)

    fallback = {
        "channel": "stable",
        "current_version": __version__,
        "current_commit": current_commit,
        "latest_version": __version__,
        "latest_tag": f"v{__version__}",
        "update_available": False,
        "release_name": f"ZettNAS v{__version__}",
        "release_url": "https://github.com/fr0styx/zettnas-toolkit/releases",
        "published_at": None,
        "release_notes": "",
        "checked_at": now,
        "error": error_msg,
    }
    return fallback


class ApplySystemUpdateRequest(BaseModel):
    channel: str = "stable"
    target_image: str | None = None


@router.post(
    "/system/updates/apply",
    dependencies=[
        Depends(require_scope("system:power", "system:manage")),
        Depends(require_confirmation("updates.apply")),
    ],
)
async def post_apply_system_update(req: ApplySystemUpdateRequest):
    """
    Pulls the latest ZettNAS image and initiates a graceful self-update.
    """
    from backend.services.container_mutator import pull_container_image
    from backend.services.self_updater import spawn_self_updater

    channel = "edge" if req.channel.lower() == "edge" else "stable"
    if req.target_image:
        # Only this project's images: an update must never install an arbitrary image
        # with full access to the Docker socket and host devices.
        if not _is_official_image_ref(req.target_image):
            raise HTTPException(status_code=400, detail=f"Updates can only install {_IMAGE_REPO} images.")
        target_img = req.target_image
    elif channel == "edge":
        target_img = "ghcr.io/fr0styx/zettnas-toolkit:edge"
    else:
        target_img = "ghcr.io/fr0styx/zettnas-toolkit:latest"

    # Invalidate cached update check so immediate post-update checks reflect the new state
    _last_update_check[channel]["data"] = None
    _last_update_check[channel]["ts"] = 0.0

    logger.info(f"[System Update] User initiated system update on '{channel}' channel using image '{target_img}'...")

    # 1. Pull the image
    try:
        await asyncio.to_thread(pull_container_image, target_img, 300.0)
    except Exception as exc:
        logger.error(f"[System Update] Image pull failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to pull image: {exc}") from exc

    # 1b. The pulled image must carry a digest from our registry repository.
    try:
        pulled = await asyncio.to_thread(_local_repo_digests, target_img)
    except Exception as exc:
        pulled = []
        logger.warning(f"[System Update] Could not inspect the pulled image: {exc}")
    if not pulled:
        raise HTTPException(status_code=502, detail=f"The downloaded image is not from {_IMAGE_REPO}; not updating.")

    # 2. Check if running inside container with docker socket access
    sock_path = "/var/run/docker.sock"
    if os.path.exists(sock_path):
        target_container = "zettnas-toolkit"
        try:
            from backend.services.compose_synthesizer import fetch_container_raw_inspect

            self_info = fetch_container_raw_inspect(socket.gethostname()) or fetch_container_raw_inspect(
                "zettnas-toolkit"
            )
            if self_info and self_info.get("Name"):
                target_container = self_info["Name"].lstrip("/")
        except Exception:
            logger.debug("backend.api.system.post_apply_system_update: ignored error", exc_info=True)

        spawned = await asyncio.to_thread(spawn_self_updater, target_img, target_container, 2.5)
        if spawned:
            return {
                "status": "restarting",
                "channel": channel,
                "target_image": target_img,
                "auto_restarting": True,
                "message": "Update downloaded. ZettNAS is recreating the container now and will reconnect shortly.",
            }

    return {
        "status": "pulled",
        "channel": channel,
        "target_image": target_img,
        "auto_restarting": False,
        "message": "Latest image downloaded to host. Please restart container via Unraid or Docker Compose to finalize.",
    }


def _previous_versions() -> list[dict[str, Any]]:
    from backend.services.container_mutator import _docker_request
    from backend.services.data_snapshot import list_snapshots

    out = []
    for snap in list_snapshots(config.DATA_DIR):
        image = snap.get("from_image") or ""
        if not image or snap.get("kind") == "revert":
            continue
        available = False
        try:
            st, _ = _docker_request("GET", f"/images/{image}/json")
            available = st == 200
        except Exception:
            available = False
        out.append(
            {
                "id": snap["id"],
                "created_at": snap.get("created_at"),
                "version": snap.get("from_version") or "",
                "image": image,
                "tag": snap.get("from_tag") or "",
                "image_available": available,
            }
        )
    return out


@router.get("/system/updates/previous", dependencies=[Depends(require_scope("system:power", "system:manage"))])
async def get_previous_versions():
    """Versions this install can go back to: a pre-update snapshot whose image is still on the host."""
    return {"current_version": __version__, "previous": await asyncio.to_thread(_previous_versions)}


class RevertSystemUpdateRequest(BaseModel):
    snapshot_id: str
    current_password: str


@router.post(
    "/system/updates/revert",
    dependencies=[
        Depends(require_scope("system:power", "system:manage")),
        Depends(require_confirmation("updates.revert")),
    ],
)
async def post_revert_system_update(
    req: RevertSystemUpdateRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Goes back to the version before the last update and restores the data as it was then (OPS-01)."""
    from backend.passwords import verify_password
    from backend.services.self_updater import spawn_self_updater
    from backend.users_db import get_user_by_id

    user = get_user_by_id(principal.user_id) if principal and principal.user_id else None
    if not user or not await asyncio.to_thread(verify_password, req.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=403, detail="Current password is incorrect.")

    match = next((p for p in await asyncio.to_thread(_previous_versions) if p["id"] == req.snapshot_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="That previous version is not available.")
    if not match["image_available"]:
        raise HTTPException(status_code=409, detail="The previous image is no longer on this host.")

    target_container = "zettnas-toolkit"
    try:
        from backend.services.compose_synthesizer import fetch_container_raw_inspect

        self_info = fetch_container_raw_inspect(socket.gethostname()) or fetch_container_raw_inspect("zettnas-toolkit")
        if self_info and self_info.get("Name"):
            target_container = self_info["Name"].lstrip("/")
    except Exception:
        logger.debug("backend.api.system.post_revert_system_update: ignored error", exc_info=True)

    logger.warning(f"[System Update] Reverting to {match['version'] or match['image']} (snapshot {match['id']})")
    spawned = await asyncio.to_thread(spawn_self_updater, match["image"], target_container, 2.5, match["id"])
    if not spawned:
        raise HTTPException(status_code=500, detail="Could not start the revert.")
    add_event("warning", "Updates", f"Reverting to {match['version'] or 'the previous version'}")
    return {
        "status": "restarting",
        "version": match["version"],
        "auto_restarting": True,
        "message": "Reverting. ZettNAS is restoring the previous version and its data and will reconnect shortly.",
    }


@router.get("/system/network-topology", dependencies=[Depends(require_scope("system:view", "system:config"))])
async def system_network_topology():
    """
    Expose complete host networking topology, physical NIC carrier states,
    link negotiation speeds (10GbE / 2.5GbE / 1GbE / 100M), duplex, MTU,
    bonding, bridges, and Docker bridge IP mappings.
    """
    from backend.hardware.network import get_network_topology

    return await asyncio.to_thread(get_network_topology)


@router.get(
    "/system/security-posture",
    dependencies=[Depends(require_scope("system:view", "system:config", "users:read"))],
)
async def system_security_posture(request: Request):
    """
    Evaluates real-time security posture across authentication, MFA, HTTPS,
    guest network shares, and API credential hygiene.
    Returns security score (0-100), letter grade (A-F), and actionable remediation issues.
    """
    from backend.services.security_advisor import evaluate_security_posture

    return await asyncio.to_thread(evaluate_security_posture, request)
