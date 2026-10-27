"""Snapshot schedules, browsing and restoring files from snapshots (Batch 6)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import require_confirmation
from backend.services import snapshot_service as snaps

router = APIRouter(tags=["Snapshots"])


class ScheduleIn(BaseModel):
    share: str = Field(min_length=1, max_length=128)
    every: Literal["hourly", "daily", "weekly"] = "daily"
    keep: int = Field(default=14, ge=1, le=1000)
    keep_daily: int = Field(default=0, ge=0, le=3650, description="Also keep one a day for this many days")
    immutable_days: int = Field(default=0, ge=0, le=3650, description="Days each snapshot can't be deleted")


class RestoreIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    overwrite: bool = False


@router.get("/snapshots/schedules", dependencies=[Depends(require_scope("backup:read", "storage:read"))])
def get_schedules():
    ok, why = snaps.availability()
    return {"schedules": snaps.list_schedules(), "available": ok, "reason": why}


@router.put("/snapshots/schedules", dependencies=[Depends(require_scope("backup:manage", "storage:admin"))])
def put_schedule(req: ScheduleIn):
    try:
        return snaps.save_schedule(req.share, req.every, req.keep, req.immutable_days, keep_daily=req.keep_daily)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.delete("/snapshots/schedules/{share}", dependencies=[Depends(require_scope("backup:manage", "storage:admin"))])
def remove_schedule(share: str):
    if not snaps.delete_schedule(share):
        raise HTTPException(status_code=404, detail="No schedule for that share.")
    return {"status": "deleted", "share": share}


@router.post(
    "/snapshots/schedules/{share}/run", dependencies=[Depends(require_scope("backup:manage", "storage:admin"))]
)
def run_now(share: str):
    return snaps.take(share)


@router.get("/snapshots/{name}/browse", dependencies=[Depends(require_scope("backup:read", "storage:read"))])
def browse(name: str, path: str = "", principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    try:
        return snaps.browse(name, path, principal=principal)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None


@router.post(
    "/snapshots/{name}/rollback",
    dependencies=[
        Depends(require_scope("backup:manage", "storage:admin")),
        Depends(require_confirmation("snapshot.rollback")),
    ],
)
def rollback(name: str):
    """Puts the whole share back as it was in this snapshot; the current state is kept as a snapshot."""
    try:
        return snaps.rollback(name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/snapshots/{name}/restore", dependencies=[Depends(require_scope("backup:manage", "storage:admin"))])
def restore(name: str, req: RestoreIn):
    try:
        return snaps.restore(name, req.path, overwrite=req.overwrite)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
