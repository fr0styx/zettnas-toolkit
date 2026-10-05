import os
import re
import json
import time
from fastapi import APIRouter, Request, HTTPException
from backend.config import logger, BUTTON_CFG_FILE, DASH_LAYOUT_FILE, EVENTS_FILE
import backend.config as config
from backend.state import Z_STATE
from backend.hardware.disks import fetch_disk_smart_detail
from backend.hardware.screen import get_screen_state
from backend.models.schemas import (
    ButtonConfigRequest, CopyConfirmRequest, MkdirRequest
)

router = APIRouter(tags=["System & Storage"])

@router.get("/disk_detail")
async def disk_detail(dev: str = "sda"):
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    return fetch_disk_smart_detail(dev)

@router.get("/screen")
async def screen_state():
    return get_screen_state()

def _handle_browse_logic(path: str, dirs_only: bool):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Path does not exist.")
    out = []
    if path != "/":
        parent = os.path.dirname(path.rstrip("/"))
        if not parent: parent = "/"
        out.append({"name": "..", "path": parent, "is_dir": True, "size": 0})
    try:
        entries = os.listdir(path)
        for e in sorted(entries):
            full = os.path.join(path, e)
            is_dir = os.path.isdir(full)
            if dirs_only and not is_dir:
                continue
            sz = 0
            if not is_dir and not os.path.islink(full):
                try: sz = os.path.getsize(full)
                except OSError: pass
            out.append({"name": e, "path": full, "is_dir": is_dir, "size": sz})
        return {"current": path, "dirs": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/browse")
async def browse(path: str = "/mnt/user", dirs_only: str = "0"):
    d_only = (dirs_only == "1")
    return _handle_browse_logic(path, d_only)

@router.post("/mkdir")
async def mkdir(req: MkdirRequest):
    path = str(req.path).strip()
    if not path.startswith("/mnt/user/") or ".." in path:
        raise HTTPException(status_code=400, detail="Invalid path")
    os.makedirs(path, exist_ok=True)
    return {"status": "ok"}

@router.get("/mkdir", include_in_schema=False)
async def mkdir_legacy_get(path: str = ""):
    path = str(path).strip()
    if not path.startswith("/mnt/user/") or ".." in path:
        raise HTTPException(status_code=400, detail="Invalid path")
    os.makedirs(path, exist_ok=True)
    return {"status": "ok"}

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

@router.get("/buttons")
async def get_buttons():
    if os.path.exists(BUTTON_CFG_FILE):
        try:
            with open(BUTTON_CFG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError): pass
    return {"enabled": False, "source": "sd", "dest": "/mnt/user/"}

@router.post("/buttons")
async def post_buttons(req: ButtonConfigRequest):
    data = req.model_dump(exclude_unset=True)
    state = {"enabled": False, "source": "sd", "dest": "/mnt/user/"}
    if os.path.exists(BUTTON_CFG_FILE):
        try:
            with open(BUTTON_CFG_FILE, "r") as f:
                state.update(json.load(f))
        except (json.JSONDecodeError, OSError): pass
    state.update(data)

    dest_val = str(data.get("dest", state["dest"])).strip()
    if "dest" in data:
        if not os.path.exists(dest_val):
            raise HTTPException(status_code=400, detail=f"Path does not exist: {dest_val}")

    with open(BUTTON_CFG_FILE, "w") as f:
        json.dump(state, f)
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

@router.post("/events/clear", include_in_schema=False)
@router.get("/events/clear", include_in_schema=False)
async def clear_events_compat():
    return await clear_events()

@router.post("/layout")
async def post_layout(request: Request):
    data = await request.json()
    data["version"] = int(time.time() * 1000)
    with open(DASH_LAYOUT_FILE, "w") as f:
        json.dump(data, f)
    with Z_STATE.lock:
        if Z_STATE.cached_stats:
            Z_STATE.cached_stats["layout"] = data
    return {"status": "ok", "layout": data}

@router.post("/state")
async def post_state(request: Request):
    data = await request.json()
    if "fb" in data:
        config.ENABLE_FB = bool(data["fb"])
    return {"status": "ok"}
