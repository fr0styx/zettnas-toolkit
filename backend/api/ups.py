"""
ZettNAS Toolkit - UPS & Power Management API Router
Provides REST endpoints for live telemetry, configuration, USB/LAN auto-discovery,
connection testing, battery self-test execution, outage simulation, and event logs.
"""

import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.db import query_ups_events
from backend.hardware.ups import (
    DEFAULT_UPS_CONFIG,
    discover_ups_sources,
    load_ups_config,
    mask_ups_config,
    read_ups_status,
    run_ups_self_test,
    save_ups_config,
    test_ups_connection,
)
from backend.services.ups_watchdog import trigger_outage_simulation

router = APIRouter(tags=["UPS & Power Integrity"])


class UpsConfigRequest(BaseModel):
    enabled: bool = True
    mode: str = Field(default="auto", description="'auto', 'nut_client', 'apcupsd_client', 'usb_hid', 'snmp'")
    host: str = "127.0.0.1"
    port: int = 3551
    ups_name: str = "ups"
    username: Optional[str] = ""
    password: Optional[str] = ""
    shutdown_policy: str = Field(default="runtime_left", description="'runtime_left', 'battery_pct', 'timer'")
    shutdown_timer_sec: int = 300
    battery_threshold_pct: int = 20
    runtime_threshold_min: int = 5
    container_shutdown_timeout_sec: int = 30
    poweroff_ups: bool = False
    notify_on_battery: bool = True
    notify_on_restore: bool = True
    notify_on_low_battery: bool = True


class UpsTestConnectionRequest(BaseModel):
    host: str = "127.0.0.1"
    port: int = 3551
    mode: str = "auto"
    ups_name: Optional[str] = ""
    username: Optional[str] = ""
    password: Optional[str] = ""


class UpsSimulateRequest(BaseModel):
    duration_sec: int = Field(default=15, ge=5, le=60)


@router.get("/ups")
async def get_ups_telemetry():
    """Returns real-time UPS telemetry enriched with power flow metrics and voltage data."""
    return await asyncio.to_thread(read_ups_status)


@router.get("/ups/config")
async def get_ups_configuration():
    """Returns persistent UPS configuration with secret passwords masked."""
    cfg = await asyncio.to_thread(load_ups_config)
    return mask_ups_config(cfg)


@router.post("/ups/config", dependencies=[Depends(require_scope("system:config"))])
async def post_ups_configuration(req: UpsConfigRequest):
    """Saves persistent UPS configuration and reloads power watchdog parameters."""
    try:
        saved = await asyncio.to_thread(save_ups_config, req.model_dump())
        return saved
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save UPS configuration: {e}")


@router.post("/ups/discover")
async def post_ups_discover():
    """Auto-discovers connected USB HID power devices and active LAN power daemons."""
    candidates = await asyncio.to_thread(discover_ups_sources)
    return {"candidates": candidates, "count": len(candidates)}


@router.post("/ups/test-connection")
async def post_ups_test_connection(req: UpsTestConnectionRequest):
    """Validates connection to a UPS daemon without altering persistent configuration."""
    res = await asyncio.to_thread(
        test_ups_connection,
        host=req.host,
        port=req.port,
        mode=req.mode,
        ups_name=req.ups_name or "",
        username=req.username or "",
        password=req.password or "",
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Connection test failed"))
    return res


@router.post("/ups/self-test", dependencies=[Depends(require_scope("system:config"))])
async def post_ups_self_test():
    """Issues 10-second battery self-test diagnostic command to the configured UPS."""
    res = await asyncio.to_thread(run_ups_self_test)
    return res


@router.get("/ups/events")
async def get_ups_event_history(limit: int = 50):
    """Returns historical power events, outages, brownouts, and diagnostic logs from SQLite."""
    events = await asyncio.to_thread(query_ups_events, limit=max(1, min(limit, 200)))
    return {"events": events, "count": len(events)}


@router.post("/ups/simulate", dependencies=[Depends(require_scope("system:config"))])
async def post_ups_simulate(req: UpsSimulateRequest):
    """Triggers simulated power outage drill for desktop UI testing."""
    return trigger_outage_simulation(duration_sec=req.duration_sec)
