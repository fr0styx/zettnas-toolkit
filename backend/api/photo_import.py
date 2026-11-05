"""Bringing photos home from a Google Takeout or an iCloud Photos export (NFEAT-3)."""

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.media import validate_media_path
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.services import photo_import

router = APIRouter(tags=["Media"])

LABELS = {"google": "Google Photos", "icloud": "iCloud", "folder": "a folder"}


class PhotoImportStart(BaseModel):
    source: str = Field(..., max_length=1024)
    destination: str = Field(..., max_length=1024)


@router.get("/media/photo-import/inspect", dependencies=[Depends(require_scope("storage:read"))])
async def inspect_export(
    path: str = Query(..., max_length=1024), principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Which export this is (Google Takeout, iCloud or plain folder), how many photos and videos it
    holds and where they would go. Reads only zip directories and file names."""
    src = validate_media_path(path, principal, must_exist=True)
    try:
        info = await asyncio.to_thread(photo_import.inspect, src)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    info["destination"] = photo_import.default_destination(src, info["kind"])
    return info


@router.post("/media/photo-import", dependencies=[Depends(require_scope("storage:write"))])
async def start_import(
    req: PhotoImportStart, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Starts the import as a job (see /api/jobs); the export is only read."""
    src = validate_media_path(req.source, principal, must_exist=True)
    dst = validate_media_path(req.destination, principal, must_exist=False)
    if dst == src or dst.startswith(src.rstrip("/") + "/"):
        raise HTTPException(status_code=400, detail="Choose a destination outside the export.")
    try:
        info = await asyncio.to_thread(photo_import.inspect, src)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not info["photos"] and not info["videos"]:
        raise HTTPException(status_code=400, detail="There are no photos or videos in it.")
    owner = principal.username if principal else None
    job_id = await asyncio.to_thread(
        photo_import.start, src, dst, owner, LABELS.get(info["kind"], os.path.basename(src))
    )
    return {"status": "started", "job_id": job_id, **info, "destination": dst}
