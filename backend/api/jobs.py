"""Jobs: one list of long-running work and its history, with cancel (ARCH-4)."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import AuthenticatedPrincipal, get_current_principal
from backend.services.jobs import job_manager

router = APIRouter(tags=["Jobs"])


def _everyone(principal: AuthenticatedPrincipal) -> bool:
    return bool(principal and (principal.has_scope("*") or principal.has_scope("system:manage")))


@router.get("/jobs")
def list_jobs(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Your running jobs and recent history; administrators see everyone's and system jobs."""
    return job_manager.list(owner=principal.username if principal else None, everyone=_everyone(principal))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    if not job_manager.cancel(job_id, owner=principal.username if principal else None, everyone=_everyone(principal)):
        raise HTTPException(status_code=404, detail="No running job with that id that you can cancel.")
    return {"status": "cancelling", "id": job_id}
