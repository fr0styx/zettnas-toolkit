"""Protection jobs (B12a, REL-12): backups, snapshots and scrubs with their state, and the
monthly scrub switch per pool."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise
from backend.services import protection_jobs

router = APIRouter(tags=["backup"])


class ScrubSwitch(BaseModel):
    enabled: bool


@router.get("/protection/jobs", dependencies=[Depends(require_scope("backup:read", "storage:read", "system:view"))])
async def list_protection_jobs() -> dict[str, Any]:
    return {"jobs": await asyncio.to_thread(protection_jobs.jobs)}


@router.put("/protection/scrub/{pool_id}", dependencies=[Depends(require_scope("storage:admin"))])
async def set_monthly_scrub(
    pool_id: str,
    req: ScrubSwitch,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    from backend.hardware.pal_storage import get_storage_platform

    pools = {p.id: p for p in await asyncio.to_thread(get_storage_platform().list_pools)}
    pool = pools.get(pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="No such pool")
    if req.enabled and protection_jobs.needs_wake_confirmation(pool):
        # a scrub reads every disk: spinning disks wake up for it once a month
        confirm_or_raise(request, principal, "pool.scrub_schedule", pool_id)
    return {"pool": pool_id, **protection_jobs.set_scrub(pool_id, req.enabled)}
