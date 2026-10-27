"""
ZettNAS Toolkit - Chassis Visualizer & Layout API Routes
"""

from fastapi import APIRouter, Depends

from backend.auth import require_scope
from backend.hardware.chassis import ChassisBayMapRequest, ChassisEngine

router = APIRouter(prefix="/chassis", tags=["Chassis Visualizer & Layout"])


@router.get("/config", dependencies=[Depends(require_scope("hardware:read", "storage:read", "system:view"))])
def get_chassis_config():
    """
    Returns dynamic chassis layout configuration, detected bays, populated disks,
    and motherboard M.2 NVMe slots.
    """
    return ChassisEngine.get_chassis_status()


@router.post("/bay_map", dependencies=[Depends(require_scope("storage:admin", "system:config"))])
def save_chassis_bay_map(request: ChassisBayMapRequest):
    """
    Saves user-customized chassis profile, total bays, and drag-and-drop bay slot assignments.
    """
    return ChassisEngine.save_bay_mapping(request)


@router.get("/bridges", dependencies=[Depends(require_scope("hardware:read", "storage:read", "system:view"))])
def get_chassis_bridges():
    """Returns detected hardware platform bridges (Zettlab, Aoostar, Ugreen, CWWK)."""
    return ChassisEngine.get_appliance_bridge_status()
