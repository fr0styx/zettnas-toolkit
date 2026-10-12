"""
ZettNAS Toolkit - Replication API Router
Exposes endpoints for managing automated snapshot replication pipelines.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services.replication_engine import get_replication_engine

router = APIRouter(prefix="/api/storage/replication", tags=["Storage Replication"])


class ReplicationJobCreateRequest(BaseModel):
    name: str = Field(..., max_length=128)
    source_pool: str = Field(..., max_length=128)
    source_dataset: str = Field(..., max_length=256)
    target_type: str = Field(default="local", pattern=r"^(local|remote_ssh|remote_wireguard)$")
    target_host: Optional[str] = Field(default=None, max_length=256)
    target_port: int = Field(default=22, ge=1, le=65535)
    target_user: str = Field(default="root", max_length=64)
    target_pool: str = Field(..., max_length=128)
    target_dataset: str = Field(..., max_length=256)
    bandwidth_limit_kbps: Optional[int] = Field(default=None, ge=100)
    incremental: bool = Field(default=True)
    retention_count: int = Field(default=14, ge=1, le=365)
    schedule: str = Field(default="daily", pattern=r"^(manual|hourly|daily|weekly)$")


@router.get("/jobs", dependencies=[Depends(require_scope("storage:read"))])
def list_replication_jobs() -> Dict[str, Any]:
    engine = get_replication_engine()
    return {"jobs": engine.list_jobs()}


@router.post("/jobs", dependencies=[Depends(require_scope("storage:admin"))])
def create_replication_job(req: ReplicationJobCreateRequest) -> Dict[str, Any]:
    engine = get_replication_engine()
    job = engine.create_job(req.model_dump())
    return {"status": "created", "job": job}


@router.get("/jobs/{job_id}", dependencies=[Depends(require_scope("storage:read"))])
def get_replication_job(job_id: str) -> Dict[str, Any]:
    engine = get_replication_engine()
    job = engine.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Replication job not found")
    return {"job": job}


@router.delete("/jobs/{job_id}", dependencies=[Depends(require_scope("storage:admin"))])
def delete_replication_job(job_id: str) -> Dict[str, Any]:
    engine = get_replication_engine()
    success = engine.delete_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Replication job not found")
    return {"status": "deleted", "job_id": job_id}


@router.post("/jobs/{job_id}/run", dependencies=[Depends(require_scope("storage:admin"))])
def run_replication_job(job_id: str) -> Dict[str, Any]:
    engine = get_replication_engine()
    try:
        return engine.run_job_async(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", dependencies=[Depends(require_scope("storage:read"))])
def get_replication_history(limit: int = 50) -> Dict[str, Any]:
    engine = get_replication_engine()
    return {"history": engine.get_history(limit=limit)}
