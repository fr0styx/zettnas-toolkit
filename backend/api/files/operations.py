"""Rename, delete, conflict checks, copy and move (now or as a task) and archives.

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import os
import shutil
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.files.common import _observe, _safe_fs_target
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.fsutil import resolve_within, root_for
from backend.rate_limit import rate_limit
from backend.services import recycle_bin
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, check_user_path_access
from backend.state import add_event

router = APIRouter()


class RenameRequest(BaseModel):
    path: str
    new_name: str


class DeleteRequest(BaseModel):
    path: str


class FsConflictCheckRequest(BaseModel):
    sources: list[str]
    destination_dir: str


class FsTransferRequest(BaseModel):
    sources: list[str]
    destination_dir: str
    action: str = Field("copy", pattern="^(copy|move)$")
    collision_policy: str = Field("merge", pattern="^(merge|overwrite|skip|keep_both)$")


@router.post(
    "/fs/rename",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_rename(req: RenameRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    check_user_path_access(req.path, principal, write=True)
    target_unresolved, parent_canonical, _ = _safe_fs_target(req.path)
    new_name = str(req.new_name or "").strip()
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid new name")

    is_admin = (
        principal.role_id in ("superadmin", "storage_admin")
        or principal.has_scope("shares:manage")
        or principal.has_scope("*")
    )
    if not is_admin and os.path.basename(parent_canonical.rstrip("/")) == "homes":
        raise HTTPException(status_code=403, detail="Cannot rename user home directory root.")

    dst = os.path.join(parent_canonical, new_name)
    check_user_path_access(dst, principal, write=True)
    if os.path.lexists(dst):
        raise HTTPException(status_code=400, detail="Destination already exists")
    _observe("rename", target_unresolved, principal, new_path=dst)
    try:
        await asyncio.to_thread(os.rename, target_unresolved, dst)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"[FS] Rename failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to rename item") from e


@router.post(
    "/fs/delete",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_delete(req: DeleteRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    check_user_path_access(req.path, principal, write=True)
    target_unresolved, parent_canonical, _ = _safe_fs_target(req.path)
    is_admin = (
        principal.role_id in ("superadmin", "storage_admin")
        or principal.has_scope("shares:manage")
        or principal.has_scope("*")
    )
    if not is_admin and os.path.basename(parent_canonical.rstrip("/")) == "homes":
        raise HTTPException(status_code=403, detail="Cannot delete user home directory root.")

    try:
        if "/.RecycleBin/" in target_unresolved.replace("\\", "/") or target_unresolved.endswith(".RecycleBin"):
            # Hard delete if already in recycle bin
            _observe("delete", target_unresolved, principal)  # only permanent deletes count (M4)
            if os.path.islink(target_unresolved):
                await asyncio.to_thread(os.unlink, target_unresolved)
            elif os.path.isdir(target_unresolved):
                await asyncio.to_thread(shutil.rmtree, target_unresolved)
            else:
                await asyncio.to_thread(os.remove, target_unresolved)
            return {"status": "ok", "message": "Item permanently deleted"}

        # Recycle Bin logic instead of hard delete
        real_root = root_for(target_unresolved, ALLOWED_BROWSE_ROOTS)
        if not real_root:
            real_root = ALLOWED_BROWSE_ROOTS[0]  # Fallback

        # its share's bin, or the root's for an item at the top (REL-15)
        recycle_dir = recycle_bin.bin_for(target_unresolved) or os.path.join(real_root, recycle_bin.BIN)
        base_name = os.path.basename(target_unresolved)
        dest_name = await asyncio.to_thread(recycle_bin.move_to_bin, target_unresolved, recycle_dir, target_unresolved)
        add_event("info", "File Explorer", f"Moved {base_name} to Recycle Bin")

        return {
            "status": "ok",
            "message": "Item moved to Recycle Bin",
            "trash_id": recycle_bin.item_id(recycle_dir, dest_name or ""),
        }
    except Exception as e:
        logger.error(f"[FS] Delete/Recycle failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to process delete request") from e


@router.post(
    "/fs/conflict-check",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_conflict_check(
    req: FsConflictCheckRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    from backend.services.fs_transfer import check_transfer_conflicts

    dest_canonical = resolve_within(req.destination_dir, ALLOWED_BROWSE_ROOTS)
    if dest_canonical is None:
        raise HTTPException(status_code=403, detail="Destination directory is outside allowed folders.")
    check_user_path_access(req.destination_dir, principal)

    for src in req.sources:
        src_canonical = resolve_within(src, ALLOWED_BROWSE_ROOTS)
        if src_canonical is None:
            raise HTTPException(status_code=403, detail=f"Source path {src} is outside allowed folders.")
        check_user_path_access(src, principal)

    return await asyncio.to_thread(check_transfer_conflicts, req.sources, dest_canonical)


@router.post(
    "/fs/transfer",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_transfer(req: FsTransferRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import execute_transfer

    dest_canonical = resolve_within(req.destination_dir, ALLOWED_BROWSE_ROOTS)
    if dest_canonical is None:
        raise HTTPException(status_code=403, detail="Destination directory is outside allowed folders.")
    check_user_path_access(req.destination_dir, principal, write=True)

    is_admin = (
        principal.role_id in ("superadmin", "storage_admin")
        or principal.has_scope("shares:manage")
        or principal.has_scope("*")
    )

    for src in req.sources:
        src_canonical = resolve_within(src, ALLOWED_BROWSE_ROOTS)
        if src_canonical is None:
            raise HTTPException(status_code=403, detail=f"Source path {src} is outside allowed folders.")
        check_user_path_access(src, principal, write=req.action == "move")

        if req.action == "move" and not is_admin and os.path.basename(src.rstrip("/")) == "homes":
            raise HTTPException(status_code=403, detail="Cannot move root homes directory.")

    res = await asyncio.to_thread(execute_transfer, req.sources, dest_canonical, req.action, req.collision_policy)
    add_event(
        "info",
        "File Explorer",
        f"Transferred {res.get('transferred', 0)} item(s) to {os.path.basename(dest_canonical)} ({req.action}, {req.collision_policy})",
    )
    return res


class FsAsyncTransferRequest(BaseModel):
    sources: list[str]
    destination_dir: str
    action: str = Field("copy", pattern="^(copy|move)$")
    collision_policy: str = Field("merge", pattern="^(merge|overwrite|skip|keep_both)$")
    # New names for the items, one per source (e.g. "Report copy.pdf" for a duplicate)
    target_names: list[str] | None = None
    kind: str = Field("", pattern="^(|copy|move|duplicate)$")


class ArchiveCreateRequest(BaseModel):
    sources: list[str]
    destination_dir: str
    archive_name: str
    format: str = Field("zip", pattern=r"^(zip|tar\.gz|tar)$")


class ArchiveExtractRequest(BaseModel):
    archive_path: str
    destination_dir: str


@router.post(
    "/fs/transfer/async",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_transfer_async(
    req: FsAsyncTransferRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    from backend.services.fs_transfer import transfer_manager

    dest_canonical = resolve_within(req.destination_dir, ALLOWED_BROWSE_ROOTS)
    if dest_canonical is None:
        raise HTTPException(status_code=403, detail="Destination directory is outside allowed folders.")
    check_user_path_access(req.destination_dir, principal, write=True)

    is_admin = (
        principal.role_id in ("superadmin", "storage_admin")
        or principal.has_scope("shares:manage")
        or principal.has_scope("*")
    )

    clean_sources = []
    for src in req.sources:
        src_canonical = resolve_within(src, ALLOWED_BROWSE_ROOTS)
        if src_canonical is None:
            raise HTTPException(status_code=403, detail=f"Source path {src} is outside allowed folders.")
        check_user_path_access(src, principal, write=req.action == "move")
        if req.action == "move" and not is_admin and os.path.basename(src.rstrip("/")) == "homes":
            raise HTTPException(status_code=403, detail="Cannot move root homes directory.")
        clean_sources.append(src_canonical)

    names = req.target_names
    if names is not None:
        if len(names) != len(req.sources):
            raise HTTPException(status_code=400, detail="target_names must give one name per source")
        for name in names:
            if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name or len(name) > 255:
                raise HTTPException(status_code=400, detail="Invalid target name")

    task = transfer_manager.submit_transfer(
        owner=principal.username or "",
        sources=clean_sources,
        destination_dir=dest_canonical,
        action=req.action,
        collision_policy=req.collision_policy,
        target_names=names,
        kind=req.kind,
    )
    add_event(
        "info",
        "File Explorer",
        f"Queued background {req.action} of {len(clean_sources)} item(s) to {os.path.basename(dest_canonical)}",
    )
    return {"status": "ok", "task_id": task.id, "task": task.to_dict()}


@router.post(
    "/fs/archive/create",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_archive_create(
    req: ArchiveCreateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    from backend.services.fs_transfer import transfer_manager

    dest_canonical = resolve_within(req.destination_dir, ALLOWED_BROWSE_ROOTS)
    if dest_canonical is None:
        raise HTTPException(status_code=403, detail="Destination directory is outside allowed folders.")
    check_user_path_access(req.destination_dir, principal, write=True)

    archive_name = os.path.basename(req.archive_name.strip())
    if not archive_name or "/" in archive_name or "\\" in archive_name or archive_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid archive name")

    clean_sources = []
    for src in req.sources:
        src_canonical = resolve_within(src, ALLOWED_BROWSE_ROOTS)
        if src_canonical is None:
            raise HTTPException(status_code=403, detail=f"Source path {src} is outside allowed folders.")
        check_user_path_access(src, principal)
        clean_sources.append(src_canonical)

    task = transfer_manager.submit_archive_create(
        owner=principal.username or "",
        sources=clean_sources,
        destination_dir=dest_canonical,
        archive_name=archive_name,
        fmt=req.format,
    )
    add_event(
        "info",
        "File Explorer",
        f"Queued archive creation {archive_name} from {len(clean_sources)} item(s)",
    )
    return {"status": "ok", "task_id": task.id, "task": task.to_dict()}


@router.post(
    "/fs/archive/extract",
    dependencies=[
        Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin")),
        Depends(rate_limit("fs.extract", 10, 60)),
    ],
)
async def fs_archive_extract(
    req: ArchiveExtractRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    from backend.services.fs_transfer import transfer_manager

    dest_canonical = resolve_within(req.destination_dir, ALLOWED_BROWSE_ROOTS)
    if dest_canonical is None:
        raise HTTPException(status_code=403, detail="Destination directory is outside allowed folders.")
    check_user_path_access(req.destination_dir, principal, write=True)

    arc_canonical = resolve_within(req.archive_path, ALLOWED_BROWSE_ROOTS)
    if arc_canonical is None or not os.path.isfile(arc_canonical):
        raise HTTPException(status_code=404, detail="Archive file not found or outside allowed folders.")
    check_user_path_access(req.archive_path, principal)

    task = transfer_manager.submit_archive_extract(
        owner=principal.username or "",
        archive_path=arc_canonical,
        destination_dir=dest_canonical,
    )
    add_event(
        "info",
        "File Explorer",
        f"Queued extraction of {os.path.basename(arc_canonical)} to {os.path.basename(dest_canonical)}",
    )
    return {"status": "ok", "task_id": task.id, "task": task.to_dict()}
