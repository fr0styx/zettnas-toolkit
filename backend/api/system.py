import aiofiles
import asyncio
import os
import re
import shutil
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

import backend.config as config
from backend import __version__
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
from backend.hardware.disks import fetch_disk_smart_detail, run_disk_smart_test
from backend.hardware.docker_stats import container_action, read_docker_containers
from backend.hardware.fans import set_fan_pwm
from backend.hardware.led import apply_led_state
from backend.hardware.screen import get_screen_state, save_screen_state
from backend.hardware.storage import get_current_layout
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


@router.post("/disk_wake")
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


@router.post("/disk/smart_test")
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


@router.get("/screen")
def screen_state():
    return get_screen_state()


@router.post("/screen")
async def post_screen_state(req: ScreenConfigRequest):
    data = req.model_dump(exclude_unset=True)
    return await asyncio.to_thread(save_screen_state, data)


def _handle_browse_logic(path: str, dirs_only: bool):
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
    for e in sorted(entries):
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
async def browse(path: str = "", dirs_only: str = "0"):
    return await asyncio.to_thread(_handle_browse_logic, path, dirs_only == "1")


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


@router.post("/mkdir")
def mkdir(req: MkdirRequest):
    return _do_mkdir(req.path)


@router.post("/copy/cancel")
def copy_cancel():
    Z_STATE.copy_abort_flag = True
    Z_STATE.copy_overwrite_choice = "cancel"
    Z_STATE.copy_confirm_event.set()
    if not Z_STATE.copy_active:
        Z_STATE.copy_status = "idle"
        Z_STATE.ui_wake.set()
    return {"status": "ok"}


@router.post("/copy/confirm")
def copy_confirm(req: CopyConfirmRequest):
    Z_STATE.copy_overwrite_choice = req.action
    Z_STATE.copy_confirm_event.set()
    return {"status": "ok"}


@router.post("/copy/pause")
def pause_copy():
    Z_STATE.copy_paused = True
    return {"status": "paused"}


@router.post("/copy/resume")
def resume_copy():
    Z_STATE.copy_paused = False
    return {"status": "resumed"}


@router.post("/copy/start")
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


@router.post("/copy/dismiss-ingest")
def dismiss_pending_ingest():
    Z_STATE.pending_ingest = None
    Z_STATE.ui_wake.set()
    return {"status": "dismissed"}


@router.post("/copy/rescan")
def rescan_media():
    from backend.services.copy_engine import rescan_media_slots

    slots = rescan_media_slots(force_usb_reset=True)
    return {"status": "ok", "slots": slots}


@router.post("/copy/eject")
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


@router.post("/buttons")
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
    return state


@router.delete("/events/clear")
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


@router.post("/lcd/page")
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


@router.post("/lcd/cycle")
def post_lcd_cycle():
    new_page = Z_STATE.cycle_lcd_page()
    return {"status": "ok", "page": new_page}


@router.get("/copy/history")
def get_copy_history(limit: int = 50):
    return query_copy_history(limit)


@router.get("/unraid")
def get_unraid_telemetry():
    return read_unraid_status(force=True)


@router.post("/system/profile")
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


@router.post("/docker/containers/{container_id}/action")
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


@router.post("/docker/containers/{container_id}/resources")
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


@router.post("/docker/containers/{container_id}/ports")
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


@router.post("/fs/rename")
async def fs_rename(req: RenameRequest):
    target_unresolved, parent_canonical, _ = _safe_fs_target(req.path)
    new_name = str(req.new_name or "").strip()
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid new name")

    dst = os.path.join(parent_canonical, new_name)
    if os.path.lexists(dst):
        raise HTTPException(status_code=400, detail="Destination already exists")
    try:
        await asyncio.to_thread(os.rename, target_unresolved, dst)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"[FS] Rename failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to rename item")


@router.post("/fs/delete")
async def fs_delete(req: DeleteRequest):
    target_unresolved, _, _ = _safe_fs_target(req.path)
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
        if not os.path.exists(recycle_dir):
            os.makedirs(recycle_dir, exist_ok=True)

        base_name = os.path.basename(target_unresolved)
        ts = int(time.time())
        dest_name = f"{ts}_{base_name}"
        dest_path = os.path.join(recycle_dir, dest_name)

        await asyncio.to_thread(shutil.move, target_unresolved, dest_path)
        add_event("info", "File Explorer", f"Moved {base_name} to Recycle Bin")

        return {"status": "ok", "message": "Item moved to Recycle Bin"}
    except Exception as e:
        logger.error(f"[FS] Delete/Recycle failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to process delete request")


@router.get("/fs/download")
def fs_download(path: str):
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot download a directory")
    return FileResponse(target, filename=os.path.basename(target))


@router.post("/fs/upload")
async def fs_upload(request: Request, path: str, filename: str):
    target_unresolved, _, _ = _safe_fs_target(path)
    target_canonical = resolve_within(target_unresolved, ALLOWED_BROWSE_ROOTS)
    if target_canonical is None or not os.path.isdir(target_canonical):
        raise HTTPException(status_code=400, detail="Target path is not a valid directory within allowed folders")

    # Secure filename against traversal
    filename = os.path.basename(filename)
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(target_canonical, filename)
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


@router.get("/tokens")
def list_tokens():
    tokens = load_tokens()
    # Mask the token for security when listing; id is the opaque UUID
    res = []
    for tid, data in tokens.items():
        res.append(
            {
                "id": str(tid),  # Opaque UUID for management
                "masked_token": data.get("masked_token", "zat_..."),
                "name": data.get("name"),
                "created": data.get("created"),
            }
        )
    return res


@router.post("/tokens")
def create_token(req: TokenCreateRequest):
    token = generate_token(req.name)
    add_event("success", "Security", f"Generated new API token: {req.name}")
    return {"token": token, "name": req.name}


@router.delete("/tokens/{token_id}")
def delete_token(token_id: str):
    if revoke_token(token_id):
        add_event("info", "Security", "Revoked an API token")
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Token not found")
