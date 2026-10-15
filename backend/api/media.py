"""
ZettNAS Toolkit - Smart Media API Router
Exposes hardware-gated AI photo indexing, acceleration status,
and FileBot-style automated media organizing and renaming.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import ALLOWED_BROWSE_ROOTS
from backend.fsutil import resolve_within
from backend.api.system import check_user_path_access
from backend.services.media_engine import get_media_engine
from backend.services.media_organizer import apply_organize, preview_organize

router = APIRouter(tags=["Smart Media Engine"])


def _validate_media_path(path: str, principal: Optional[AuthenticatedPrincipal], must_exist: bool = True) -> str:
    path = str(path or "").strip()
    if not path or "\x00" in path:
        raise HTTPException(status_code=400, detail="Invalid path")
    real = resolve_within(path, ALLOWED_BROWSE_ROOTS)
    if real is None:
        raise HTTPException(status_code=403, detail="Path is outside the allowed storage folders.")
    if must_exist and not os.path.exists(real):
        raise HTTPException(status_code=404, detail="Path does not exist.")
    check_user_path_access(real, principal)
    return real


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
def trigger_media_scan(
    req: MediaScanRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> Dict[str, Any]:
    engine = get_media_engine()
    validated_path = _validate_media_path(req.media_path or "/mnt/storage/media", principal, must_exist=True)
    try:
        return engine.trigger_scan(media_path=validated_path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/media/organize/preview",
    dependencies=[Depends(require_scope("storage:read", "storage:admin"))],
)
async def preview_media_organization(
    req: MediaOrganizePreviewRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> Dict[str, Any]:
    """Analyzes source media files and calculates dry-run proposed Plex/Jellyfin renames."""
    src = _validate_media_path(req.source_dir, principal, must_exist=True)
    dst = _validate_media_path(req.target_dir, principal, must_exist=False) if req.target_dir else None
    try:
        return await asyncio.to_thread(
            preview_organize,
            src,
            dst,
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
async def apply_media_organization(
    req: MediaOrganizeApplyRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> Dict[str, Any]:
    """Applies media renames and folder restructuring (move, copy, or hardlink)."""
    validated_items = []
    for it in req.items:
        clean_it = dict(it)
        src = clean_it.get("source_path") or clean_it.get("source")
        dst = clean_it.get("destination_path") or clean_it.get("target")
        if not src or not dst:
            raise HTTPException(status_code=400, detail="Missing source or destination path in organize item")
        clean_it["source_path"] = _validate_media_path(src, principal, must_exist=True)
        clean_it["destination_path"] = _validate_media_path(dst, principal, must_exist=False)
        validated_items.append(clean_it)

    try:
        return await asyncio.to_thread(
            apply_organize,
            validated_items,
            req.action,
            req.hardlink,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
