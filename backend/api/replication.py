"""
ZettNAS Toolkit - Replication API Router
Exposes endpoints for managing automated snapshot replication pipelines.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.paging import PageParams
from backend.services.replication_engine import availability, get_replication_engine, validate

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
    hour: int = Field(default=1, ge=0, le=23)


@router.get("/jobs", dependencies=[Depends(require_scope("storage:read"))])
def list_replication_jobs() -> dict[str, Any]:
    engine = get_replication_engine()
    ok, reason = availability()
    return {"jobs": engine.list_jobs(), "available": ok, "reason": reason}


def _available() -> None:
    """REL-5: replication runs where ZettNAS manages the pools and has their tools."""
    ok, reason = availability()
    if not ok:
        raise HTTPException(status_code=409, detail=reason)


@router.post("/jobs", dependencies=[Depends(require_scope("storage:admin"))])
def create_replication_job(req: ReplicationJobCreateRequest) -> dict[str, Any]:
    _available()
    data = req.model_dump()
    try:
        validate(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    job = get_replication_engine().create_job(data)
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
    _available()
    try:
        return get_replication_engine().run_job_async(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/history", dependencies=[Depends(require_scope("storage:read"))])
def get_replication_history(page: PageParams = Depends()) -> dict[str, Any]:
    engine = get_replication_engine()
    rows = engine.get_history(limit=page.fetch)
    return {"history": page.slice(rows), **page.meta(len(rows))}
