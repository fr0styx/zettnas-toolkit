"""
ZettNAS Toolkit - Chassis Visualizer & Layout API Routes
"""

from fastapi import APIRouter
from backend.hardware.chassis import ChassisEngine, ChassisBayMapRequest

router = APIRouter(prefix="/chassis", tags=["Chassis Visualizer & Layout"])


@router.get("/config")
def get_chassis_config():
    """
    Returns dynamic chassis layout configuration, detected bays, populated disks,
    and motherboard M.2 NVMe slots.
    """
    return ChassisEngine.get_chassis_status()


@router.post("/bay_map")
def save_chassis_bay_map(request: ChassisBayMapRequest):
    """
    Saves user-customized chassis profile, total bays, and drag-and-drop bay slot assignments.
    """
    return ChassisEngine.save_bay_mapping(request)
