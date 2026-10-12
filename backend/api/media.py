"""
ZettNAS Toolkit - Smart Media API Router
Exposes hardware-gated AI photo indexing and acceleration status.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services.media_engine import get_media_engine

router = APIRouter(prefix="/api/media", tags=["Smart Media Engine"])


class MediaScanRequest(BaseModel):
    media_path: Optional[str] = Field(default="/mnt/storage/media", max_length=512)


@router.get("/status", dependencies=[Depends(require_scope("system:read"))])
def get_media_status() -> Dict[str, Any]:
    engine = get_media_engine()
    return engine.get_status()


@router.post("/scan", dependencies=[Depends(require_scope("system:config"))])
def trigger_media_scan(req: MediaScanRequest) -> Dict[str, Any]:
    engine = get_media_engine()
    try:
        return engine.trigger_scan(media_path=req.media_path or "/mnt/storage/media")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
