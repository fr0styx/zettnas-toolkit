from fastapi import APIRouter, Depends, HTTPException

from backend.auth import require_scope
from backend.config import (
    FAN_STATE_FILE,
    FAN_ZERO_RPM_DEFAULT_NVME_CEILING,
    FAN_ZERO_RPM_DEFAULT_START_TEMP,
    FAN_ZERO_RPM_DEFAULT_STOP_TEMP,
)
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.fans import sanitize_curve_points
from backend.models.schemas import FanConfigRequest, FanPresetCreate

router = APIRouter(tags=["Thermal & Fan Control"])

FAN_DEFAULTS = {
    "profile": "auto",
    "manual_pct": 60,
    "ctrl_cpu_fan": False,
    "temp_min": 37,
    "temp_max": 50,
    "zero_rpm_enabled": False,
    "zero_rpm_nvme_ceiling": FAN_ZERO_RPM_DEFAULT_NVME_CEILING,
    "zero_rpm_stop_temp": FAN_ZERO_RPM_DEFAULT_STOP_TEMP,
    "zero_rpm_start_temp": FAN_ZERO_RPM_DEFAULT_START_TEMP,
}
VALID_PROFILES = {"auto", "quiet", "balanced", "performance", "full", "manual"}


def _load_fans():
    cfg = dict(FAN_DEFAULTS)
    saved = read_json(FAN_STATE_FILE, {})
    if isinstance(saved, dict):
        cfg.update(saved)
    return cfg


@router.get("/fans")
def get_fans():
    return _load_fans()


@router.post("/fans", dependencies=[Depends(require_scope("hardware:fans"))])
def post_fans(req: FanConfigRequest):
    data = req.model_dump(exclude_unset=True)

    if "profile" in data and data["profile"] is not None and data["profile"] not in VALID_PROFILES:
        raise HTTPException(status_code=400, detail="Invalid fan profile")
    if data.get("manual_pct") is not None:
        data["manual_pct"] = max(0, min(100, int(data["manual_pct"])))
    for key in ("temp_min", "temp_max"):
        if data.get(key) is not None:
            data[key] = max(0, min(100, int(data[key])))
    if "zero_rpm_enabled" in data and data["zero_rpm_enabled"] is not None:
        data["zero_rpm_enabled"] = bool(data["zero_rpm_enabled"])
    if data.get("zero_rpm_nvme_ceiling") is not None:
        data["zero_rpm_nvme_ceiling"] = max(40, min(70, int(data["zero_rpm_nvme_ceiling"])))
    if data.get("zero_rpm_stop_temp") is not None:
        data["zero_rpm_stop_temp"] = max(25, min(45, int(data["zero_rpm_stop_temp"])))
    if data.get("zero_rpm_start_temp") is not None:
        data["zero_rpm_start_temp"] = max(30, min(55, int(data["zero_rpm_start_temp"])))
    for curve_field in (
        "curve_points",
        "nvme_curve_points",
        "cpu_curve_points",
        "zone1_curve_points",
        "zone2_curve_points",
    ):
        if curve_field in data and data[curve_field] is not None:
            data[curve_field] = sanitize_curve_points(data[curve_field])

    fan_cfg = _load_fans()
    fan_cfg.update(data)
    if fan_cfg.get("temp_min", 0) >= fan_cfg.get("temp_max", 100):
        fan_cfg["temp_max"] = min(100, fan_cfg["temp_min"] + 1)
    if fan_cfg.get("zero_rpm_stop_temp", 34) >= fan_cfg.get("zero_rpm_start_temp", 38):
        fan_cfg["zero_rpm_start_temp"] = min(55, fan_cfg["zero_rpm_stop_temp"] + 2)
    atomic_write_json(FAN_STATE_FILE, fan_cfg)
    return fan_cfg


@router.get("/fans/presets")
def get_fan_presets():
    """Lists all saved custom fan curve presets."""
    fan_cfg = _load_fans()
    return {"presets": fan_cfg.get("custom_presets", {})}


@router.post("/fans/presets", dependencies=[Depends(require_scope("hardware:fans"))])
def create_fan_preset(req: FanPresetCreate):
    """Saves or updates a custom named fan curve preset."""
    clean_curve = sanitize_curve_points(req.curve_points)
    if not clean_curve:
        raise HTTPException(status_code=400, detail="Curve points must have at least 2 valid points.")

    fan_cfg = _load_fans()
    if "custom_presets" not in fan_cfg or not isinstance(fan_cfg["custom_presets"], dict):
        fan_cfg["custom_presets"] = {}

    preset_data = {
        "name": req.name,
        "curve_points": clean_curve,
    }
    if req.nvme_curve_points:
        clean_nvme = sanitize_curve_points(req.nvme_curve_points)
        if clean_nvme:
            preset_data["nvme_curve_points"] = clean_nvme
    if req.cpu_curve_points:
        clean_cpu = sanitize_curve_points(req.cpu_curve_points)
        if clean_cpu:
            preset_data["cpu_curve_points"] = clean_cpu

    fan_cfg["custom_presets"][req.name] = preset_data
    atomic_write_json(FAN_STATE_FILE, fan_cfg)
    return {"success": True, "name": req.name, "preset": preset_data}


@router.delete("/fans/presets/{preset_name}", dependencies=[Depends(require_scope("hardware:fans"))])
def delete_fan_preset(preset_name: str):
    """Deletes a custom named fan curve preset."""
    fan_cfg = _load_fans()
    presets = fan_cfg.get("custom_presets", {})
    if preset_name not in presets:
        raise HTTPException(status_code=404, detail="Preset not found")

    del presets[preset_name]
    fan_cfg["custom_presets"] = presets
    atomic_write_json(FAN_STATE_FILE, fan_cfg)
    return {"success": True, "deleted": preset_name}


@router.post("/fans/presets/{preset_name}/apply", dependencies=[Depends(require_scope("hardware:fans"))])
def apply_fan_preset(preset_name: str):
    """Applies a custom named preset to the active fan curve."""
    fan_cfg = _load_fans()
    presets = fan_cfg.get("custom_presets", {})
    if preset_name not in presets:
        raise HTTPException(status_code=404, detail="Preset not found")

    preset = presets[preset_name]
    fan_cfg["curve_points"] = preset["curve_points"]
    if "nvme_curve_points" in preset:
        fan_cfg["nvme_curve_points"] = preset["nvme_curve_points"]
    if "cpu_curve_points" in preset:
        fan_cfg["cpu_curve_points"] = preset["cpu_curve_points"]
    fan_cfg["profile"] = "auto"
    atomic_write_json(FAN_STATE_FILE, fan_cfg)
    return {"success": True, "applied": preset_name, "fan_config": fan_cfg}
