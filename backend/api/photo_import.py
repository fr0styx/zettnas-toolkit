"""Bringing photos home from a Google Takeout or an iCloud Photos export (NFEAT-3)."""

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.media import validate_media_path
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.services import icloud_photos, photo_import

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


# --- iCloud Photos with an Apple ID (NFEAT-3, D14) ------------------------------------------------------
class ICloudSignIn(BaseModel):
    apple_id: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=1024)


class ICloudCode(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)


class ICloudDownload(BaseModel):
    destination: str = Field(..., max_length=1024)


def _owner(principal: AuthenticatedPrincipal) -> str:
    return principal.username if principal and principal.username else "admin"


def _icloud_call(fn, *args):
    try:
        return fn(*args)
    except icloud_photos.SignInError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/media/icloud", dependencies=[Depends(require_scope("storage:read"))])
async def icloud_status(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """Whether this NAS user is signed in to iCloud, waits for a code, or is downloading."""
    return await asyncio.to_thread(icloud_photos.status, _owner(principal))


@router.post("/media/icloud/sign-in", dependencies=[Depends(require_scope("storage:write"))])
async def icloud_sign_in(
    req: ICloudSignIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Signs in with an Apple ID; the password is used for this sign-in only and never kept."""
    return await asyncio.to_thread(_icloud_call, icloud_photos.sign_in, _owner(principal), req.apple_id, req.password)


@router.post("/media/icloud/code", dependencies=[Depends(require_scope("storage:write"))])
async def icloud_code(
    req: ICloudCode, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """The code Apple sent to the person's devices."""
    return await asyncio.to_thread(_icloud_call, icloud_photos.verify, _owner(principal), req.code)


@router.post("/media/icloud/download", dependencies=[Depends(require_scope("storage:write"))])
async def icloud_download(
    req: ICloudDownload, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Downloads every photo not brought home before into the folder, as a job (see /api/jobs)."""
    dst = validate_media_path(req.destination, principal, must_exist=False)
    job_id = await asyncio.to_thread(_icloud_call, icloud_photos.start, _owner(principal), dst)
    return {"status": "started", "job_id": job_id, "destination": dst}


@router.delete("/media/icloud", dependencies=[Depends(require_scope("storage:write"))])
async def icloud_sign_out(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """Forgets the Apple session; the photos already downloaded stay."""
    return await asyncio.to_thread(icloud_photos.sign_out, _owner(principal))
