"""The file activity log, for administrators (FEAT-12)."""

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth import require_scope
from backend.services import file_activity

router = APIRouter()


@router.get("/fs/activity", dependencies=[Depends(require_scope("audit:read"))])
def fs_activity(
    q: str = Query("", max_length=200),
    user: str = Query("", max_length=64),
    action: str = Query("", max_length=32),
    days: int = Query(file_activity.RETENTION_DAYS, ge=1, le=file_activity.RETENTION_DAYS),
    limit: int = Query(100, ge=1, le=file_activity.MAX_LIMIT),
    before: int | None = Query(None, ge=1),
):
    """Who deleted, moved, renamed, restored or uploaded what, newest first (90 days are kept)."""
    try:
        items = file_activity.search(q=q, user=user, action=action, days=days, limit=limit, before_id=before)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return {
        "items": items,
        "actions": list(file_activity.ACTIONS),
        "retention_days": file_activity.RETENTION_DAYS,
        "next_before": items[-1]["id"] if len(items) == limit else None,
    }
