"""
ZettNAS Toolkit - Replication API Router
Exposes endpoints for managing automated snapshot replication pipelines.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.paging import PageParams
from backend.services.replication_engine import get_replication_engine

router = APIRouter(prefix="/storage/replication", tags=["Storage Replication"])


class ReplicationJobCreateRequest(BaseModel):
    name: str = Field(..., max_length=128)
    source_pool: str = Field(..., max_length=128)
    source_dataset: str = Field(default="", max_length=256)
    target_type: str = Field(default="local", pattern=r"^(local|remote_ssh|remote_wireguard)$")
    target_host: str | None = Field(default=None, max_length=256)
    target_port: int = Field(default=22, ge=1, le=65535)
    target_user: str = Field(default="root", max_length=64)
    target_pool: str = Field(..., max_length=128)
    target_dataset: str = Field(default="", max_length=256)
    bandwidth_limit_kbps: int | None = Field(default=None, ge=100)
    incremental: bool = Field(default=True)
    retention_count: int = Field(default=14, ge=1, le=365)
    schedule: str = Field(default="daily", pattern=r"^(manual|hourly|daily|weekly)$")


@router.get("/jobs", dependencies=[Depends(require_scope("storage:read"))])
def list_replication_jobs() -> dict[str, Any]:
    engine = get_replication_engine()
    return {"jobs": engine.list_jobs(), "available": False, "reason": REPLICATION_OFF}


REPLICATION_OFF = (
    "Replication is turned off for now: it needs the ZFS or btrfs tools and a safe schedule, "
    "which are being fixed. Use an off-site backup to another NAS instead."
)


@router.post("/jobs", dependencies=[Depends(require_scope("storage:admin"))])
def create_replication_job(req: ReplicationJobCreateRequest) -> dict[str, Any]:
    raise HTTPException(status_code=409, detail=REPLICATION_OFF)  # REL-5 (D7): off until fixed
    engine = get_replication_engine()
    job = engine.create_job(req.model_dump())
    return {"status": "created", "job": job}


@router.get("/jobs/{job_id}", dependencies=[Depends(require_scope("storage:read"))])
def get_replication_job(job_id: str) -> dict[str, Any]:
    engine = get_replication_engine()
    job = engine.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Replication job not found")
    return {"job": job}


@router.delete("/jobs/{job_id}", dependencies=[Depends(require_scope("storage:admin"))])
def delete_replication_job(job_id: str) -> dict[str, Any]:
    engine = get_replication_engine()
    success = engine.delete_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Replication job not found")
    return {"status": "deleted", "job_id": job_id}


@router.post("/jobs/{job_id}/run", dependencies=[Depends(require_scope("storage:admin"))])
def run_replication_job(job_id: str) -> dict[str, Any]:
    raise HTTPException(status_code=409, detail=REPLICATION_OFF)  # REL-5 (D7): off until fixed
    engine = get_replication_engine()
    try:
        return engine.run_job_async(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/history", dependencies=[Depends(require_scope("storage:read"))])
def get_replication_history(page: PageParams = Depends()) -> dict[str, Any]:
    engine = get_replication_engine()
    rows = engine.get_history(limit=page.fetch)
    return {"history": page.slice(rows), **page.meta(len(rows))}
