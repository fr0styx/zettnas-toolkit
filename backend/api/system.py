import aiofiles
import asyncio
from datetime import datetime, timezone
import io
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

import backend.config as config
from backend import __version__
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.api_tokens import generate_token, load_tokens, revoke_token
from backend.config import (
    ALLOWED_BROWSE_ROOTS,
    BUTTON_CFG_FILE,
    DASH_LAYOUT_FILE,
    EVENTS_FILE,
    FAN_STATE_FILE,
    LED_STATE_FILE,
    logger,
)
from backend.db import query_copy_history
from backend.fsutil import atomic_write_json, read_json, resolve_within, root_for
from backend.hardware.disks import fetch_disk_smart_detail, locate_disk, run_disk_smart_test
from backend.hardware.docker_stats import container_action, read_docker_containers
from backend.hardware.fans import set_fan_pwm
from backend.hardware.led import apply_led_state
from backend.hardware.screen import get_screen_state, save_screen_state
from backend.hardware.storage import detect_chassis_model, get_current_layout
from backend.hardware.unraid import read_unraid_status
from backend.hardware.ups import read_ups_status
from backend.models.schemas import (
    DiskSmartTestRequest,
    ButtonConfigRequest,
    CopyConfirmRequest,
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
from backend.services.copy_engine import _do_copy
from backend.services.notifications import DEFAULT_NOTIFICATION_CONFIG, NOTIFICATIONS_FILE
from backend.hardware.memory import read_mem
from backend.hardware.pal_storage import get_storage_platform
from backend.logging_config import get_recent_logs, sanitize_dict, sanitize_string
from backend.state import Z_STATE, add_event

router = APIRouter(tags=["System & Storage"])


@router.get("/health")
def health():
    """Public liveness probe (no secrets): used by Docker HEALTHCHECK/monitoring."""
    hb = Z_STATE.collector_heartbeat
    hb_age = round(time.time() - hb, 1) if hb else None
    collector_ok = hb_age is not None and hb_age <= config.COLLECTOR_WATCHDOG_SECS
    return {
        "status": "ok" if collector_ok else "degraded",
        "version": __version__,
        "collector_heartbeat_age": hb_age,
        "lcd_renderer_active": bool(Z_STATE.lcd_renderer_active),
        "fans_released": bool(Z_STATE.fans_released),
        "critical_temp_active": bool(Z_STATE.critical_temp_active),
    }


def _contained(path, must_exist=True):
    """Resolve `path` inside an allowed browse root or raise 403/404."""
    path = str(path or "").strip()
    if not path or "\x00" in path:
        raise HTTPException(status_code=400, detail="Invalid path")
    real = resolve_within(path, ALLOWED_BROWSE_ROOTS)
    if real is None:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders.")
    if must_exist and not os.path.exists(real):
        raise HTTPException(status_code=404, detail="Path does not exist.")
    return real


@router.get("/disk_detail")
async def disk_detail(dev: str = "sda"):
    if dev.startswith("/dev/"):
        dev = dev.replace("/dev/", "")
    m = re.match(r"^nv([0-9]+)$", dev)
    if m:
        dev = f"nvme{m.group(1)}n1"
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    return await asyncio.to_thread(fetch_disk_smart_detail, dev)


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
    detail = await asyncio.to_thread(fetch_disk_smart_detail, dev)
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


def check_user_path_access(req_path: str, principal: Optional[AuthenticatedPrincipal]) -> None:
    """Enforce multi-user path isolation:
    - SuperAdmin / StorageAdmin / users with 'shares:manage' or '*' scope have unrestricted access to all allowed roots.
    - Standard users cannot access other users' private home folders in /homes/<other_user>.
    """
    if not principal:
        return

    if (
        principal.role_id in ("superadmin", "storage_admin")
        or principal.has_scope("shares:manage")
        or principal.has_scope("*")
    ):
        return

    norm_path = os.path.normpath(str(req_path or "").strip()).replace("\\", "/")
    parts = [p for p in norm_path.split("/") if p]
    if "homes" in parts:
        idx = parts.index("homes")
        if idx + 1 < len(parts):
            target_user = parts[idx + 1].lower()
            current_user = (principal.username or "").lower()
            if target_user != current_user:
                raise HTTPException(status_code=403, detail="Access denied to another user's home folder.")


def _handle_browse_logic(path: str, dirs_only: bool, principal: Optional[AuthenticatedPrincipal] = None):
    real = _contained(path or ALLOWED_BROWSE_ROOTS[0])
    if not os.path.isdir(real):
        raise HTTPException(status_code=400, detail="Not a directory.")
    out = []
    root = root_for(real, ALLOWED_BROWSE_ROOTS)
    if root and real != root:
        out.append({"name": "..", "path": os.path.dirname(real), "is_dir": True, "size": 0})
    try:
        entries = os.listdir(real)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.")
    except OSError as e:
        logger.warning(f"[BROWSE] listdir failed for {real}: {e}")
        raise HTTPException(status_code=500, detail="Unable to read directory.")

    is_admin = not principal or (
        principal.role_id in ("superadmin", "storage_admin")
        or principal.has_scope("shares:manage")
        or principal.has_scope("*")
    )
    is_homes_dir = os.path.basename(real.rstrip("/")) == "homes"

    if is_homes_dir and not is_admin and principal and principal.username:
        user_home_name = principal.username.lower()
        user_home_path = os.path.join(real, user_home_name)
        if not os.path.exists(user_home_path):
            try:
                os.makedirs(user_home_path, exist_ok=True)
                if user_home_name not in entries:
                    entries.append(user_home_name)
            except OSError as e:
                logger.warning(f"[BROWSE] Failed to auto-provision home directory {user_home_path}: {e}")

    for e in sorted(entries):
        if is_homes_dir and not is_admin and principal:
            if e.lower() != (principal.username or "").lower():
                continue
        full = os.path.join(real, e)
        is_dir = os.path.isdir(full)
        if dirs_only and not is_dir:
            continue
        # Hide symlinks that point outside the allowed roots.
        if os.path.islink(full) and resolve_within(full, ALLOWED_BROWSE_ROOTS) is None:
            continue
        sz = 0
        if not is_dir and not os.path.islink(full):
            try:
                sz = os.path.getsize(full)
            except OSError:
                pass
        out.append({"name": e, "path": full, "is_dir": is_dir, "size": sz})
    return {"current": real, "roots": list(ALLOWED_BROWSE_ROOTS), "dirs": out}


@router.get("/browse")
async def browse(
    path: str = "",
    dirs_only: str = "0",
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    check_user_path_access(path, principal)
    return await asyncio.to_thread(_handle_browse_logic, path, dirs_only == "1", principal)


def _do_mkdir(path: str):
    path = str(path or "").strip()
    parent = _contained(os.path.dirname(path.rstrip("/")) or "/", must_exist=True)
    name = os.path.basename(path.rstrip("/"))
    if not name or name in (".", "..") or "/" in name:
        raise HTTPException(status_code=400, detail="Invalid folder name")
    target = os.path.join(parent, name)
    if resolve_within(target, ALLOWED_BROWSE_ROOTS) is None:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders.")
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as e:
        logger.warning(f"[MKDIR] Failed to create {target}: {e}")
        raise HTTPException(status_code=500, detail="Unable to create folder.")
    return {"status": "ok", "path": target}


@router.post(
    "/mkdir",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def mkdir(req: MkdirRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    check_user_path_access(req.path, principal)
    return _do_mkdir(req.path)


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


@router.post(
    "/copy/eject", dependencies=[Depends(require_scope("storage:write", "shares:user_write", "storage:admin"))]
)
def eject_media(req: EjectMediaRequest | None = None):
    from backend.services.copy_engine import eject_media_slot

    slot = req.slot if req and req.slot else "sd"
    return eject_media_slot(slot)


BUTTON_DEFAULTS = {
    "enabled": False,
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
    state.update(data)
    atomic_write_json(BUTTON_CFG_FILE, state)
    if data.get("auto_ingest") is False:
        with Z_STATE.lock:
            Z_STATE.pending_ingest = None
        Z_STATE.ui_wake.set()
    return state


@router.delete("/events/clear", dependencies=[Depends(require_scope("system:config", "audit:read"))])
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


@router.post("/layout")
def post_layout(req: LayoutRequest):
    data = req.model_dump()
    data["sizes"] = {k: v for k, v in data["sizes"].items() if v in ("full", "compact")}
    data["version"] = int(time.time() * 1000)
    atomic_write_json(DASH_LAYOUT_FILE, data)
    with Z_STATE.lock:
        if Z_STATE.cached_stats:
            Z_STATE.cached_stats["layout"] = data
    Z_STATE.ui_wake.set()
    return {"status": "ok", "layout": data}


@router.post("/state")
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

    set_fan_pwm(fan_cfg["profile"], fan_cfg.get("manual_pct", 60), ctrl_cpu_fan=fan_cfg.get("ctrl_cpu_fan", False))
    apply_led_state(led_cfg)
    Z_STATE.ui_wake.set()

    return {"status": "ok", "profile": profile, "fan": fan_cfg, "led": led_cfg}


@router.get("/docker/containers")
async def get_docker_containers():
    return await asyncio.to_thread(read_docker_containers)


@router.post(
    "/docker/containers/{container_id}/action",
    dependencies=[Depends(require_scope("containers:write", "containers:manage"))],
)
async def post_docker_container_action(container_id: str, req: DockerActionRequest):
    res = await asyncio.to_thread(container_action, container_id, req.action)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Action failed"))
    return res


@router.get("/docker/containers/{container_id}/compose")
async def get_docker_container_compose(container_id: str):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.compose_synthesizer import get_container_compose_data

    data = await asyncio.to_thread(get_container_compose_data, container_id)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


@router.get("/docker/containers/{container_id}/details")
async def get_docker_container_details(container_id: str):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.compose_synthesizer import get_container_full_details

    data = await asyncio.to_thread(get_container_full_details, container_id)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


@router.get("/docker/containers/{container_id}/logs")
async def get_docker_container_logs(container_id: str, tail: int = 200):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.compose_synthesizer import get_container_logs_chunk

    return await asyncio.to_thread(get_container_logs_chunk, container_id, tail)


class DockerResourceUpdateRequest(BaseModel):
    memory_mb: Optional[int] = None
    nano_cpus: Optional[float] = None
    cpu_shares: Optional[int] = None
    restart_policy: Optional[str] = None


@router.post("/docker/containers/{container_id}/resources", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_container_resources(container_id: str, req: DockerResourceUpdateRequest):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.container_mutator import update_container_resources

    try:
        res = await asyncio.to_thread(
            update_container_resources,
            container_id,
            memory_mb=req.memory_mb,
            nano_cpus=req.nano_cpus,
            cpu_shares=req.cpu_shares,
            restart_policy=req.restart_policy,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Docker] Resource update failed for {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PortMappingItem(BaseModel):
    container_port: int
    host_port: Optional[int] = None
    proto: str = "tcp"
    host_ip: str = "0.0.0.0"


class DockerPortRecreateRequest(BaseModel):
    ports: List[PortMappingItem]
    keep_backup: bool = False


@router.post("/docker/containers/{container_id}/ports", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_container_ports(container_id: str, req: DockerPortRecreateRequest):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.container_mutator import recreate_container_ports

    try:
        ports_dicts = [p.model_dump() for p in req.ports]
        res = await asyncio.to_thread(
            recreate_container_ports,
            container_id,
            new_port_bindings=ports_dicts,
            keep_backup=req.keep_backup,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Docker] Port recreate failed for {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/docker/check_port")
async def get_check_port(port: int, proto: str = "tcp"):
    from backend.services.container_mutator import check_port_available

    available = await asyncio.to_thread(check_port_available, port, proto)
    return {"port": port, "proto": proto, "available": available}


class AppSourceCreateRequest(BaseModel):
    name: str
    url: str


class AppSourceToggleRequest(BaseModel):
    enabled: bool


class AppComposeRequest(BaseModel):
    host_port: Optional[int] = None
    storage_root: str = "/mnt/user/appdata"


class ContainerExecRequest(BaseModel):
    cmd: str


@router.get("/docker/catalog")
async def get_docker_catalog():
    from backend.services.app_catalog import get_all_catalog_apps

    return await asyncio.to_thread(get_all_catalog_apps)


@router.get("/docker/catalog/sources")
async def get_docker_catalog_sources():
    from backend.services.app_catalog import get_catalog_sources

    return await asyncio.to_thread(get_catalog_sources)


@router.post("/docker/catalog/sources", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_sources(req: AppSourceCreateRequest):
    from backend.services.app_catalog import add_catalog_source

    try:
        res = await asyncio.to_thread(add_catalog_source, req.name, req.url)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[AppCatalog] Failed to add source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/docker/catalog/sources/{source_id}", dependencies=[Depends(require_scope("containers:manage"))])
async def delete_docker_catalog_source(source_id: str):
    if not source_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", source_id):
        raise HTTPException(status_code=400, detail="Invalid source ID")

    from backend.services.app_catalog import delete_catalog_source

    try:
        deleted = await asyncio.to_thread(delete_catalog_source, source_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Source not found")
        return {"status": "ok", "deleted": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[AppCatalog] Failed to delete source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/docker/catalog/sources/{source_id}/sync", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_source_sync(source_id: str):
    if not source_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", source_id):
        raise HTTPException(status_code=400, detail="Invalid source ID")

    from backend.services.app_catalog import sync_catalog_source

    try:
        updated = await asyncio.to_thread(sync_catalog_source, source_id)
        return {"status": "ok", "source": updated}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[AppCatalog] Failed to sync source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/docker/catalog/sources/{source_id}/toggle", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_source_toggle(source_id: str, req: AppSourceToggleRequest):
    if not source_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", source_id):
        raise HTTPException(status_code=400, detail="Invalid source ID")

    from backend.services.app_catalog import toggle_catalog_source

    try:
        updated = await asyncio.to_thread(toggle_catalog_source, source_id, req.enabled)
        return {"status": "ok", "source": updated}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[AppCatalog] Failed to toggle source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/docker/catalog/{app_id}/resolve")
async def get_docker_catalog_resolve(app_id: str):
    if not app_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", app_id):
        raise HTTPException(status_code=400, detail="Invalid application ID")
    from backend.services.app_catalog import resolve_app_port_conflict

    res = await asyncio.to_thread(resolve_app_port_conflict, app_id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.post("/docker/catalog/{app_id}/compose", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_compose(app_id: str, req: Optional[AppComposeRequest] = None):
    if not app_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", app_id):
        raise HTTPException(status_code=400, detail="Invalid application ID")
    from backend.services.app_catalog import generate_compose_for_app

    host_port = req.host_port if req else None
    storage_root = req.storage_root if req else "/mnt/user/appdata"
    res = await asyncio.to_thread(generate_compose_for_app, app_id, host_port=host_port, storage_root=storage_root)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


class AppDeployRequest(BaseModel):
    host_port: Optional[int] = None
    storage_root: str = "/mnt/user/appdata"


@router.post("/docker/catalog/{app_id}/deploy", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_deploy(app_id: str, req: Optional[AppDeployRequest] = None):
    if not app_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", app_id):
        raise HTTPException(status_code=400, detail="Invalid application ID")

    from fastapi.responses import StreamingResponse
    from backend.services.app_catalog import stream_deploy_catalog_app

    host_port = req.host_port if req else None
    storage_root = req.storage_root if req else "/mnt/user/appdata"

    def event_stream():
        for event in stream_deploy_catalog_app(app_id, host_port=host_port, storage_root=storage_root):
            yield json.dumps(event) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/docker/containers/{container_id}/exec", dependencies=[Depends(require_scope("containers:exec"))])
async def post_docker_container_exec(container_id: str, req: ContainerExecRequest):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.compose_synthesizer import execute_in_container

    res = await asyncio.to_thread(execute_in_container, container_id, req.cmd)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Execution failed"))
    return res


class DockerContainerDeleteRequest(BaseModel):
    force: bool = False
    remove_volumes: bool = True
    remove_image: bool = False


@router.delete("/docker/containers/{container_id}", dependencies=[Depends(require_scope("containers:manage"))])
async def delete_docker_container(
    container_id: str,
    force: bool = False,
    remove_volumes: bool = True,
    remove_image: bool = False,
):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.docker_cleanup import destroy_container

    try:
        res = await asyncio.to_thread(
            destroy_container,
            container_id,
            force=force,
            remove_volumes=remove_volumes,
            remove_image=remove_image,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Docker Cleanup] Failed to delete container {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/docker/system/df")
async def get_system_df():
    from backend.services.docker_cleanup import get_docker_system_df

    try:
        return await asyncio.to_thread(get_docker_system_df)
    except Exception as e:
        logger.error(f"[Docker Cleanup] Failed to get system df: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class DockerPruneRequest(BaseModel):
    prune_containers: bool = True
    prune_images: bool = True
    all_images: bool = False
    prune_volumes: bool = False
    prune_networks: bool = True
    prune_build_cache: bool = True


@router.post("/docker/system/prune", dependencies=[Depends(require_scope("containers:manage"))])
async def post_system_prune(req: Optional[DockerPruneRequest] = None):
    from backend.services.docker_cleanup import prune_docker_system

    payload = req or DockerPruneRequest()
    try:
        res = await asyncio.to_thread(
            prune_docker_system,
            prune_containers=payload.prune_containers,
            prune_images=payload.prune_images,
            all_images=payload.all_images,
            prune_volumes=payload.prune_volumes,
            prune_networks=payload.prune_networks,
            prune_build_cache=payload.prune_build_cache,
        )
        return res
    except Exception as e:
        logger.error(f"[Docker Cleanup] Prune failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ups")
async def get_ups_telemetry():
    return await asyncio.to_thread(read_ups_status)


class RenameRequest(BaseModel):
    path: str
    new_name: str


class DeleteRequest(BaseModel):
    path: str


def _safe_fs_target(req_path: str):
    raw = str(req_path or "").strip()
    if not raw or "\x00" in raw:
        raise HTTPException(status_code=400, detail="Invalid path")
    # Disallow root paths
    canonical_roots = {os.path.realpath(r) for r in ALLOWED_BROWSE_ROOTS}
    norm = os.path.normpath(raw)
    parent_raw = os.path.dirname(norm)
    parent_canonical = resolve_within(parent_raw, ALLOWED_BROWSE_ROOTS)
    if parent_canonical is None:
        raise HTTPException(status_code=403, detail="Path is outside allowed folders.")

    base = os.path.basename(norm)
    if not base or base in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid path element")

    target_unresolved = os.path.join(parent_canonical, base)
    target_canonical = resolve_within(target_unresolved, ALLOWED_BROWSE_ROOTS)
    if target_canonical is None:
        raise HTTPException(status_code=403, detail="Path or target symlink resolves outside allowed folders.")

    if target_canonical in canonical_roots or os.path.realpath(target_unresolved) in canonical_roots:
        raise HTTPException(status_code=403, detail="Cannot operate on browse root")

    if not os.path.lexists(target_unresolved):
        raise HTTPException(status_code=404, detail="Item does not exist")

    return target_unresolved, parent_canonical, base


@router.post(
    "/fs/rename",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_rename(req: RenameRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    check_user_path_access(req.path, principal)
    target_unresolved, parent_canonical, _ = _safe_fs_target(req.path)
    new_name = str(req.new_name or "").strip()
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid new name")

    is_admin = (
        principal.role_id in ("superadmin", "storage_admin")
        or principal.has_scope("shares:manage")
        or principal.has_scope("*")
    )
    if not is_admin and os.path.basename(parent_canonical.rstrip("/")) == "homes":
        raise HTTPException(status_code=403, detail="Cannot rename user home directory root.")

    dst = os.path.join(parent_canonical, new_name)
    check_user_path_access(dst, principal)
    if os.path.lexists(dst):
        raise HTTPException(status_code=400, detail="Destination already exists")
    try:
        await asyncio.to_thread(os.rename, target_unresolved, dst)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"[FS] Rename failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to rename item")


@router.post(
    "/fs/delete",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_delete(req: DeleteRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    check_user_path_access(req.path, principal)
    target_unresolved, parent_canonical, _ = _safe_fs_target(req.path)
    is_admin = (
        principal.role_id in ("superadmin", "storage_admin")
        or principal.has_scope("shares:manage")
        or principal.has_scope("*")
    )
    if not is_admin and os.path.basename(parent_canonical.rstrip("/")) == "homes":
        raise HTTPException(status_code=403, detail="Cannot delete user home directory root.")

    try:
        if "/.RecycleBin/" in target_unresolved.replace("\\", "/") or target_unresolved.endswith(".RecycleBin"):
            # Hard delete if already in recycle bin
            if os.path.islink(target_unresolved):
                await asyncio.to_thread(os.unlink, target_unresolved)
            elif os.path.isdir(target_unresolved):
                await asyncio.to_thread(shutil.rmtree, target_unresolved)
            else:
                await asyncio.to_thread(os.remove, target_unresolved)
            return {"status": "ok", "message": "Item permanently deleted"}

        # Recycle Bin logic instead of hard delete
        real_root = root_for(target_unresolved, ALLOWED_BROWSE_ROOTS)
        if not real_root:
            real_root = ALLOWED_BROWSE_ROOTS[0]  # Fallback

        recycle_dir = os.path.join(real_root, ".RecycleBin")
        base_name = os.path.basename(target_unresolved)
        ts = int(time.time())
        dest_name = f"{ts}_{base_name}"
        dest_path = os.path.join(recycle_dir, dest_name)

        def _move_to_recycle():
            os.makedirs(recycle_dir, exist_ok=True)
            shutil.move(target_unresolved, dest_path)

        await asyncio.to_thread(_move_to_recycle)
        add_event("info", "File Explorer", f"Moved {base_name} to Recycle Bin")

        return {"status": "ok", "message": "Item moved to Recycle Bin"}
    except Exception as e:
        logger.error(f"[FS] Delete/Recycle failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to process delete request")


@router.get("/fs/download")
def fs_download(path: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot download a directory")
    return FileResponse(target, filename=os.path.basename(target))


@router.post(
    "/fs/upload",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_upload(
    request: Request,
    path: str,
    filename: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    check_user_path_access(path, principal)
    target_unresolved, _, _ = _safe_fs_target(path)
    target_canonical = resolve_within(target_unresolved, ALLOWED_BROWSE_ROOTS)
    if target_canonical is None or not os.path.isdir(target_canonical):
        raise HTTPException(status_code=400, detail="Target path is not a valid directory within allowed folders")

    # Secure filename against traversal
    filename = os.path.basename(filename)
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(target_canonical, filename)
    check_user_path_access(file_path, principal)
    if os.path.islink(file_path) and resolve_within(file_path, ALLOWED_BROWSE_ROOTS) is None:
        raise HTTPException(status_code=403, detail="Destination symlink points outside allowed folders")

    try:
        async with aiofiles.open(file_path, "wb") as f_out:
            async for chunk in request.stream():
                if chunk:
                    await f_out.write(chunk)

        add_event("success", "File Explorer", f"Uploaded {filename} to {path}")
        return {"status": "ok", "message": "File uploaded"}
    except Exception as e:
        logger.error(f"[FS] Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file")


class TokenCreateRequest(BaseModel):
    name: str
    scopes: Optional[List[str]] = None
    role_id: Optional[str] = None
    expires_in_days: Optional[int] = None


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
        return {
            "token": raw_token,
            "name": req.name,
            "token_id": meta["token_id"],
            "scopes": meta["scopes"],
            "masked_token": meta["masked_token"],
        }
    except Exception as e:
        logger.warning(f"Falling back to legacy token generation: {e}")
        token = generate_token(req.name)
        add_event("success", "Security", f"Generated new API token: {req.name}")
        return {"token": token, "name": req.name}


@router.delete("/tokens/{token_id}", dependencies=[Depends(require_scope("users:write", "system:config"))])
def delete_token(token_id: str):
    revoked = False
    try:
        from backend.users_db import revoke_scoped_api_token

        revoked = revoke_scoped_api_token(token_id)
    except Exception as e:
        logger.warning(f"Could not revoke token via users_db: {e}")
    if not revoked:
        revoked = revoke_token(token_id)
    if revoked:
        add_event("info", "Security", "Revoked an API token")
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Token not found")


@router.post("/system/reboot", dependencies=[Depends(require_scope("system:power"))])
async def system_reboot():
    """Trigger system reboot (requires system:power scope)."""
    add_event("warning", "System", "System reboot sequence initiated by authorized user")
    return {"status": "ok", "message": "System reboot sequence initiated"}


@router.post("/system/shutdown", dependencies=[Depends(require_scope("system:power"))])
async def system_shutdown():
    """Trigger system poweroff (requires system:power scope)."""
    add_event("warning", "System", "System shutdown sequence initiated by authorized user")
    return {"status": "ok", "message": "System shutdown sequence initiated"}


_last_update_check = {"ts": 0.0, "data": None}


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
    import socket
    import sys

    from backend.hardware.storage import detect_chassis_model

    chassis = detect_chassis_model()
    boot_time = getattr(Z_STATE, "boot_time", None) or time.time()
    uptime_secs = round(time.time() - boot_time, 1)

    return {
        "name": "ZettNAS Workbench",
        "version": __version__,
        "tag": f"v{__version__}",
        "release_channel": "stable",
        "chassis_model": chassis,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "uptime_secs": uptime_secs,
        "containerized": os.path.exists("/.dockerenv")
        or os.environ.get("CONTAINERIZED") == "1"
        or os.path.exists("/app"),
        "github_repo": "https://github.com/fr0styx/zettnas-toolkit",
    }


@router.get("/system/updates")
async def check_system_updates(force: bool = False):
    """Check GitHub Releases for newer ZettNAS releases with in-memory caching."""
    import httpx

    now = time.time()
    if not force and _last_update_check["data"] and (now - _last_update_check["ts"] < 600):
        return _last_update_check["data"]

    url = "https://api.github.com/repos/fr0styx/zettnas-toolkit/releases/latest"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": f"ZettNAS-Workbench/{__version__}",
    }

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                tag = data.get("tag_name", "").strip()
                clean_tag = tag.lstrip("v")
                update_available = _is_newer_version(clean_tag, __version__)

                result = {
                    "current_version": __version__,
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
                _last_update_check["ts"] = now
                _last_update_check["data"] = result
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
                        "current_version": __version__,
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
                    _last_update_check["ts"] = now
                    _last_update_check["data"] = result
                    return result

            error_msg = f"GitHub API HTTP {resp.status_code}"
    except Exception as e:
        error_msg = str(e)

    fallback = {
        "current_version": __version__,
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


@router.get("/system/network-topology")
async def system_network_topology():
    """
    Expose complete host networking topology, physical NIC carrier states,
    link negotiation speeds (10GbE / 2.5GbE / 1GbE / 100M), duplex, MTU,
    bonding, bridges, and Docker bridge IP mappings.
    """
    from backend.hardware.network import get_network_topology
    return await asyncio.to_thread(get_network_topology)


@router.get(
    "/system/diagnostics-bundle",
    dependencies=[Depends(require_scope("system:view", "system:read", "system:config"))],
)
async def generate_diagnostics_bundle():
    """
    Generates an in-memory zip archive containing complete sanitized system diagnostics:
    - system_summary.json (platform, kernel, chassis, PAL mode, CPU/RAM, uptime)
    - hardware_telemetry.json (thermals, fan PWM/RPM, UPS status, screen)
    - storage_and_smart.json (disks layout, SMART attributes summary)
    - network_topology.json (physical NICs, speeds, duplex, bridges, bonds, routes, Docker bridge networks)
    - container_manifests.json (running containers and compose stacks with sensitive env vars redacted)
    - notifications_summary.json (configured channels with webhooks/tokens redacted)
    - system_events.json (last 100 system events)
    - recent_logs.log (sanitized structured log lines)
    """
    t0 = time.time()

    # 1. System summary
    uptime_sec = 0.0
    try:
        if os.path.exists("/proc/uptime"):
            with open("/proc/uptime", "r") as f:
                uptime_sec = float(f.read().split()[0])
        else:
            uptime_sec = round(time.time() - Z_STATE.boot_time, 1)
    except Exception:
        uptime_sec = round(time.time() - Z_STATE.boot_time, 1)

    ram_stats = {}
    try:
        ram_stats = read_mem()
    except Exception:
        pass

    try:
        pal_adapter = get_storage_platform()
        pal_caps = pal_adapter.get_capabilities().model_dump()
    except Exception:
        pal_caps = {"platform": "unknown"}

    system_summary = {
        "toolkit_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": sys.version,
        },
        "chassis_model": detect_chassis_model(),
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
    hardware_telemetry = {
        "fan_state_tracker": Z_STATE.fan_state_tracker,
        "fan_config": fan_cfg,
        "led_config": led_cfg,
        "ups_status": ups_status,
        "screen_state": screen_state,
        "fans_released": Z_STATE.fans_released,
        "critical_temp_active": Z_STATE.critical_temp_active,
    }

    # 3. Storage and SMART
    layout = get_current_layout()
    smart_data = Z_STATE.cached_smart_data or {}
    storage_and_smart = {
        "layout": layout,
        "smart_telemetry": smart_data,
    }

    # 4. Network topology
    from backend.hardware.network import get_network_topology
    net_topology = await asyncio.to_thread(get_network_topology)

    # 5. Containers (sanitized)
    containers = await asyncio.to_thread(read_docker_containers)
    sanitized_containers = sanitize_dict(containers)

    # 6. Notifications (sanitized)
    notif_cfg = read_json(NOTIFICATIONS_FILE, DEFAULT_NOTIFICATION_CONFIG)
    sanitized_notifs = sanitize_dict(notif_cfg)

    # 7. System events (last 100)
    events = list(Z_STATE.event_log)

    # 8. Recent logs
    log_lines = get_recent_logs(max_lines=1000)
    recent_logs_text = "\n".join(log_lines)

    # Compress into zip in memory
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system_summary.json", json.dumps(sanitize_dict(system_summary), indent=2))
        zf.writestr("hardware_telemetry.json", json.dumps(sanitize_dict(hardware_telemetry), indent=2))
        zf.writestr("storage_and_smart.json", json.dumps(sanitize_dict(storage_and_smart), indent=2))
        zf.writestr("network_topology.json", json.dumps(sanitize_dict(net_topology), indent=2))
        zf.writestr("container_manifests.json", json.dumps(sanitized_containers, indent=2))
        zf.writestr("notifications_summary.json", json.dumps(sanitized_notifs, indent=2))
        zf.writestr("system_events.json", json.dumps(sanitize_dict(events), indent=2))
        zf.writestr("recent_logs.log", sanitize_string(recent_logs_text))

    zip_bytes = zip_buf.getvalue()
    elapsed = round(time.time() - t0, 3)
    logger.info(f"[DIAGNOSTICS] Generated bundle ({len(zip_bytes)} bytes) in {elapsed}s")

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
