from fastapi import APIRouter, HTTPException

from backend.config import FAN_STATE_FILE
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.fans import sanitize_curve_points
from backend.models.schemas import FanConfigRequest

router = APIRouter(tags=["Thermal & Fan Control"])

FAN_DEFAULTS = {"profile": "auto", "manual_pct": 60, "ctrl_cpu_fan": False, "temp_min": 37, "temp_max": 50}
VALID_PROFILES = {"auto", "quiet", "balanced", "performance", "full", "manual"}


def _load_fans():
    cfg = dict(FAN_DEFAULTS)
    saved = read_json(FAN_STATE_FILE, {})
    if isinstance(saved, dict):
        cfg.update(saved)
    return cfg


@router.get("/fans")
async def get_fans():
    return _load_fans()


@router.post("/fans")
async def post_fans(req: FanConfigRequest):
    data = req.model_dump(exclude_unset=True)

    if "profile" in data and data["profile"] is not None and data["profile"] not in VALID_PROFILES:
        raise HTTPException(status_code=400, detail="Invalid fan profile")
    if data.get("manual_pct") is not None:
        data["manual_pct"] = max(0, min(100, int(data["manual_pct"])))
    for key in ("temp_min", "temp_max"):
        if data.get(key) is not None:
            data[key] = max(0, min(100, int(data[key])))
    if "curve_points" in data:
        # Monotonic, bounded, deduplicated — or None (falls back to linear curve).
        data["curve_points"] = sanitize_curve_points(data["curve_points"])

    fan_cfg = _load_fans()
    fan_cfg.update(data)
    if fan_cfg.get("temp_min", 0) >= fan_cfg.get("temp_max", 100):
        fan_cfg["temp_max"] = min(100, fan_cfg["temp_min"] + 1)
    atomic_write_json(FAN_STATE_FILE, fan_cfg)
    return fan_cfg
