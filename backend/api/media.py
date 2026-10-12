"""
ZettNAS Toolkit - Smart Media API Router
Exposes hardware-gated AI photo indexing, acceleration status,
and FileBot-style automated media organizing and renaming.
"""

import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services.media_engine import get_media_engine
from backend.services.media_organizer import apply_organize, preview_organize

router = APIRouter(tags=["Smart Media Engine"])


class MediaScanRequest(BaseModel):
    media_path: Optional[str] = Field(default="/mnt/storage/media", max_length=512)


class MediaOrganizePreviewRequest(BaseModel):
    source_dir: str = Field(..., min_length=1)
    target_dir: Optional[str] = None
    media_type: str = "auto"  # "auto", "tv", "movie"


class MediaOrganizeApplyRequest(BaseModel):
    items: List[Dict[str, Any]] = Field(..., min_length=1)
    action: str = Field("move", pattern="^(move|copy)$")
    hardlink: bool = False


@router.get("/media/status", dependencies=[Depends(require_scope("system:read"))])
def get_media_status() -> Dict[str, Any]:
    engine = get_media_engine()
    return engine.get_status()


@router.post("/media/scan", dependencies=[Depends(require_scope("system:config"))])
def trigger_media_scan(req: MediaScanRequest) -> Dict[str, Any]:
    engine = get_media_engine()
    try:
        return engine.trigger_scan(media_path=req.media_path or "/mnt/storage/media")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/media/organize/preview",
    dependencies=[Depends(require_scope("storage:read", "storage:admin"))],
)
async def preview_media_organization(req: MediaOrganizePreviewRequest) -> Dict[str, Any]:
    """Analyzes source media files and calculates dry-run proposed Plex/Jellyfin renames."""
    try:
        return await asyncio.to_thread(
            preview_organize,
            req.source_dir,
            req.target_dir,
            req.media_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/media/organize/apply",
    dependencies=[Depends(require_scope("storage:write", "storage:admin"))],
)
async def apply_media_organization(req: MediaOrganizeApplyRequest) -> Dict[str, Any]:
    """Applies media renames and folder restructuring (move, copy, or hardlink)."""
    try:
        return await asyncio.to_thread(
            apply_organize,
            req.items,
            req.action,
            req.hardlink,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
