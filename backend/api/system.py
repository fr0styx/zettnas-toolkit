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
from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
    docker_sock,
    logger,
)
from backend.confirmations import confirm_or_raise, require_confirmation
from backend.db import query_copy_history
from backend.fsutil import atomic_write_json, json_locked, read_json, resolve_within, root_for
from backend.hardware.disks import is_drive_asleep, locate_disk, read_smart_detail, run_disk_smart_test
from backend.hardware.docker_stats import container_action, read_docker_containers
from backend.hardware.fans import set_fan_pwm
from backend.hardware.led import apply_led_state
from backend.hardware.memory import read_mem
from backend.hardware.pal_storage import get_storage_platform
from backend.hardware.screen import get_screen_state, save_screen_state
from backend.hardware.storage import detect_chassis_model, get_chassis_friendly_name, get_current_layout
from backend.hardware.unraid import read_unraid_status
from backend.hardware.ups import read_ups_status
from backend.ignored_errors import ignored
from backend.logging_config import get_recent_logs, in_this_request, sanitize_dict, sanitize_string
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
from backend.paging import PageParams
from backend.services.broadcaster import broadcaster
from backend.services.copy_engine import _do_copy
from backend.services.notifications import DEFAULT_NOTIFICATION_CONFIG, NOTIFICATIONS_FILE
from backend.settings import test_mode
from backend.state import Z_STATE, add_event

router = APIRouter(tags=["System & Storage"])


_PROCESS_STARTED = time.time()


def _image_variant() -> str:
    from backend.config import IMAGE_VARIANT

    return IMAGE_VARIANT


def _daemon_status() -> dict:
    from backend.services.supervisor import daemon_status

    return daemon_status()


HEALTH_STARTUP_GRACE_SECS = 60.0
# the users database is opened at most every 5 minutes for the health probe while it is fine;
# a failure is looked at again on every probe (PERF-30)
DB_CHECK_EVERY_SECS = 300.0
_DB_CHECK: dict = {"state": "", "at": 0.0}


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
    now = time.time()
    if now - _DB_CHECK["at"] >= DB_CHECK_EVERY_SECS or _DB_CHECK["state"] != "ok":
        try:
            from backend.users_db import users_db_session

            with users_db_session(None) as conn:
                conn.execute("SELECT count(*) FROM users").fetchone()  # a real table, not just a file
            _DB_CHECK.update(state="ok", at=now)
        except Exception:
            _DB_CHECK.update(state="failed", at=now)
    checks["database"] = _DB_CHECK["state"]
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
        # the commit the image was built from: open pages compare it to notice an update
        "build": os.environ.get("BUILD_COMMIT", "")[:12],
        "image_variant": _image_variant(),
        "checks": checks,
        "daemons": {k: {"state": v["state"], "restarts": v["restarts"]} for k, v in _daemon_status().items()},
        "stalled": sorted(k for k, v in _daemon_status().items() if v["state"] == "stalled"),
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


async def _confirm_wake(request: Request, principal: AuthenticatedPrincipal, dev: str) -> None:
    """A sleeping drive is only woken after the person confirms it (428 "disk.wake" until then)."""
    if await asyncio.to_thread(is_drive_asleep, dev):
        confirm_or_raise(request, principal, "disk.wake", dev)


@router.get("/disk_detail", dependencies=[Depends(require_scope("storage:read", "system:view"))])
async def disk_detail(
    request: Request,
    dev: str = "sda",
    wake: bool = False,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    if dev.startswith("/dev/"):
        dev = dev.replace("/dev/", "")
    m = re.match(r"^nv([0-9]+)$", dev)
    if m:
        dev = f"nvme{m.group(1)}n1"
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    if wake:
        await _confirm_wake(request, principal, dev)
    # A reading under 30 s old is reused (Drive Health has usually just taken it); waking reads anew.
    return await asyncio.to_thread(read_smart_detail, dev, wake, 0.0 if wake else 30.0)


@router.post("/disk_wake", dependencies=[Depends(require_scope("storage:write", "storage:admin"))])
async def disk_wake(
    payload: dict, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    dev = str(payload.get("dev", "sda"))
    if dev.startswith("/dev/"):
        dev = dev.replace("/dev/", "")
    m = re.match(r"^nv([0-9]+)$", dev)
    if m:
        dev = f"nvme{m.group(1)}n1"
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    await _confirm_wake(request, principal, dev)
    detail = await asyncio.to_thread(read_smart_detail, dev, True)
    return {"success": True, "dev": dev, "detail": detail}


@router.post("/disk/smart_test", dependencies=[Depends(require_scope("storage:admin"))])
async def disk_smart_test(
    req: DiskSmartTestRequest, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    dev = str(req.dev)
    test_type = str(req.test_type)
    if dev.startswith("/dev/"):
        dev = dev.replace("/dev/", "")
    m = re.match(r"^nv([0-9]+)$", dev)
    if m:
        dev = f"nvme{m.group(1)}n1"
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    await _confirm_wake(request, principal, dev)  # a self-test spins a sleeping drive up
    return await asyncio.to_thread(run_disk_smart_test, dev, test_type)


@router.get("/disk/smart_tests", dependencies=[Depends(require_scope("storage:read", "hardware:read", "system:view"))])
async def get_disk_smart_tests(dev: str | None = None, limit: int = Query(20, ge=1, le=500)):
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
async def disk_locate_endpoint(
    payload: dict, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
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
    if not await asyncio.to_thread(is_drive_asleep, dev):
        return await asyncio.to_thread(locate_disk, dev, duration)
    # Asleep: the bay lights do not wake it; reading the disk to blink its activity light does.
    result = await asyncio.to_thread(locate_disk, dev, duration, False)
    if not result.get("needs_wake"):
        return result
    confirm_or_raise(request, principal, "disk.wake", dev)
    return await asyncio.to_thread(locate_disk, dev, duration, True)


@router.get("/screen", dependencies=[Depends(require_scope("hardware:read", "system:view"))])
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
    threading.Thread(target=in_this_request(lambda c: asyncio.run(_do_copy(c))), args=(cfg,), daemon=True).start()
    return {"status": "started"}


class UsbDiskRequest(BaseModel):
    path: str = Field(..., min_length=2, max_length=1024)
    dest: str | None = Field(default=None, max_length=1024)


class UsbSettingsRequest(BaseModel):
    offer: bool | None = None
    auto_backup: bool | None = None


@router.get("/usb/disks", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def usb_disks():
    """USB disks mounted under /mnt/disks: space, the backups that go to each, camera media (FEAT-07)."""
    from backend.services import usb_copy

    return {"disks": usb_copy.disks(), "settings": usb_copy.settings()}


@router.put("/usb/settings", dependencies=[Depends(require_scope("system:config"))])
def usb_settings(req: UsbSettingsRequest):
    from backend.services import usb_copy

    return usb_copy.save_settings(**req.model_dump())


@router.post("/usb/import", dependencies=[Depends(require_scope("storage:write", "storage:admin"))])
def usb_import(req: UsbDiskRequest):
    """Copies a USB disk's photos and videos (its DCIM folder, else the whole disk) into dated
    folders, verified file by file like the card reader (FEAT-07)."""
    from backend.services import usb_copy

    try:
        usb_copy.find(req.path)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'")) from None
    if Z_STATE.copy_active:
        raise HTTPException(status_code=409, detail="Copy operation already in progress")
    cfg = {**_load_buttons(), "source": "usb", "source_path": req.path}
    if req.dest:
        cfg["dest"] = req.dest
    Z_STATE.pending_usb = None
    Z_STATE.copy_active = True
    Z_STATE.copy_status = "copying"
    Z_STATE.ui_wake.set()
    add_event("info", "Copy Started", f"Importing from USB disk {os.path.basename(req.path)}...")
    threading.Thread(target=in_this_request(lambda c: asyncio.run(_do_copy(c))), args=(cfg,), daemon=True).start()
    return {"status": "started"}


@router.post("/usb/backup", dependencies=[Depends(require_scope("backup:manage", "system:config"))])
def usb_backup(req: UsbDiskRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Backs the NAS up to this USB disk now: every off-site backup that lives on it (FEAT-07)."""
    from backend.services import usb_copy

    try:
        started = usb_copy.start_backups(req.path, owner=principal.username)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'")) from None
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    usb_copy.dismiss()
    return {"status": "started", "backups": started}


@router.post("/usb/dismiss", dependencies=[Depends(require_scope("storage:write", "storage:admin", "backup:manage"))])
def usb_dismiss():
    from backend.services import usb_copy

    usb_copy.dismiss()
    return {"status": "dismissed"}


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


@router.get("/buttons", dependencies=[Depends(require_scope("hardware:read", "system:view"))])
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
    from backend.state import clear_events as _clear

    _clear()
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


@router.get("/lcd/page", dependencies=[Depends(require_scope("hardware:read", "system:view"))])
def get_lcd_page():
    return {
        "page": Z_STATE.current_lcd_page,
        "cycle_seconds": Z_STATE.lcd_cycle_seconds,
    }


@router.get("/lcd/preview.png", dependencies=[Depends(require_scope("hardware:read", "system:view"))])
def get_lcd_preview(page: int | None = Query(None, ge=0, le=3), theme: str | None = Query(None, max_length=20)):
    """The LCD as the built-in (no-browser) renderer draws it, as a 640x172 PNG."""
    from backend.services import lcd_pil

    with Z_STATE.lock:
        stats = dict(Z_STATE.cached_stats or {})
    prefs = dict(stats.get("client_preferences") or {})
    if theme:
        prefs["lcd_theme"] = theme
    png = lcd_pil.preview_png(stats, page, prefs=prefs)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


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


@router.get("/copy/history", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_copy_history(page: PageParams = Depends()):
    # a plain list, as before; limit and offset are validated and applied
    return page.slice(query_copy_history(page.fetch))


@router.get("/unraid", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_unraid_telemetry():
    return read_unraid_status(force=True)


@router.post("/system/profile", dependencies=[Depends(require_scope("system:config"))])
@json_locked(lambda *a, **k: FAN_STATE_FILE)
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
    # COMP-06: only these folders (and what is inside them); empty means every folder the account may open
    folders: list[str] | None = None


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
                        "last_used_ip": t.get("last_used_ip") or "",
                        "last_client": t.get("last_client") or "",
                        "folders": t.get("folders") or [],
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


def _token_folders_for(folders: list[str] | None, principal: Any) -> list[str]:
    """The folder allow-list for a new token (COMP-06): only folders its creator may read, checked
    from the paths alone so no sleeping drive is woken."""
    from backend.services.path_access import indexed_path_checker
    from backend.users_db import normalize_token_folders

    clean = normalize_token_folders(folders)  # ValueError -> 400
    readable = indexed_path_checker(principal)
    refused = [f for f in clean if not readable(f)]
    if refused:
        raise HTTPException(status_code=403, detail=f"You can't open {refused[0]}, so a token can't either.")
    return clean


@router.post("/tokens", dependencies=[Depends(require_scope("users:write", "system:config"))])
def create_token(req: TokenCreateRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    if principal and not principal.has_scope("*"):
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

        # No scopes chosen: the token gets what its creator holds, never more (SEC-4)
        scopes = req.scopes or list(getattr(principal, "scopes", None) or [])
        folders = _token_folders_for(req.folders, principal)
        raw_token, meta = create_scoped_api_token(
            user_id=user_id,
            name=req.name,
            scopes=scopes,
            expires_in_days=req.expires_in_days,
            folders=folders,
        )
        add_event("success", "Security", f"Generated new scoped API token: {req.name}")
        try:
            from backend.users_db import log_security_event

            log_security_event(
                "api_token.created",
                "success",
                actor_id=getattr(principal, "user_id", None),
                actor_username=getattr(principal, "username", None),
                details={"name": req.name, "scopes": meta.get("scopes"), "folders": meta.get("folders")},
            )
        except Exception:
            ignored("backend.api.system.create_token")
        return {
            "token": raw_token,
            "name": req.name,
            "token_id": meta["token_id"],
            "scopes": meta["scopes"],
            "folders": meta.get("folders") or [],
            "masked_token": meta["masked_token"],
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.error(f"Could not create API token: {e}")
        raise HTTPException(status_code=500, detail="Could not create the API token.") from e


@router.delete("/tokens/{token_id}", dependencies=[Depends(require_scope("users:write", "system:config"))])
def delete_token(token_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    user_id = None
    if principal and not principal.has_scope("*"):
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


REBOOT_TRIGGERS = (
    ("/host/reboot",),
    ("/usr/local/sbin/reboot",),
    ("reboot",),
    ("shutdown", "-r", "now"),
)
POWEROFF_TRIGGERS = (
    ("/host/powerdown",),
    ("/usr/local/sbin/powerdown",),
    ("/sbin/poweroff",),
    ("poweroff",),
    ("shutdown", "-h", "now"),
)
SYSRQ_TRIGGER = "/proc/sysrq-trigger"


def _sysrq_power(action: str) -> bool:
    """Last resort: the kernel's emergency keys. They act at once, so the disks are flushed
    (s) and switched to read-only (u) first; otherwise unwritten data would be lost."""
    if not os.path.exists(SYSRQ_TRIGGER):
        return False
    try:
        os.sync()
        for key in ("s", "u"):
            with open(SYSRQ_TRIGGER, "w") as f:
                f.write(key)
            time.sleep(1.0)
        with open(SYSRQ_TRIGGER, "w") as f:
            f.write("b" if action == "reboot" else "o")
        return True
    except Exception as e:
        logger.debug(f"[Power] Sysrq fallback failed: {e}")
        return False


def trigger_power_action(action: str) -> bool:
    """
    Triggers host system reboot or shutdown.
    Checks host trigger scripts, container-host volume mounts, and system power commands.
    """
    if test_mode():
        logger.info(f"[Power] Test mode active; harmlessly mocked host trigger for '{action}'")
        return True

    for cmd in REBOOT_TRIGGERS if action == "reboot" else POWEROFF_TRIGGERS:
        bin_path = cmd[0]
        if (os.path.exists(bin_path) and os.access(bin_path, os.X_OK)) or shutil.which(bin_path):
            try:
                subprocess.Popen(list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info(f"[Power] Executed host trigger: {list(cmd)}")
                return True
            except Exception as e:
                logger.error(f"[Power] Failed executing host trigger {list(cmd)}: {e}")

    return _sysrq_power(action)


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
    "beta": {"ts": 0.0, "data": None},
    "edge": {"ts": 0.0, "data": None},
}
CHANNEL_IMAGE_TAG = {"stable": "latest", "beta": "beta", "edge": "edge"}


def _channel(name: str | None) -> str:
    """stable (promoted releases, :latest), beta (new releases during their 7-day soak, :beta)
    or edge (every commit on main, :edge). Anything else is stable."""
    n = str(name or "").lower()
    return n if n in CHANNEL_IMAGE_TAG else "stable"


@functools.lru_cache(maxsize=1)
def _get_current_build_info_cached() -> dict[str, Any]:
    return _get_current_build_info_impl()


def _get_current_build_info() -> dict[str, Any]:
    if test_mode():
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
                        ignored("backend.api.system._get_current_build_info_impl")

                # 2. Container labels fallback
                if not commit:
                    labels = data.get("Config", {}).get("Labels", {})
                    commit = labels.get("org.opencontainers.image.revision", "")
                    if not created:
                        created = labels.get("org.opencontainers.image.created", "")
        except Exception:
            ignored("backend.api.system._get_current_build_info_impl")

    if not commit:
        for p in ("/app/.git_commit", "data/.git_commit", ".git_commit"):
            if os.path.exists(p):
                try:
                    with open(p) as f:
                        commit = f.read().strip()
                except Exception:
                    ignored("backend.api.system._get_current_build_info_impl")

    if not commit:
        try:
            import subprocess

            res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=2.0)
            if res.returncode == 0 and res.stdout.strip():
                commit = res.stdout.strip()
        except Exception:
            ignored("backend.api.system._get_current_build_info_impl")

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


class IdentityIn(BaseModel):
    server_name: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)


@router.get("/system/identity")
def get_server_identity(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """The server's name and time zone (UX-17)."""
    from backend.services.identity import get_identity

    return get_identity()


@router.put("/system/identity", dependencies=[Depends(require_scope("system:config"))])
def put_server_identity(req: IdentityIn):
    from backend.services.identity import set_identity

    try:
        return set_identity(req.server_name, req.timezone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


class HealthSignalIn(BaseModel):
    enabled: bool


@router.get("/system/health-signal", dependencies=[Depends(require_scope("system:view"))])
def get_health_signal():
    """The opt-in anonymous weekly report: whether it is on, and exactly what it sends."""
    from backend.services.health_signal import status

    return status()


@router.put("/system/health-signal", dependencies=[Depends(require_scope("system:config"))])
def put_health_signal(req: HealthSignalIn):
    from backend.services.health_signal import endpoint, set_enabled, status

    if req.enabled and not endpoint():
        raise HTTPException(status_code=409, detail="The health report is not available in this version.")
    set_enabled(req.enabled)
    return status()


@router.get("/system/protection", dependencies=[Depends(require_scope("system:view"))])
def get_protection_status():
    """The copies outside this NAS, for the Overview (FEAT-01)."""
    from backend.services.protection_status import status

    return status()


@router.get("/system/status-summary", dependencies=[Depends(require_scope("system:view"))])
def get_status_summary():
    """What needs attention, for the Overview (UX-1)."""
    from backend.services.status_summary import summary

    return summary()


@router.get("/system/about")
def get_system_about():
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


async def _check_update_signature(target_img: str, expected_digest: str | None, pulled: list[str]) -> dict:
    """Verifies the CI signature of the image about to be installed (UPDATE_SIGNATURES)."""
    mode = config.UPDATE_SIGNATURES
    if mode == "off":
        return {"checked": False}
    from backend.services.image_signature import SignatureResult, verify_image

    if "@" in target_img:
        digest = target_img.split("@", 1)[1]
    else:
        digest = expected_digest or (pulled[0] if pulled else "")
    result = await asyncio.to_thread(verify_image, digest) if digest else SignatureResult(False, "no digest")
    if result.ok:
        logger.info(f"[System Update] Signature verified for {digest} ({result.identity}).")
        return {"checked": True, **result.as_dict()}
    if mode == "warn":
        logger.warning(f"[System Update] Installing {digest} although its signature failed: {result.reason}")
        add_event("warning", "Update signature not verified", result.reason)
        return {"checked": True, **result.as_dict()}
    logger.error(f"[System Update] Refusing {digest}: {result.reason}")
    raise HTTPException(
        status_code=502,
        detail=f"Not updating: the image's signature could not be verified ({result.reason}). "
        "Try again later; UPDATE_SIGNATURES=warn installs it anyway.",
    )


@router.get("/system/updates", dependencies=[Depends(require_scope("system:view"))])
async def check_system_updates(force: bool = False, channel: str = "stable"):
    """Release/commit check, then a registry digest check (OPS-18).

    Version strings and commit hashes say a newer release exists; only the image
    digest says whether the image this channel serves differs from the one running.
    When both digests are known they decide update_available.
    """
    result = await _check_system_updates_by_version(force=force, channel=channel)
    if result.get("digest_checked"):
        return result
    from backend.config import variant_tag

    tag = variant_tag(CHANNEL_IMAGE_TAG[_channel(result.get("channel"))])
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
    """Check GitHub Releases (stable: the latest promoted release; beta: the newest release,
    soaking or not) or the commits on main (edge), with in-memory caching."""
    import httpx

    channel_key = _channel(channel)
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

    # Stable: GitHub's "latest release" skips pre-releases, so a release only shows up here
    # once it has been promoted after its 7-day soak (OPS-07). Beta: the newest release.
    if channel_key == "beta":
        url = "https://api.github.com/repos/fr0styx/zettnas-toolkit/releases?per_page=10"
    else:
        url = "https://api.github.com/repos/fr0styx/zettnas-toolkit/releases/latest"

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if channel_key == "beta":
                    data = (
                        next((r for r in data if isinstance(r, dict) and not r.get("draft")), None)
                        if isinstance(data, list)
                        else None
                    )
            if resp.status_code == 200 and data:
                tag = data.get("tag_name", "").strip()
                clean_tag = tag.lstrip("v")
                update_available = _is_newer_version(clean_tag, __version__)

                result = {
                    "channel": channel_key,
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
                _last_update_check[channel_key] = {"ts": now, "data": result}
                return result
            elif channel_key == "beta":
                # No release published at all: the newest version tag. Never for stable,
                # where it would skip the soak.
                tags_resp = await client.get(
                    "https://api.github.com/repos/fr0styx/zettnas-toolkit/tags", headers=headers
                )
                if tags_resp.status_code == 200 and tags_resp.json():
                    latest_tag = tags_resp.json()[0].get("name", "")
                    clean_tag = latest_tag.lstrip("v")
                    update_available = _is_newer_version(clean_tag, __version__)
                    result = {
                        "channel": channel_key,
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
                    _last_update_check[channel_key] = {"ts": now, "data": result}
                    return result

            error_msg = f"GitHub API HTTP {resp.status_code}"
    except Exception as e:
        error_msg = str(e)

    fallback = {
        "channel": channel_key,
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
    revert: bool = False  # SEC-37: installing an older version must be asked for by name


_VERSION_TAG = re.compile(r"^v?\d+(?:\.\d+){1,3}$")


def older_than_running(version: str) -> bool:
    """True for a version string (v1.9.4, 1.9.4) older than the one running now."""
    v = (version or "").strip()
    return bool(_VERSION_TAG.match(v)) and _is_newer_version(__version__, v.lstrip("v"))


def _image_version_label(image_ref: str) -> str:
    from backend.services.container_mutator import _docker_request

    st, img = _docker_request("GET", f"/images/{image_ref}/json")
    if st != 200 or not isinstance(img, dict):
        return ""
    return str(((img.get("Config") or {}).get("Labels") or {}).get("org.opencontainers.image.version") or "")


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

    channel = _channel(req.channel)
    if req.target_image:
        # Only this project's images: an update must never install an arbitrary image
        # with full access to the Docker socket and host devices.
        if not _is_official_image_ref(req.target_image):
            raise HTTPException(status_code=400, detail=f"Updates can only install {_IMAGE_REPO} images.")
        target_img = req.target_image
        tag = target_img.rsplit(":", 1)[1] if ":" in target_img.split("/")[-1] else ""
        if older_than_running(tag) and not req.revert:
            raise HTTPException(
                status_code=409,
                detail=f"{tag} is older than this version ({__version__}). To go back, ask for a revert.",
            )
    else:
        from backend.config import variant_tag

        target_img = f"ghcr.io/fr0styx/zettnas-toolkit:{variant_tag(CHANNEL_IMAGE_TAG[channel])}"

    # Invalidate cached update check so immediate post-update checks reflect the new state
    _last_update_check[channel]["data"] = None
    _last_update_check[channel]["ts"] = 0.0

    logger.info(f"[System Update] User initiated system update on '{channel}' channel using image '{target_img}'...")

    # 0. The digest the registry serves for this tag right now: the pulled image must be exactly
    #    that one, so the tag can't move between the check and the download (OPS-1)
    expected_digest = None
    tag = target_img.rsplit(":", 1)[1] if ":" in target_img.split("/")[-1] else "latest"
    if "@" not in target_img:
        try:
            expected_digest = await _registry_digest(tag)
        except Exception as exc:
            logger.warning(f"[System Update] Could not look up the digest for '{tag}': {exc}")

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
    if expected_digest and expected_digest not in pulled:
        raise HTTPException(
            status_code=409,
            detail="The image changed while it was downloading (a new build was published). Check for updates again.",
        )

    # 1b'. Nor an older version under a newer name, unless a revert was asked for (SEC-37)
    try:
        label = await asyncio.to_thread(_image_version_label, target_img)
    except Exception:
        label = ""
    if older_than_running(label) and not req.revert:
        raise HTTPException(
            status_code=409,
            detail=f"The downloaded image is version {label}, older than this one ({__version__}). Not updating.",
        )

    # 1c. The image must be signed by this project's CI (cosign keyless, Sigstore bundle)
    signature = await _check_update_signature(target_img, expected_digest, pulled)

    # 2. Check if running inside container with docker socket access
    sock_path = docker_sock()
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
            ignored("backend.api.system.post_apply_system_update")

        spawned = await asyncio.to_thread(spawn_self_updater, target_img, target_container, 2.5)
        if spawned:
            return {
                "status": "restarting",
                "channel": channel,
                "target_image": target_img,
                "auto_restarting": True,
                "signature": signature,
                "message": "Update downloaded. ZettNAS is recreating the container now and will reconnect shortly.",
            }

    return {
        "status": "pulled",
        "channel": channel,
        "target_image": target_img,
        "auto_restarting": False,
        "signature": signature,
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


@router.get("/system/updates/last-result", dependencies=[Depends(require_scope("system:view", "system:manage"))])
def get_last_update_result():
    """How the last in-app update or revert ended (OPS-7)."""
    from backend.services.self_updater import last_update_result

    data = last_update_result(config.DATA_DIR) or {}
    return {k: data.get(k) for k in ("result", "reason", "at", "to_image")} if data else {"result": None}


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
        ignored("backend.api.system.post_revert_system_update")

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


@router.post(
    "/system/security-posture/fix/{fix_id}",
    dependencies=[Depends(require_scope("system:config")), Depends(require_confirmation("security.advisor_fix"))],
)
async def system_security_fix(fix_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Applies one Security Advisor fix (B11): tightens a setting an upgraded install kept."""
    from backend.services.safe_defaults_advisor import FIXES, apply_fix

    if fix_id not in FIXES:
        raise HTTPException(status_code=404, detail="Unknown fix")
    try:
        message = await asyncio.to_thread(apply_fix, fix_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    who = getattr(principal, "username", None) or "admin"
    try:
        from backend.state import add_event

        add_event("info", "Security Advisor fix applied", f"{who}: {message}", details={"fix": fix_id})
    except Exception as e:
        logger.debug(f"[SecurityAdvisor] Could not record event: {e}")
    return {"ok": True, "fix": fix_id, "message": message}
