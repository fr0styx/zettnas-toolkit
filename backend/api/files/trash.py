"""The Recycle Bin: list, restore, empty.

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import os
import shutil
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.files.common import _contained
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.confirmations import require_confirmation
from backend.services.path_access import (
    ALLOWED_BROWSE_ROOTS,
    _is_files_admin,
    check_user_path_access,
    user_can_access_path,
)
from backend.state import add_event

router = APIRouter()


class TrashRestoreRequest(BaseModel):
    item_id: str
    target_path: str | None = None


@router.get("/fs/trash", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))])
async def fs_trash_list(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Lists deleted items currently residing in the Recycle Bin with FreeDesktop .trashinfo metadata support."""

    def _scan_trash():
        items = []
        for root_dir in ALLOWED_BROWSE_ROOTS:
            recycle_dir = os.path.join(root_dir, ".RecycleBin")
            if not os.path.isdir(recycle_dir):
                continue

            files_dir = os.path.join(recycle_dir, "files")
            info_dir = os.path.join(recycle_dir, "info")
            scan_dirs = [(files_dir, True)] if os.path.isdir(files_dir) else []
            scan_dirs.append((recycle_dir, False))

            seen_ids = set()
            for s_dir, is_fd_dir in scan_dirs:
                try:
                    with os.scandir(s_dir) as it:
                        for entry in it:
                            if entry.name.startswith(".") or entry.name in ("files", "info"):
                                continue
                            if entry.name in seen_ids:
                                continue
                            seen_ids.add(entry.name)

                            orig_name = entry.name
                            deleted_ts = 0
                            orig_path = ""

                            if is_fd_dir:
                                tinfo = os.path.join(info_dir, f"{entry.name}.trashinfo")
                                if os.path.exists(tinfo):
                                    try:
                                        with open(tinfo, encoding="utf-8") as f_meta:
                                            for line in f_meta:
                                                if line.startswith("Path="):
                                                    orig_path = line.split("=", 1)[1].strip()
                                                    orig_name = os.path.basename(orig_path)
                                                elif line.startswith("DeletionDate="):
                                                    date_str = line.split("=", 1)[1].strip()
                                                    try:
                                                        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                                                        deleted_ts = int(dt.timestamp())
                                                    except Exception:
                                                        logger.debug(
                                                            "backend.api.fs.fs_trash_list._scan_trash: ignored error",
                                                            exc_info=True,
                                                        )
                                    except Exception:
                                        logger.debug(
                                            "backend.api.fs.fs_trash_list._scan_trash: ignored error", exc_info=True
                                        )

                            if not orig_path:
                                parts = entry.name.split("_", 1)
                                if len(parts) == 2 and parts[0].isdigit():
                                    deleted_ts = int(parts[0])
                                    orig_name = parts[1]

                            if orig_path and not user_can_access_path(orig_path, principal):
                                continue
                            if not orig_path and not user_can_access_path(entry.path, principal):
                                continue

                            try:
                                st = entry.stat(follow_symlinks=False)
                                is_dir = entry.is_dir(follow_symlinks=False)
                                items.append(
                                    {
                                        "id": entry.name,
                                        "name": orig_name,
                                        "original_path": orig_path,
                                        "path": entry.path,
                                        "is_dir": is_dir,
                                        "size": st.st_size if not is_dir else 0,
                                        "deleted_at": deleted_ts or int(st.st_mtime),
                                        "root_path": root_dir,
                                    }
                                )
                            except (OSError, PermissionError):
                                pass
                except (OSError, PermissionError):
                    pass
        items.sort(key=lambda x: x["deleted_at"], reverse=True)
        return {"items": items, "total": len(items)}

    return await asyncio.to_thread(_scan_trash)


@router.post(
    "/fs/trash/restore",
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_trash_restore(
    req: TrashRestoreRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Restores an item from the Recycle Bin, reconstructing parent directories as needed."""
    item_id = os.path.basename(req.item_id.strip())
    if not item_id or item_id in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid item ID")

    def _do_restore():
        for root_dir in ALLOWED_BROWSE_ROOTS:
            recycle_dir = os.path.join(root_dir, ".RecycleBin")
            fd_source = os.path.join(recycle_dir, "files", item_id)
            legacy_source = os.path.join(recycle_dir, item_id)
            source_path = (
                fd_source if os.path.lexists(fd_source) else (legacy_source if os.path.lexists(legacy_source) else None)
            )
            if source_path:
                info_file = os.path.join(recycle_dir, "info", f"{item_id}.trashinfo")
                orig_path = ""
                orig_name = item_id
                if os.path.exists(info_file):
                    try:
                        with open(info_file, encoding="utf-8") as f_meta:
                            for line in f_meta:
                                if line.startswith("Path="):
                                    orig_path = line.split("=", 1)[1].strip()
                                    orig_name = os.path.basename(orig_path)
                    except Exception:
                        logger.debug("backend.api.fs.fs_trash_restore._do_restore: ignored error", exc_info=True)
                if not orig_path:
                    parts = item_id.split("_", 1)
                    orig_name = parts[1] if (len(parts) == 2 and parts[0].replace("-", "").isdigit()) else item_id

                if not _is_files_admin(principal):
                    if not orig_path:
                        raise HTTPException(status_code=403, detail="You can't restore this item.")
                    check_user_path_access(orig_path, principal, write=True)
                if req.target_path and os.path.isdir(req.target_path):
                    dest_dir = req.target_path
                    dest_path = os.path.join(dest_dir, orig_name)
                elif orig_path:
                    dest_path = orig_path
                    dest_dir = os.path.dirname(orig_path)
                else:
                    dest_dir = root_dir
                    dest_path = os.path.join(dest_dir, orig_name)

                dest_dir = _contained(dest_dir, must_exist=False)
                dest_path = _contained(dest_path, must_exist=False)
                check_user_path_access(dest_path, principal, write=True)

                os.makedirs(dest_dir, exist_ok=True)

                if os.path.lexists(dest_path):
                    ts = int(time.time())
                    dest_path = os.path.join(dest_dir, f"restored_{ts}_{orig_name}")

                shutil.move(source_path, dest_path)
                if os.path.exists(info_file):
                    try:
                        os.remove(info_file)
                    except OSError:
                        pass
                return {"status": "ok", "message": f"Restored {orig_name}", "path": dest_path}
        raise FileNotFoundError(f"Trash item '{item_id}' not found")

    try:
        res = await asyncio.to_thread(_do_restore)
        add_event("success", "File Explorer", f"Restored {item_id} from Recycle Bin")
        return res
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Item not found in Recycle Bin") from None
    except Exception as e:
        logger.error(f"[FS] Restore failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to restore item") from e


@router.delete(
    "/fs/trash/empty",
    dependencies=[
        Depends(require_scope("shares:manage", "storage:admin")),
        Depends(require_confirmation("fs.trash.empty")),
    ],
)
async def fs_trash_empty(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Permanently purges all items currently in the Recycle Bin across all browse roots."""

    def _do_empty():
        purged = 0
        for root_dir in ALLOWED_BROWSE_ROOTS:
            recycle_dir = os.path.join(root_dir, ".RecycleBin")
            if os.path.isdir(recycle_dir):
                for sub in ("files", "info"):
                    sub_p = os.path.join(recycle_dir, sub)
                    if os.path.isdir(sub_p):
                        for entry in os.listdir(sub_p):
                            p = os.path.join(sub_p, entry)
                            try:
                                if os.path.islink(p):
                                    os.unlink(p)
                                elif os.path.isdir(p):
                                    shutil.rmtree(p)
                                else:
                                    os.remove(p)
                                purged += 1
                            except Exception as e:
                                logger.warning(f"[FS] Could not purge {p}: {e}")
                for entry in os.listdir(recycle_dir):
                    if entry in ("files", "info"):
                        continue
                    p = os.path.join(recycle_dir, entry)
                    try:
                        if os.path.islink(p):
                            os.unlink(p)
                        elif os.path.isdir(p):
                            shutil.rmtree(p)
                        else:
                            os.remove(p)
                        purged += 1
                    except Exception as e:
                        logger.warning(f"[FS] Could not purge {p}: {e}")
        return {"status": "ok", "purged_count": purged}

    res = await asyncio.to_thread(_do_empty)
    add_event("info", "File Explorer", f"Recycle Bin emptied ({res['purged_count']} items permanently deleted)")
    return res
