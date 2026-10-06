from pydantic import BaseModel
import shutil
from fastapi.responses import FileResponse
import asyncio
import os
import re
import time

from fastapi import APIRouter, HTTPException

import backend.config as config
from backend import __version__
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
from backend.hardware.fans import set_fan_pwm
from backend.hardware.led import apply_led_state
from backend.hardware.screen import get_screen_state, save_screen_state
from backend.hardware.storage import get_current_layout
from backend.hardware.unraid import read_unraid_status
from backend.hardware.docker_stats import container_action, read_docker_containers
from backend.hardware.ups import read_ups_status
from backend.models.schemas import (
    ButtonConfigRequest,
    ScreenConfigRequest,
    CopyConfirmRequest,
    DockerActionRequest,
    LayoutRequest,
    LcdPageRequest,
    MkdirRequest,
    StateRequest,
    SystemProfileRequest,
)
from backend.state import Z_STATE

router = APIRouter(tags=["System & Storage"])


@router.get("/health")
async def health():
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
async def disk_smart_test(payload: dict):
    dev = str(payload.get("dev", "sda"))
    test_type = str(payload.get("test_type", "short"))
    if dev.startswith("/dev/"):
        dev = dev.replace("/dev/", "")
    m = re.match(r"^nv([0-9]+)$", dev)
    if m:
        dev = f"nvme{m.group(1)}n1"
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    return await asyncio.to_thread(run_disk_smart_test, dev, test_type)


@router.get("/screen")
async def screen_state():
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
async def mkdir(req: MkdirRequest):
    return _do_mkdir(req.path)


@router.post("/copy/cancel")
async def copy_cancel():
    Z_STATE.copy_abort_flag = True
    Z_STATE.copy_overwrite_choice = "cancel"
    Z_STATE.copy_confirm_event.set()
    if not Z_STATE.copy_active:
        Z_STATE.copy_status = "idle"
        Z_STATE.ui_wake.set()
    return {"status": "ok"}


@router.post("/copy/confirm")
async def copy_confirm(req: CopyConfirmRequest):
    Z_STATE.copy_overwrite_choice = req.action
    Z_STATE.copy_confirm_event.set()
    return {"status": "ok"}


@router.post("/copy/pause")
async def pause_copy():
    Z_STATE.copy_paused = True
    return {"status": "paused"}


@router.post("/copy/resume")
async def resume_copy():
    Z_STATE.copy_paused = False
    return {"status": "resumed"}


@router.post("/copy/start")
async def start_copy():
    if Z_STATE.copy_active:
        raise HTTPException(status_code=409, detail="Copy operation already in progress")
    cfg = _load_buttons()
    Z_STATE.copy_active = True
    Z_STATE.copy_status = "copying"
    Z_STATE.ui_wake.set()
    add_event("info", "Copy Started", "Starting ingest from media slot...")
    from backend.services.copy_engine import _do_copy

    threading.Thread(target=lambda c: asyncio.run(_do_copy(c)), args=(cfg,), daemon=True).start()
    return {"status": "started"}


BUTTON_DEFAULTS = {"enabled": False, "source": "sd", "dest": "/mnt/user/"}


def _load_buttons():
    state = dict(BUTTON_DEFAULTS)
    saved = read_json(BUTTON_CFG_FILE, {})
    if isinstance(saved, dict):
        state.update(saved)
    return state


@router.get("/buttons")
async def get_buttons():
    return _load_buttons()


@router.post("/buttons")
async def post_buttons(req: ButtonConfigRequest):
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
async def clear_events():
    with Z_STATE.lock:
        Z_STATE.event_log = []
    if os.path.exists(EVENTS_FILE):
        try:
            os.remove(EVENTS_FILE)
        except OSError:
            pass
    return {"status": "ok"}


@router.get("/layout")
async def get_layout():
    return get_current_layout()


@router.post("/layout")
async def post_layout(req: LayoutRequest):
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
async def post_state(req: StateRequest):
    if req.fb is not None:
        config.ENABLE_FB = bool(req.fb)
    return {"status": "ok"}


@router.get("/lcd/page")
async def get_lcd_page():
    return {
        "page": Z_STATE.current_lcd_page,
        "cycle_seconds": Z_STATE.lcd_cycle_seconds,
    }


@router.post("/lcd/page")
async def post_lcd_page(req: LcdPageRequest):
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
async def post_lcd_cycle():
    new_page = Z_STATE.cycle_lcd_page()
    return {"status": "ok", "page": new_page}


@router.get("/copy/history")
async def get_copy_history(limit: int = 50):
    return query_copy_history(limit)


@router.get("/unraid")
async def get_unraid_telemetry():
    return read_unraid_status(force=True)


@router.post("/system/profile")
async def set_system_profile(req: SystemProfileRequest):
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
    if os.path.realpath(target_unresolved) in canonical_roots:
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
        import time
        from backend.state import add_event

        # Find which root this belongs to
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
async def fs_download(path: str):
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot download a directory")
    return FileResponse(target, filename=os.path.basename(target))


from fastapi import Request


@router.post("/fs/upload")
async def fs_upload(request: Request, path: str, filename: str):
    target_unresolved, _, _ = _safe_fs_target(path)
    if not os.path.isdir(target_unresolved):
        raise HTTPException(status_code=400, detail="Target path is not a directory")

    # Secure filename against traversal
    filename = os.path.basename(filename)
    if not filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(target_unresolved, filename)
    try:
        content = await request.body()
        with open(file_path, "wb") as f_out:
            f_out.write(content)

        from backend.state import add_event

        add_event("success", "File Explorer", f"Uploaded {filename} to {path}")
        return {"status": "ok", "message": "File uploaded"}
    except Exception as e:
        logger.error(f"[FS] Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file")


from pydantic import BaseModel


class TokenCreateRequest(BaseModel):
    name: str


@router.get("/tokens")
async def list_tokens():
    from backend.api_tokens import load_tokens

    tokens = load_tokens()
    # Mask the token for security when listing
    res = []
    for t, data in tokens.items():
        res.append(
            {
                "masked_token": t[:8] + "..." + t[-4:],
                "name": data.get("name"),
                "created": data.get("created"),
                "id": t,  # we need the ID to revoke it
            }
        )
    return res


@router.post("/tokens")
async def create_token(req: TokenCreateRequest):
    from backend.api_tokens import generate_token
    from backend.state import add_event

    token = generate_token(req.name)
    add_event("success", "Security", f"Generated new API token: {req.name}")
    return {"token": token, "name": req.name}


@router.delete("/tokens/{token_id}")
async def delete_token(token_id: str):
    from backend.api_tokens import revoke_token
    from backend.state import add_event

    if revoke_token(token_id):
        add_event("info", "Security", "Revoked an API token")
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Token not found")
