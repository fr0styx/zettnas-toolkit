import os
import json
from fastapi import APIRouter
from backend.config import FAN_STATE_FILE
from backend.models.schemas import FanConfigRequest

router = APIRouter(tags=["Thermal & Fan Control"])

@router.get("/fans")
async def get_fans():
    fan_cfg = {"profile": "auto", "manual_pct": 60, "ctrl_cpu_fan": False, "temp_min": 37, "temp_max": 50}
    if os.path.exists(FAN_STATE_FILE):
        try:
            with open(FAN_STATE_FILE, "r") as f:
                fan_cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError): pass
    return fan_cfg

@router.post("/fans")
async def post_fans(req: FanConfigRequest):
    data = req.model_dump(exclude_unset=True)
    fan_cfg = {"profile": "auto", "manual_pct": 60, "ctrl_cpu_fan": False, "temp_min": 37, "temp_max": 50}
    if os.path.exists(FAN_STATE_FILE):
        try:
            with open(FAN_STATE_FILE, "r") as f:
                fan_cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError): pass
    fan_cfg.update(data)
    with open(FAN_STATE_FILE, "w") as f:
        json.dump(fan_cfg, f)
    return fan_cfg
