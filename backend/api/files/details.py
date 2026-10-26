"""Checksums, folder sizes and permissions.

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import hashlib
import os
import stat
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.files.common import _contained
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.fsutil import prune_protected
from backend.services.path_access import check_user_path_access

router = APIRouter()


class ChecksumRequest(BaseModel):
    path: str
    algorithm: str = Field("sha256", pattern="^(sha256|sha1|md5)$")


class FolderSizeRequest(BaseModel):
    path: str
    force_wake: bool = False


class PermissionsUpdateRequest(BaseModel):
    path: str
    mode_octal: str | None = None
    owner: str | None = None
    group: str | None = None
    recursive: bool = False


_FOLDER_SIZE_CACHE: dict[str, tuple[float, float, int, int, int]] = {}


@router.post(
    "/fs/checksum",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
async def fs_checksum(
    req: ChecksumRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    check_user_path_access(req.path, principal)
    target = _contained(req.path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot compute checksum of a directory")

    algo = req.algorithm.lower()
    h = hashlib.new(algo)
    file_size = os.path.getsize(target)

    def _calc_hash():
        with open(target, "rb") as f:
            while chunk := f.read(256 * 1024):
                h.update(chunk)
        return h.hexdigest()

    digest = await asyncio.to_thread(_calc_hash)
    return {
        "status": "ok",
        "path": req.path,
        "algorithm": algo,
        "checksum": digest,
        "size": file_size,
    }


@router.post(
    "/fs/folder-size",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
async def fs_folder_size(
    req: FolderSizeRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    check_user_path_access(req.path, principal)
    target = _contained(req.path, must_exist=True)
    if not os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Path is not a directory")

    if not req.force_wake:
        is_standby = False
        try:
            from backend.services.rag_standby import is_backing_disk_in_standby

            is_standby = is_backing_disk_in_standby(target)
        except Exception:
            logger.debug("backend.api.fs.fs_folder_size: ignored error", exc_info=True)
        if is_standby:
            return {
                "status": "standby",
                "path": req.path,
                "size": None,
                "files_count": None,
                "dirs_count": None,
                "is_standby": True,
                "cached": False,
                "message": "Drive is in standby mode. Size calculation deferred to prevent spinup.",
            }

    now = time.time()
    try:
        cur_mtime = os.path.getmtime(target)
    except OSError:
        cur_mtime = 0.0

    cached = _FOLDER_SIZE_CACHE.get(target)
    if cached and (now - cached[0]) < 300.0 and cached[1] == cur_mtime:
        return {
            "status": "ok",
            "path": req.path,
            "size": cached[2],
            "files_count": cached[3],
            "dirs_count": cached[4],
            "is_standby": False,
            "cached": True,
        }

    def _compute_size():
        total_sz = 0
        f_count = 0
        d_count = 0
        for root, dirs, files in os.walk(target):
            prune_protected(root, dirs)
            d_count += len(dirs)
            for f in files:
                f_path = os.path.join(root, f)
                try:
                    if not os.path.islink(f_path):
                        total_sz += os.path.getsize(f_path)
                    f_count += 1
                except OSError:
                    pass
        return total_sz, f_count, d_count

    total_sz, f_count, d_count = await asyncio.to_thread(_compute_size)
    _FOLDER_SIZE_CACHE[target] = (now, cur_mtime, total_sz, f_count, d_count)

    return {
        "status": "ok",
        "path": req.path,
        "size": total_sz,
        "files_count": f_count,
        "dirs_count": d_count,
        "is_standby": False,
        "cached": False,
    }


@router.get(
    "/fs/permissions",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
def fs_get_permissions(
    path: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    check_user_path_access(path, principal, allow_list=True)
    target = _contained(path, must_exist=True)
    st = os.stat(target, follow_symlinks=False)
    mode_int = st.st_mode
    octal_str = f"{stat.S_IMODE(mode_int):04o}"
    human_mode = stat.filemode(mode_int)

    owner_name = str(st.st_uid)
    group_name = str(st.st_gid)
    try:
        import pwd

        owner_name = pwd.getpwuid(st.st_uid).pw_name
    except Exception:
        logger.debug("backend.api.fs.fs_get_permissions: ignored error", exc_info=True)
    try:
        import grp

        group_name = grp.getgrgid(st.st_gid).gr_name
    except Exception:
        logger.debug("backend.api.fs.fs_get_permissions: ignored error", exc_info=True)

    return {
        "status": "ok",
        "path": path,
        "mode_octal": octal_str,
        "mode_human": human_mode,
        "owner": owner_name,
        "group": group_name,
        "uid": st.st_uid,
        "gid": st.st_gid,
        "is_dir": stat.S_ISDIR(mode_int),
    }


@router.put(
    "/fs/permissions",
    dependencies=[Depends(require_scope("shares:manage", "storage:admin"))],
)
async def fs_update_permissions(
    req: PermissionsUpdateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    check_user_path_access(req.path, principal, write=True)
    target = _contained(req.path, must_exist=True)

    # Guard against modifying sensitive system directories and appdata root
    normalized = os.path.abspath(target)
    protected_system_prefixes = [
        "/boot",
        "/etc",
        "/sys",
        "/proc",
        "/dev",
        "/usr",
        "/bin",
        "/sbin",
        "/var",
        "/appdata",
        "/mnt/user/appdata",
    ]
    if any(normalized == p or normalized.startswith(p + "/") for p in protected_system_prefixes):
        raise HTTPException(
            status_code=403,
            detail="Modifying permissions on protected system roots or /appdata is forbidden",
        )

    mode_int = None
    if req.mode_octal:
        try:
            mode_int = int(req.mode_octal, 8)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid octal mode string") from None
        if not 0 <= mode_int <= 0o7777:
            raise HTTPException(status_code=400, detail="A mode has at most four octal digits (0000-7777)")

    uid = -1
    gid = -1
    if req.owner:
        try:
            import pwd

            uid = pwd.getpwnam(req.owner).pw_uid if not req.owner.isdigit() else int(req.owner)
        except Exception:
            raise HTTPException(status_code=400, detail=f"User {req.owner} not found") from None
    if req.group:
        try:
            import grp

            gid = grp.getgrnam(req.group).gr_gid if not req.group.isdigit() else int(req.group)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Group {req.group} not found") from None

    def _apply_permissions():
        paths_to_update = [target]
        if req.recursive and os.path.isdir(target):
            for root, dirs, files in os.walk(target):
                prune_protected(root, dirs)
                for d in dirs:
                    paths_to_update.append(os.path.join(root, d))
                for f in files:
                    paths_to_update.append(os.path.join(root, f))
        for p in paths_to_update:
            try:
                if mode_int is not None:
                    os.chmod(p, mode_int)
                if uid != -1 or gid != -1:
                    os.chown(p, uid, gid)
            except OSError as e:
                logger.warning(f"[FS Permissions] Could not chmod/chown {p}: {e}")

    await asyncio.to_thread(_apply_permissions)
    return {"status": "ok", "path": req.path, "recursive": req.recursive}
