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
from backend.hardware.screen import get_screen_state
from backend.hardware.storage import get_current_layout
from backend.hardware.unraid import read_unraid_status
from backend.hardware.docker_stats import container_action, read_docker_containers
from backend.hardware.ups import read_ups_status
from backend.models.schemas import (
    ButtonConfigRequest,
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

