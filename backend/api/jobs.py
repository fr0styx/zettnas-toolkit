"""Jobs: one list of long-running work and its history, with cancel (ARCH-4)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import AuthenticatedPrincipal, get_current_principal
from backend.services.jobs import job_manager

router = APIRouter(tags=["Jobs"])


class JobOut(BaseModel):
    id: str
    kind: str
    title: str
    status: str
    owner: str | None = None
    percent: float | None = None
    detail: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    can_cancel: bool = False


class JobList(BaseModel):
    active: list[JobOut]
    history: list[JobOut]


class JobCancelled(BaseModel):
    status: str
    id: str


def _everyone(principal: AuthenticatedPrincipal) -> bool:
    return bool(principal and (principal.has_scope("*") or principal.has_scope("system:manage")))


@router.get("/jobs", response_model=JobList)
def list_jobs(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Your running jobs and recent history; administrators see everyone's and system jobs."""
    return job_manager.list(owner=principal.username if principal else None, everyone=_everyone(principal))


@router.post("/jobs/{job_id}/cancel", response_model=JobCancelled)
def cancel_job(job_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    if not job_manager.cancel(job_id, owner=principal.username if principal else None, everyone=_everyone(principal)):
        raise HTTPException(status_code=404, detail="No running job with that id that you can cancel.")
    return {"status": "cancelling", "id": job_id}
