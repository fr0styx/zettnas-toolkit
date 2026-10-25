"""Previous versions of a file in File Explorer (missing feature 7)."""

import mimetypes
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.fsutil import resolve_within
from backend.services import file_versions
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, check_user_path_access
from backend.state import add_event

router = APIRouter(tags=["Files"])
READ = Depends(require_scope("shares:read", "shares:user_write", "storage:read", "storage:write", "storage:admin"))
WRITE = Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))


class RestoreVersionIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    version: str = Field(min_length=1, max_length=512)
    overwrite: bool = False


def _inside(path: str) -> str:
    """The path within the folders File Explorer may show (the file itself may be gone)."""
    raw = str(path or "").strip()
    if not raw or "\x00" in raw:
        raise HTTPException(status_code=400, detail="Invalid path")
    parent = resolve_within(os.path.dirname(os.path.normpath(raw)), ALLOWED_BROWSE_ROOTS)
    if parent is None:
        raise HTTPException(status_code=403, detail="Path is outside allowed folders.")
    return os.path.join(parent, os.path.basename(os.path.normpath(raw)))


@router.get("/fs/versions", dependencies=[READ])
def get_versions(path: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    target = _inside(path)
    check_user_path_access(target, principal)
    return {"path": target, "versions": file_versions.list_versions(target)}


@router.get("/fs/versions/download", dependencies=[READ])
def download_version(path: str, version: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    target = _inside(path)
    check_user_path_access(target, principal)
    try:
        src = file_versions.version_path(target, version)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return FileResponse(
        src,
        filename=os.path.basename(target),
        media_type=mimetypes.guess_type(target)[0] or "application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
    )


@router.post("/fs/versions/restore", dependencies=[WRITE])
def restore_version(req: RestoreVersionIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    target = _inside(req.path)
    check_user_path_access(target, principal, write=True)
    try:
        dest = file_versions.restore_version(target, req.version, overwrite=req.overwrite)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    add_event("info", "File Explorer", f"Restored an earlier version of {os.path.basename(target)}")
    return {"status": "ok", "path": dest, "overwrote": req.overwrite}
