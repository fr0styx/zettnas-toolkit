"""The Recycle Bins: list, restore, empty (one per share and one per root, REL-15).

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import os
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.files.common import _contained, record_activity
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.confirmations import require_confirmation
from backend.services import recycle_bin
from backend.services.path_access import _is_files_admin, check_user_path_access, user_can_access_path
from backend.state import add_event

router = APIRouter()


class TrashRestoreRequest(BaseModel):
    item_id: str
    target_path: str | None = None


def _listing(principal: AuthenticatedPrincipal) -> dict:
    out, sleeping = [], []
    for b in recycle_bin.all_bins():
        if recycle_bin.asleep(b):
            sleeping.append({"root_path": os.path.dirname(b), "items": recycle_bin.known_items(b)})
            continue  # opening the bin never wakes a disk (NREL-16)
        try:
            recycle_bin.auto_empty(b)  # the bin is in use: it drops what it should no longer keep
        except Exception:
            logger.debug(f"[FS] auto-empty of {b} skipped", exc_info=True)
        root = os.path.dirname(b)
        for item in recycle_bin.items(b):
            orig = recycle_bin.original_path(b, item["name"])
            if not user_can_access_path(orig or item["path"], principal):
                continue
            name = os.path.basename(orig) if orig else item["name"]
            head = item["name"].split("_", 1)
            if not orig and len(head) == 2 and head[0].replace("-", "").isdigit():
                name = head[1]
            is_dir = os.path.isdir(item["path"]) and not os.path.islink(item["path"])
            out.append(
                {
                    "id": recycle_bin.item_id(b, item["name"]),
                    "name": name,
                    "original_path": orig,
                    "path": item["path"],
                    "is_dir": is_dir,
                    "size": 0 if is_dir else item["size"],
                    "deleted_at": int(item["deleted_at"]),
                    "root_path": root,
                }
            )
    out.sort(key=lambda x: x["deleted_at"], reverse=True)
    return {"items": out, "total": len(out), "asleep": sleeping}


def bin_listing(principal: AuthenticatedPrincipal) -> dict:
    """Every bin's items this person may open, newest first (the File Explorer's bin view)."""
    return _listing(principal)


@router.get("/fs/trash", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))])
async def fs_trash_list(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """What the Recycle Bins hold, newest first; each person sees what they may open."""
    return await asyncio.to_thread(_listing, principal)


def _restore(req: TrashRestoreRequest, principal: AuthenticatedPrincipal) -> dict:
    found = recycle_bin.locate(req.item_id.strip())
    if not found:
        raise FileNotFoundError(req.item_id)
    b, name = found
    source = os.path.join(b, "files", name)
    if not os.path.lexists(source):
        source = os.path.join(b, name)
    orig = recycle_bin.original_path(b, name)
    # the .trashinfo is in the share and anyone who can write there can change it: a restore only
    # goes back inside the share (or root) this bin belongs to (NSEC-8)
    scope = os.path.realpath(os.path.dirname(b))
    if orig and not (os.path.realpath(orig) == scope or os.path.realpath(orig).startswith(scope + os.sep)):
        orig = ""
    head = name.split("_", 1)
    orig_name = (
        os.path.basename(orig) if orig else (head[1] if len(head) == 2 and head[0].replace("-", "").isdigit() else name)
    )
    if not _is_files_admin(principal):
        if not orig:
            raise HTTPException(status_code=403, detail="You can't restore this item.")
        check_user_path_access(orig, principal, write=True)
    if req.target_path and os.path.isdir(req.target_path):
        dest = os.path.join(req.target_path, orig_name)
    elif orig:
        dest = orig
    else:
        dest = os.path.join(os.path.dirname(b), orig_name)  # deleted over SMB: back into its share
    dest_dir = _contained(os.path.dirname(dest), must_exist=False)
    dest = _contained(dest, must_exist=False)
    check_user_path_access(dest, principal, write=True)
    os.makedirs(dest_dir, exist_ok=True)
    if os.path.lexists(dest):
        dest = os.path.join(dest_dir, f"restored_{int(time.time())}_{orig_name}")
    shutil.move(source, dest)
    info = os.path.join(b, "info", f"{name}.trashinfo")
    if os.path.exists(info):
        os.remove(info)
    return {"status": "ok", "message": f"Restored {orig_name}", "path": dest}


@router.post(
    "/fs/trash/restore",
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_trash_restore(
    req: TrashRestoreRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Restores an item where it was (or into target_path), never over an existing one."""
    if not req.item_id.strip() or "/" in req.item_id:
        raise HTTPException(status_code=400, detail="Invalid item ID")
    try:
        res = await asyncio.to_thread(_restore, req, principal)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Item not found in Recycle Bin") from None
    except Exception as e:
        logger.error(f"[FS] Restore failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to restore item") from e
    add_event("success", "File Explorer", f"Restored {req.item_id} from Recycle Bin")
    await asyncio.to_thread(
        record_activity, "restore", str(res.get("path") or req.item_id), principal, detail="from the Recycle Bin"
    )
    return res


def _empty() -> dict:
    purged = 0
    for b in recycle_bin.all_bins():
        for item in recycle_bin.items(b):
            try:
                recycle_bin._remove(b, item)
                purged += 1
            except OSError as e:
                logger.warning(f"[FS] Could not purge {item['path']}: {e}")
        info = os.path.join(b, "info")
        for left in os.listdir(info) if os.path.isdir(info) else []:
            os.remove(os.path.join(info, left))  # notes of items that were already gone
        recycle_bin.auto_empty(b, force=True)  # records the bin as empty
    return {"status": "ok", "purged_count": purged}


@router.delete(
    "/fs/trash/empty",
    dependencies=[
        Depends(require_scope("shares:manage", "storage:admin")),
        Depends(require_confirmation("fs.trash.empty")),
    ],
)
async def fs_trash_empty(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Permanently deletes everything in every Recycle Bin."""
    res = await asyncio.to_thread(_empty)
    add_event("info", "File Explorer", f"Recycle Bin emptied ({res['purged_count']} items permanently deleted)")
    await asyncio.to_thread(record_activity, "empty_bin", "", principal, detail=f"{res['purged_count']} items")
    return res
