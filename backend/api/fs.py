# ZettNAS Toolkit - File System & Storage Browsing API Router
import asyncio
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import UTC, datetime, timezone
from typing import Any, Optional

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

import backend.config as config
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import POOL_PATH, logger
from backend.confirmations import require_confirmation
from backend.passwords import hash_password, verify_password
from backend.rate_limit import rate_limit

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    logger.debug("backend.api.fs.<module>: ignored error", exc_info=True)


from backend.fsutil import (
    atomic_write_json,
    is_protected,
    json_locked,
    prune_protected,
    read_json,
    resolve_within,
    root_for,
)
from backend.logging_config import sanitize_string
from backend.models.schemas import MkdirRequest
from backend.services import media_info, thumbs, video_compat
from backend.services.path_access import (  # noqa: E402,F401  (moved to the service layer, ARCH-2)
    ALLOWED_BROWSE_ROOTS,
    _AllowedBrowseRootsProxy,
    _indexed_readable,
    _is_files_admin,
    check_user_path_access,
    indexed_path_checker,
    user_can_access_path,
)
from backend.state import add_event

router = APIRouter(tags=["File System & Shares"])


def _contained(path, must_exist=True):
    """Resolve `path` inside an allowed browse root or raise 403/404."""
    path = str(path or "").strip()
    if not path or "\x00" in path:
        raise HTTPException(status_code=400, detail="Invalid path")
    real = resolve_within(path, ALLOWED_BROWSE_ROOTS)
    if real is None:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders.")
    if must_exist and not os.path.exists(real):
        if os.path.basename(real.rstrip("/")) == ".RecycleBin":
            try:
                os.makedirs(real, exist_ok=True)
                return real
            except OSError:
                pass
        raise HTTPException(status_code=404, detail="Path does not exist.")
    return real


def _scan_remote_dir_isolated(real: str, dirs_only: bool) -> list[dict[str, Any]]:
    """Scans a remote FUSE directory in an isolated subprocess with a 2.5s SIGKILL timeout.
    Prevents stalled Rclone/WebDAV mounts from hanging the Python asyncio threadpool or workers.
    """
    cmd = [
        sys.executable,
        "-c",
        (
            "import os, sys, json\n"
            "path = sys.argv[1]\n"
            "dirs_only = sys.argv[2] == '1'\n"
            "out = []\n"
            "try:\n"
            "    with os.scandir(path) as it:\n"
            "        for e in it:\n"
            "            try:\n"
            "                is_dir = e.is_dir(follow_symlinks=False)\n"
            "                if dirs_only and not is_dir:\n"
            "                    continue\n"
            "                sz = e.stat(follow_symlinks=False).st_size if not is_dir else 0\n"
            "                out.append({'name': e.name, 'path': e.path, 'is_dir': is_dir, 'size': sz})\n"
            "            except (OSError, PermissionError):\n"
            "                pass\n"
            "except Exception as err:\n"
            "    sys.stderr.write(str(err))\n"
            "    sys.exit(2)\n"
            "print(json.dumps(out))\n"
        ),
        real,
        "1" if dirs_only else "0",
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = proc.communicate(timeout=2.5)
        if proc.returncode == 0 and stdout:
            return json.loads(stdout.strip())
        elif proc.returncode == 2:
            detail = stderr.strip() if stderr else "Unable to read remote directory."
            raise HTTPException(status_code=500, detail=f"Remote directory error: {detail}")
        return []
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        logger.warning(f"[FUSE] Remote scandir timed out after 2.5s for {real}")
        raise HTTPException(
            status_code=504,
            detail={
                "code": "FUSE_TIMEOUT",
                "path": real,
                "message": "Remote storage mount timed out after 2.5s. Storage endpoint may be unreachable.",
            },
        ) from None


def _handle_browse_logic(path: str, dirs_only: bool, principal: AuthenticatedPrincipal | None = None):
    result = _handle_browse_logic_unfiltered(path, dirs_only, principal)
    if principal is None or _is_files_admin(principal) or not isinstance(result, dict):
        return result
    from backend.services.share_access import level_for

    username = principal.username or ""
    result["dirs"] = [
        e for e in result.get("dirs", []) if e.get("name") == ".." or level_for(username, e.get("path", "")) != "none"
    ]
    return result


def _handle_browse_logic_unfiltered(path: str, dirs_only: bool, principal: AuthenticatedPrincipal | None = None):
    real = _contained(path or ALLOWED_BROWSE_ROOTS[0])
    if not os.path.isdir(real):
        raise HTTPException(status_code=400, detail="Not a directory.")
    out = []
    root = root_for(real, ALLOWED_BROWSE_ROOTS)
    if root and real != root:
        parent_dir = os.path.dirname(real)
        parent_mtime = 0.0
        try:
            parent_mtime = os.path.getmtime(parent_dir)
        except OSError:
            pass
        out.append(
            {
                "name": "..",
                "path": parent_dir,
                "is_dir": True,
                "size": 0,
                "mtime": parent_mtime,
                "mode": "0755",
                "is_symlink": False,
                "ext": "",
            }
        )

    is_admin = not principal or (
        principal.role_id in ("superadmin", "storage_admin")
        or principal.has_scope("shares:manage")
        or principal.has_scope("*")
    )
    is_homes_dir = os.path.basename(real.rstrip("/")) == "homes"

    # FUSE Isolation for remote mounts under /mnt/remotes/*
    if real.startswith("/mnt/remotes/") and real != "/mnt/remotes":
        remote_entries = _scan_remote_dir_isolated(real, dirs_only)
        remote_entries.sort(key=lambda x: x["name"])
        for item in remote_entries:
            if is_protected(str(item.get("path") or "")):
                continue
            if is_homes_dir and not is_admin and principal:
                if item["name"].lower() != (principal.username or "").lower():
                    continue
            if "mtime" not in item:
                item["mtime"] = 0.0
            if "mode" not in item:
                item["mode"] = "0755" if item.get("is_dir") else "0644"
            if "is_symlink" not in item:
                item["is_symlink"] = False
            if "ext" not in item:
                item["ext"] = os.path.splitext(item["name"])[1].lower() if not item.get("is_dir") else ""
            out.append(item)
        return {"current": real, "roots": list(ALLOWED_BROWSE_ROOTS), "dirs": out}

    use_scandir = False
    scanned_entries = []
    try:
        with os.scandir(real) as it:
            scanned_entries = list(it)
        use_scandir = True
    except (TypeError, AttributeError, OSError):
        try:
            scanned_entries = os.listdir(real)
            use_scandir = False
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied.") from None
        except OSError as e:
            logger.warning(f"[BROWSE] listdir failed for {real}: {e}")
            raise HTTPException(status_code=500, detail="Unable to read directory.") from e

    if is_homes_dir and not is_admin and principal and principal.username:
        user_home_name = principal.username.lower()
        user_home_path = os.path.join(real, user_home_name)
        if not os.path.exists(user_home_path):
            try:
                os.makedirs(user_home_path, exist_ok=True)
                # the listing was read before the folder existed: read it again so it shows now
                if use_scandir:
                    with os.scandir(real) as it:
                        scanned_entries = list(it)
                elif user_home_name not in scanned_entries:
                    scanned_entries.append(user_home_name)
            except OSError as e:
                logger.warning(f"[BROWSE] Failed to auto-provision home directory {user_home_path}: {e}")

    # the app's own folders are never listed (SEC-3)
    scanned_entries = [
        e for e in scanned_entries if not is_protected(os.path.join(real, e.name if use_scandir else str(e)))
    ]
    if use_scandir:
        scanned_entries.sort(key=lambda x: x.name.lower())
        for entry in scanned_entries:
            e = entry.name
            if is_homes_dir and not is_admin and principal:
                if e.lower() != (principal.username or "").lower():
                    continue
            full = entry.path
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                if dirs_only and not is_dir:
                    continue
                is_symlink = entry.is_symlink()
                if is_symlink and resolve_within(full, ALLOWED_BROWSE_ROOTS) is None:
                    continue
                st = entry.stat(follow_symlinks=False)
                sz = st.st_size if not is_dir and not is_symlink else 0
                mtime = st.st_mtime
                mode = f"{stat.S_IMODE(st.st_mode):04o}" if hasattr(stat, "S_IMODE") else "0644"
            except (OSError, PermissionError):
                is_dir = real == "/mnt/remotes"
                is_symlink = False
                sz = 0
                mtime = 0.0
                mode = "0755" if real == "/mnt/remotes" else "0644"
            ext = os.path.splitext(e)[1].lower() if not is_dir else ""
            out.append(
                {
                    "name": e,
                    "path": full,
                    "is_dir": is_dir,
                    "size": sz,
                    "mtime": mtime,
                    "mode": mode,
                    "is_symlink": is_symlink,
                    "ext": ext,
                }
            )
    else:
        for e in sorted(scanned_entries):
            if is_homes_dir and not is_admin and principal:
                if e.lower() != (principal.username or "").lower():
                    continue
            full = os.path.join(real, e)
            is_dir = os.path.isdir(full)
            if dirs_only and not is_dir:
                continue
            is_symlink = os.path.islink(full)
            if is_symlink and resolve_within(full, ALLOWED_BROWSE_ROOTS) is None:
                continue
            sz = 0
            mtime = 0.0
            mode = "0755" if is_dir else "0644"
            try:
                st = os.stat(full, follow_symlinks=False)
                if not is_dir and not is_symlink:
                    sz = st.st_size
                mtime = st.st_mtime
                mode = f"{stat.S_IMODE(st.st_mode):04o}"
            except OSError:
                pass
            ext = os.path.splitext(e)[1].lower() if not is_dir else ""
            out.append(
                {
                    "name": e,
                    "path": full,
                    "is_dir": is_dir,
                    "size": sz,
                    "mtime": mtime,
                    "mode": mode,
                    "is_symlink": is_symlink,
                    "ext": ext,
                }
            )

    if real == "/mnt/remotes":
        try:
            from backend.services.rclone_engine import get_rclone_engine

            engine = get_rclone_engine()
            existing_names = {x["name"] for x in out}
            for r in engine.list_remotes():
                if r.get("is_mounted") and r.get("name") not in existing_names:
                    r_path = r.get("mount_path") or os.path.join(real, r["name"])
                    out.append(
                        {
                            "name": r["name"],
                            "path": r_path,
                            "is_dir": True,
                            "size": 0,
                            "mtime": time.time(),
                            "mode": "0755",
                            "is_symlink": False,
                            "ext": "",
                        }
                    )
        except Exception:
            logger.debug("backend.api.fs._handle_browse_logic_unfiltered: ignored error", exc_info=True)

    return {"current": real, "roots": list(ALLOWED_BROWSE_ROOTS), "dirs": out}


def _user_file_headers(media_type: str | None) -> dict[str, str]:
    """Headers for serving a user's file from the app's own origin (SEC-05).

    A CSP sandbox stops an uploaded HTML or SVG file from running script with the
    viewer's session when it is opened directly. It doesn't affect <img>, <video>
    or <audio> embedding. PDFs are left out because Chrome won't render a PDF in a
    sandboxed document.
    """
    headers = {"X-Content-Type-Options": "nosniff"}
    if (media_type or "").split(";")[0].strip().lower() != "application/pdf":
        headers["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'"
        )
    return headers


@router.get("/browse")
async def browse(
    path: str = "",
    dirs_only: str = "0",
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    check_user_path_access(path, principal, allow_list=True)
    return await asyncio.to_thread(_handle_browse_logic, path, dirs_only == "1", principal)


@router.get("/fs/roots", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))])
async def fs_roots(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Authoritative platform-aware storage hierarchy for File Explorer.
    Dynamically reports User Array, pools, cloud remotes, special folders, and boot partition.
    Strict Spindown Safety: reads only filesystem mounts and directories; never invokes smartctl.
    """

    def _gather_roots():
        res = {
            "status": "ok",
            "roots": list(ALLOWED_BROWSE_ROOTS),
            "array": None,
            "pools": [],
            "remotes": [],
            "system": [],
            "special": [],
        }

        # 1. Main Array / Pool
        if os.path.exists("/mnt/user"):
            res["array"] = {"name": "User Array", "path": "/mnt/user", "available": True}
        elif os.path.exists("/mnt/storage"):
            res["array"] = {"name": "Storage Pool", "path": "/mnt/storage", "available": True}
        elif ALLOWED_BROWSE_ROOTS:
            res["array"] = {"name": "Main Pool", "path": ALLOWED_BROWSE_ROOTS[0], "available": True}

        # 2. Additional Pools / Disks
        pool_candidates = [
            ("Cache Pool", "/mnt/cache"),
            ("Fast Pool", "/mnt/fast"),
            ("SSD Pool", "/mnt/ssd"),
        ]
        for name, p in pool_candidates:
            if os.path.exists(p):
                res["pools"].append({"name": name, "path": p, "available": True})

        # Disks under /mnt/disks (Unassigned Devices)
        if os.path.isdir("/mnt/disks"):
            try:
                for entry in sorted(os.listdir("/mnt/disks")):
                    dp = os.path.join("/mnt/disks", entry)
                    if os.path.isdir(dp) and not entry.startswith("."):
                        res["pools"].append({"name": entry, "path": dp, "available": True})
            except OSError:
                pass

        # Custom Pools under /mnt (e.g. pool1, pool2, nvme)
        if os.path.isdir("/mnt"):
            try:
                known_subdirs = {
                    "user",
                    "storage",
                    "remotes",
                    "disks",
                    "cache",
                    "fast",
                    "ssd",
                }
                for entry in sorted(os.listdir("/mnt")):
                    if entry.lower() not in known_subdirs and not entry.startswith("."):
                        p = os.path.join("/mnt", entry)
                        if os.path.isdir(p):
                            res["pools"].append({"name": entry, "path": p, "available": True})
            except OSError:
                pass

        # 3. Cloud Remotes & Connected Drives
        configured_remotes = {}
        try:
            from backend.services.rclone_engine import get_rclone_engine

            engine = get_rclone_engine()
            for r in engine.list_remotes():
                configured_remotes[r["name"]] = r
        except Exception as e:
            logger.debug(f"[FS_ROOTS] rclone list_remotes failed: {e}")

        remotes_dir = getattr(config, "REMOTES_PATH", "/mnt/remotes")
        if os.path.isdir(remotes_dir):
            try:
                for entry in sorted(os.listdir(remotes_dir)):
                    if entry.startswith("."):
                        continue
                    rp = os.path.join(remotes_dir, entry)
                    conf = configured_remotes.get(entry, {})
                    res["remotes"].append(
                        {
                            "name": entry,
                            "path": rp,
                            "type": conf.get("type", "cloud"),
                            "available": os.path.exists(rp),
                            "is_mounted": True,
                        }
                    )
            except OSError:
                pass

        for r_name, r_conf in configured_remotes.items():
            if not any(r["name"] == r_name for r in res["remotes"]):
                m_path = r_conf.get("mount_path") or os.path.join(remotes_dir, r_name)
                is_mounted = bool(r_conf.get("is_mounted"))
                if is_mounted or os.path.exists(m_path):
                    res["remotes"].append(
                        {
                            "name": r_name,
                            "path": m_path,
                            "type": r_conf.get("type", "cloud"),
                            "available": os.path.exists(m_path),
                            "is_mounted": is_mounted,
                        }
                    )

        # 4. System (/boot) - Flash Boot
        is_admin = principal and (
            principal.role_id in ("superadmin", "storage_admin")
            or principal.has_scope("storage:admin")
            or principal.has_scope("*")
        )
        if os.path.exists("/boot"):
            res["system"].append(
                {
                    "name": "Flash Boot (/boot)",
                    "path": "/boot",
                    "admin_only": True,
                    "accessible": bool(is_admin),
                }
            )

        # 5. Special Folders (Downloads, Media, Appdata, Recycle Bin)
        base_arr = res["array"]["path"] if res["array"] else "/mnt/user"
        special_candidates = [
            ("Downloads", os.path.join(base_arr, "downloads"), "downloads"),
            ("Media", os.path.join(base_arr, "media"), "media"),
            ("Appdata", os.path.join(base_arr, "appdata"), "box"),
            ("Recycle Bin", os.path.join(base_arr, ".RecycleBin"), "trash"),
        ]
        for name, p, icon in special_candidates:
            if os.path.exists(p) or name == "Recycle Bin":
                res["special"].append({"name": name, "path": p, "icon": icon, "available": True})

        return res

    return await asyncio.to_thread(_gather_roots)


def _do_mkdir(path: str):
    path = str(path or "").strip()
    parent = _contained(os.path.dirname(path.rstrip("/")) or "/", must_exist=True)
    name = os.path.basename(path.rstrip("/"))
    if not name or name in (".", "..") or "/" in name:
        raise HTTPException(status_code=400, detail="Invalid folder name")
    target = os.path.join(parent, name)
    if resolve_within(target, ALLOWED_BROWSE_ROOTS) is None:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders.")
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as e:
        logger.warning(f"[MKDIR] Failed to create {target}: {e}")
        raise HTTPException(status_code=500, detail="Unable to create folder.") from e
    return {"status": "ok", "path": target}


@router.post(
    "/mkdir",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def mkdir(req: MkdirRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    check_user_path_access(req.path, principal, write=True)
    import backend.api.system as sys_mod

    fn = (
        getattr(sys_mod, "_do_mkdir", _do_mkdir)
        if hasattr(sys_mod, "_do_mkdir") and sys_mod._do_mkdir != _do_mkdir
        else _do_mkdir
    )
    return fn(req.path)


def _observe(kind: str, path: str, principal: Any, new_path: str = "") -> None:
    """Feeds file-manager changes to the ransomware guard (M4)."""
    from backend.auth import CLIENT_IP_CTX
    from backend.services.ransomware_guard import get_guard

    get_guard().observe(
        kind, path, user=getattr(principal, "username", "") or "", ip=CLIENT_IP_CTX.get(), new_path=new_path
    )


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


def _safe_fs_target(req_path: str):
    raw = str(req_path or "").strip()
    if not raw or "\x00" in raw:
        raise HTTPException(status_code=400, detail="Invalid path")
    # Disallow root paths
    canonical_roots = {os.path.realpath(r) for r in ALLOWED_BROWSE_ROOTS}
    norm = os.path.normpath(raw)
    parent_raw = os.path.dirname(norm)
    parent_canonical = resolve_within(parent_raw, ALLOWED_BROWSE_ROOTS)
    if parent_canonical is None:
        raise HTTPException(status_code=403, detail="Path is outside allowed folders.")

    base = os.path.basename(norm)
    if not base or base in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid path element")

    target_unresolved = os.path.join(parent_canonical, base)
    target_canonical = resolve_within(target_unresolved, ALLOWED_BROWSE_ROOTS)
    if target_canonical is None:
        raise HTTPException(status_code=403, detail="Path or target symlink resolves outside allowed folders.")

    if target_canonical in canonical_roots or os.path.realpath(target_unresolved) in canonical_roots:
        raise HTTPException(status_code=403, detail="Cannot operate on browse root")

    if not os.path.lexists(target_unresolved):
        raise HTTPException(status_code=404, detail="Item does not exist")

    return target_unresolved, parent_canonical, base


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

        recycle_dir = os.path.join(real_root, ".RecycleBin")
        files_dir = os.path.join(recycle_dir, "files")
        info_dir = os.path.join(recycle_dir, "info")
        base_name = os.path.basename(target_unresolved)
        ts = int(time.time())
        dest_name = f"{ts}_{base_name}"
        dest_path = os.path.join(files_dir, dest_name)
        info_path = os.path.join(info_dir, f"{dest_name}.trashinfo")

        def _move_to_recycle():
            os.makedirs(files_dir, exist_ok=True)
            os.makedirs(info_dir, exist_ok=True)
            iso_now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                with open(info_path, "w", encoding="utf-8") as f_info:
                    f_info.write(f"[Trash Info]\nPath={target_unresolved}\nDeletionDate={iso_now}\n")
            except Exception as e_info:
                logger.warning(f"[FS] Could not write .trashinfo: {e_info}")
            shutil.move(target_unresolved, dest_path)

        await asyncio.to_thread(_move_to_recycle)
        add_event("info", "File Explorer", f"Moved {base_name} to Recycle Bin")

        return {"status": "ok", "message": "Item moved to Recycle Bin"}
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


def _task_owner_filter(principal: AuthenticatedPrincipal | None) -> str | None:
    """None (see every task) for admins, else the caller's username (SEC-11)."""
    return None if _is_files_admin(principal) else (principal.username or "").lower() if principal else ""


def _assert_task_owner(task_id: str, principal: AuthenticatedPrincipal | None) -> None:
    from backend.services.fs_transfer import transfer_manager

    owner = _task_owner_filter(principal)
    if owner is not None and transfer_manager.owner_of(task_id) not in (owner,):
        raise HTTPException(status_code=404, detail="Task not found")


@router.get(
    "/fs/transfers",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
def fs_list_transfers(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    return {"status": "ok", "tasks": transfer_manager.list_tasks(owner=_task_owner_filter(principal))}


@router.get("/fs/transfers/stream")
async def fs_transfers_stream(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    from backend.services.fs_transfer import transfer_manager

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=100)
    transfer_manager.register_listener(queue, loop)

    async def event_generator():
        try:
            owner = _task_owner_filter(principal)
            initial_data = json.dumps({"event": "snapshot", "tasks": transfer_manager.list_tasks(owner=owner)})
            yield f"event: snapshot\ndata: {initial_data}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    if owner is not None and (payload.get("task") or {}).get("owner") != owner:
                        continue
                    evt_type = payload.get("event", "update")
                    data_str = json.dumps(payload)
                    yield f"event: {evt_type}\ndata: {data_str}\n\n"
                except TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            transfer_manager.unregister_listener(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/fs/transfers/{task_id}/pause",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def fs_pause_transfer(task_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    _assert_task_owner(task_id, principal)
    ok = transfer_manager.pause_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found or cannot be paused")
    return {"status": "ok", "paused": True}


@router.post(
    "/fs/transfers/{task_id}/resume",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def fs_resume_transfer(task_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    _assert_task_owner(task_id, principal)
    ok = transfer_manager.resume_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found or cannot be resumed")
    return {"status": "ok", "resumed": True}


@router.post(
    "/fs/transfers/{task_id}/cancel",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def fs_cancel_transfer(task_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    _assert_task_owner(task_id, principal)
    ok = transfer_manager.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found or cannot be cancelled")
    return {"status": "ok", "cancelled": True}


@router.delete(
    "/fs/transfers/completed",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def fs_clear_completed_transfers(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    cleared = transfer_manager.clear_completed_tasks()
    return {"status": "ok", "cleared_count": cleared}


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


@router.get("/fs/download")
def fs_download(path: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot download a directory")
    return FileResponse(
        target, filename=os.path.basename(target), headers=_user_file_headers(mimetypes.guess_type(target)[0])
    )


def _inbox_dir(principal: AuthenticatedPrincipal) -> str:
    """The user's Inbox for files shared from a phone (M1): <home>/Inbox."""
    from backend.users_db import get_user_by_username

    rec = get_user_by_username(principal.username) or {}
    home = rec.get("home_directory") or os.path.join(POOL_PATH or ALLOWED_BROWSE_ROOTS[0], "homes", principal.username)
    inbox = os.path.join(home, "Inbox")
    canonical = resolve_within(inbox, ALLOWED_BROWSE_ROOTS)
    if canonical is None:
        raise HTTPException(status_code=400, detail="Your home folder is outside the allowed folders")
    return canonical


@router.get("/fs/inbox", dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin"))])
def fs_inbox(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    return {"path": _inbox_dir(principal)}


@router.post("/fs/inbox", dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin"))])
async def fs_inbox_upload(
    request: Request, filename: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Saves one shared file into the Inbox under a name that doesn't overwrite anything (M1)."""
    inbox = _inbox_dir(principal)
    check_user_path_access(inbox, principal, write=True)
    name = os.path.basename(str(filename or "").replace("\\", "/")).strip() or "shared-file"
    if name in (".", "..") or name.startswith("."):
        name = f"shared{name}"
    await asyncio.to_thread(os.makedirs, inbox, exist_ok=True)
    stem, ext = os.path.splitext(name)
    target = os.path.join(inbox, name)
    n = 1
    while os.path.lexists(target):
        n += 1
        target = os.path.join(inbox, f"{stem} ({n}){ext}")
    staging = os.path.join(inbox, f".zettnas_tmp_{secrets.token_hex(8)}")
    try:
        async with aiofiles.open(staging, "wb") as f_out:
            async for chunk in request.stream():
                if chunk:
                    await f_out.write(chunk)
        os.replace(staging, target)
    finally:
        if os.path.exists(staging):
            os.remove(staging)
    _observe("write", target, principal)
    add_event("success", "File Explorer", f"Received {os.path.basename(target)} in Inbox")
    return {"status": "ok", "path": target, "name": os.path.basename(target)}


@router.post(
    "/fs/upload",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_upload(
    request: Request,
    path: str,
    filename: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    check_user_path_access(path, principal, write=True)
    target_unresolved, _, _ = _safe_fs_target(path)
    target_canonical = resolve_within(target_unresolved, ALLOWED_BROWSE_ROOTS)
    if target_canonical is None or not os.path.isdir(target_canonical):
        raise HTTPException(status_code=400, detail="Target path is not a valid directory within allowed folders")

    # Secure filename against traversal
    filename = os.path.basename(filename)
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(target_canonical, filename)
    check_user_path_access(file_path, principal, write=True)
    if os.path.islink(file_path) and resolve_within(file_path, ALLOWED_BROWSE_ROOTS) is None:
        raise HTTPException(status_code=403, detail="Destination symlink points outside allowed folders")

    # Personal space quota (Batch 6): refuse up front when the size is known, stop when it isn't
    from backend.services.user_spaces import QuotaExceeded, check_upload

    declared = int(request.headers.get("content-length") or 0)
    try:
        allowed = check_upload(principal.username, file_path, declared)
    except QuotaExceeded as e:
        raise HTTPException(status_code=507, detail=str(e)) from None

    staging_file = os.path.join(target_canonical, f".zettnas_tmp_{secrets.token_hex(8)}_{filename}")
    try:
        written = 0
        async with aiofiles.open(staging_file, "wb") as f_out:
            async for chunk in request.stream():
                if chunk:
                    written += len(chunk)
                    if allowed is not None and written > allowed:
                        raise QuotaExceeded(0, 0, written)
                    await f_out.write(chunk)

        os.replace(staging_file, file_path)
        add_event("success", "File Explorer", f"Uploaded {filename} to {path}")
        return {"status": "ok", "message": "File uploaded"}
    except QuotaExceeded:
        if os.path.exists(staging_file):
            os.remove(staging_file)
        raise HTTPException(status_code=507, detail="This upload would go over your space.") from None
    except Exception as e:
        if os.path.exists(staging_file):
            try:
                os.remove(staging_file)
            except Exception:
                logger.debug("backend.api.fs.fs_upload: ignored error", exc_info=True)
        logger.error(f"[FS] Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file") from e


UPLOAD_CHUNK_SIZE = 16 * 1024 * 1024
UPLOAD_SESSION_TTL = 24 * 3600
UPLOAD_FREE_FLOOR = 1024**3  # an upload never fills the pool to the last gigabyte (SEC-7)


class UploadInitRequest(BaseModel):
    # the File Explorer sends destination_dir and no chunk count; scripts send path
    path: str | None = None
    destination_dir: str | None = None
    filename: str
    total_size: int = Field(ge=0)
    total_chunks: int | None = Field(default=None, ge=1, le=1_000_000)
    chunk_size: int | None = None


class UploadCompleteRequest(BaseModel):
    upload_id: str
    expected_sha256: str | None = None


_CHUNKED_UPLOADS: dict[str, dict[str, Any]] = {}
_CHUNKED_UPLOADS_LOCK = asyncio.Lock()


@router.post(
    "/fs/upload/init",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_upload_init(
    req: UploadInitRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    dest = req.path or req.destination_dir or ""
    if not dest:
        raise HTTPException(status_code=400, detail="Choose a folder to upload to")
    fewest = max(1, -(-int(req.total_size) // UPLOAD_CHUNK_SIZE))
    total_chunks = int(req.total_chunks or fewest)
    if not fewest <= total_chunks <= max(1, int(req.total_size)):
        raise HTTPException(status_code=400, detail="The chunk count doesn't match the file size")
    await _expire_uploads()
    check_user_path_access(dest, principal, write=True)
    target_unresolved, _, _ = _safe_fs_target(dest)
    target_canonical = resolve_within(target_unresolved, ALLOWED_BROWSE_ROOTS)
    if target_canonical is None or not os.path.isdir(target_canonical):
        raise HTTPException(status_code=400, detail="Target path is not a valid directory within allowed folders")

    filename = os.path.basename(req.filename)
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    from backend.services.user_spaces import QuotaExceeded, check_upload

    try:
        check_upload(principal.username, os.path.join(target_canonical, filename), int(req.total_size or 0))
    except QuotaExceeded as e:
        raise HTTPException(status_code=507, detail=str(e)) from None

    try:
        free = shutil.disk_usage(target_canonical).free
    except OSError:
        free = None
    if free is not None and free - int(req.total_size) < UPLOAD_FREE_FLOOR:
        raise HTTPException(status_code=507, detail="Not enough free space for this file.")

    upload_id = secrets.token_hex(16)
    staging_dir = os.path.join(target_canonical, f".zettnas_staging_{upload_id}_{filename}")
    os.makedirs(staging_dir, exist_ok=True)

    async with _CHUNKED_UPLOADS_LOCK:
        _CHUNKED_UPLOADS[upload_id] = {
            "upload_id": upload_id,
            "target_dir": target_canonical,
            "staging_dir": staging_dir,
            "filename": filename,
            "total_size": int(req.total_size),
            "total_chunks": total_chunks,
            "chunks_received": set(),
            "chunk_bytes": {},
            "created_at": time.time(),
            "created_by": principal.username,
        }

    return {
        "status": "ok",
        "upload_id": upload_id,
        "chunk_size": UPLOAD_CHUNK_SIZE,
        "total_chunks": total_chunks,
    }


async def _expire_uploads() -> None:
    """Uploads left unfinished for a day are removed with their staged chunks (SEC-7)."""
    cutoff = time.time() - UPLOAD_SESSION_TTL
    async with _CHUNKED_UPLOADS_LOCK:
        stale = [u for u in _CHUNKED_UPLOADS.values() if u.get("created_at", 0) < cutoff]
        for u in stale:
            _CHUNKED_UPLOADS.pop(u["upload_id"], None)
    for u in stale:
        shutil.rmtree(u.get("staging_dir", ""), ignore_errors=True)


@router.post(
    "/fs/upload/chunk",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_upload_chunk(
    request: Request,
    upload_id: str,
    chunk_index: int,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    async with _CHUNKED_UPLOADS_LOCK:
        upload_info = _CHUNKED_UPLOADS.get(upload_id)
        if not upload_info:
            raise HTTPException(status_code=404, detail="Upload session not found or expired")
        if upload_info.get("created_by") != principal.username and not principal.has_scope("storage:admin"):
            raise HTTPException(status_code=403, detail="Not authorized to write to this upload")

    staging_dir = upload_info["staging_dir"]
    if not os.path.isdir(staging_dir):
        raise HTTPException(status_code=404, detail="Staging directory missing for upload session")
    if not 0 <= chunk_index < int(upload_info["total_chunks"]):
        raise HTTPException(status_code=400, detail="Chunk number out of range")

    # This chunk may not exceed the chunk size, nor all chunks together the declared size (SEC-7)
    others = sum(b for i, b in upload_info["chunk_bytes"].items() if i != chunk_index)
    allowed = min(UPLOAD_CHUNK_SIZE, int(upload_info["total_size"]) - others)
    chunk_path = os.path.join(staging_dir, f"chunk_{chunk_index:06d}")
    written = 0
    async with aiofiles.open(chunk_path, "wb") as f_out:
        async for content in request.stream():
            if content:
                written += len(content)
                if written > allowed:
                    break
                await f_out.write(content)
    if written > allowed:
        try:
            os.remove(chunk_path)
        except OSError:
            logger.debug("fs_upload_chunk: oversized chunk already gone", exc_info=True)
        raise HTTPException(status_code=413, detail="This upload is larger than the size it announced.")

    async with _CHUNKED_UPLOADS_LOCK:
        if upload_id in _CHUNKED_UPLOADS:
            _CHUNKED_UPLOADS[upload_id]["chunks_received"].add(chunk_index)
            _CHUNKED_UPLOADS[upload_id]["chunk_bytes"][chunk_index] = written

    return {"status": "ok", "chunk_index": chunk_index}


@router.post(
    "/fs/upload/complete",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_upload_complete(
    req: UploadCompleteRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    async with _CHUNKED_UPLOADS_LOCK:
        upload_info = _CHUNKED_UPLOADS.get(req.upload_id)
        if not upload_info:
            raise HTTPException(status_code=404, detail="Upload session not found or expired")

    staging_dir = upload_info["staging_dir"]
    target_dir = upload_info["target_dir"]
    filename = upload_info["filename"]
    total_chunks = upload_info["total_chunks"]
    chunks_received = upload_info["chunks_received"]

    if len(chunks_received) < total_chunks:
        missing = set(range(total_chunks)) - chunks_received
        raise HTTPException(status_code=400, detail=f"Upload incomplete. Missing {len(missing)} chunks")
    if sum(upload_info.get("chunk_bytes", {}).values()) != int(upload_info["total_size"]):
        raise HTTPException(status_code=400, detail="The uploaded size doesn't match the announced size")

    final_target = os.path.join(target_dir, filename)
    check_user_path_access(final_target, principal, write=True)
    temp_assembly = os.path.join(target_dir, f".zettnas_tmp_{req.upload_id}_{filename}")

    sha256 = hashlib.sha256()
    try:
        async with aiofiles.open(temp_assembly, "wb") as f_out:
            for idx in range(total_chunks):
                chunk_file = os.path.join(staging_dir, f"chunk_{idx:06d}")
                if not os.path.exists(chunk_file):
                    raise HTTPException(status_code=400, detail=f"Chunk file {idx} missing on disk")
                async with aiofiles.open(chunk_file, "rb") as f_in:
                    while b := await f_in.read(65536):
                        sha256.update(b)
                        await f_out.write(b)

        computed_hash = sha256.hexdigest()
        if req.expected_sha256 and req.expected_sha256.lower().strip() != computed_hash.lower():
            if os.path.exists(temp_assembly):
                os.remove(temp_assembly)
            raise HTTPException(
                status_code=400,
                detail=f"SHA-256 integrity mismatch: expected {req.expected_sha256}, computed {computed_hash}",
            )

        os.replace(temp_assembly, final_target)
        shutil.rmtree(staging_dir, ignore_errors=True)
        async with _CHUNKED_UPLOADS_LOCK:
            _CHUNKED_UPLOADS.pop(req.upload_id, None)

        final_size = os.path.getsize(final_target)
        add_event("success", "File Explorer", f"Completed chunked upload of {filename}")
        return {
            "status": "ok",
            "filename": filename,
            "size_bytes": final_size,
            "sha256": computed_hash,
        }
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(temp_assembly):
            try:
                os.remove(temp_assembly)
            except Exception:
                logger.debug("backend.api.fs.fs_upload_complete: ignored error", exc_info=True)
        logger.error(f"[FS] Chunked assembly failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to assemble uploaded chunks: {e}") from e


class TrashRestoreRequest(BaseModel):
    item_id: str
    target_path: str | None = None


@router.get("/fs/search", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))])
async def fs_search(
    q: str,
    path: str | None = None,
    limit: int = 50,
    offset: int = 0,
    recursive: bool = True,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """
    Streaming bounded filesystem search using os.scandir with path containment.
    """
    query = (q or "").strip().lower()
    if not query:
        return {"items": [], "total": 0, "query": q, "limit": limit, "offset": offset}

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    if path and path.strip():
        check_user_path_access(path, principal, allow_list=True)
        search_root = resolve_within(path, ALLOWED_BROWSE_ROOTS)
        if search_root is None or not os.path.isdir(search_root):
            raise HTTPException(status_code=400, detail="Invalid search path")
        search_roots = [search_root]
    else:
        search_roots = [r for r in ALLOWED_BROWSE_ROOTS if os.path.isdir(r)]

    def _execute_search():
        matched = []
        scanned_count = 0
        max_scanned = 10000

        for s_root in search_roots:
            queue = [(s_root, 0)]
            while queue and scanned_count < max_scanned:
                curr_dir, depth = queue.pop(0)
                try:
                    with os.scandir(curr_dir) as it:
                        for entry in it:
                            scanned_count += 1
                            if scanned_count >= max_scanned:
                                break
                            if entry.name.startswith(".") or is_protected(entry.path):
                                continue
                            if not user_can_access_path(entry.path, principal, allow_list=True):
                                continue

                            is_match = query in entry.name.lower()
                            is_dir = entry.is_dir(follow_symlinks=False)

                            if is_match:
                                try:
                                    st = entry.stat(follow_symlinks=False)
                                    matched.append(
                                        {
                                            "name": entry.name,
                                            "path": entry.path,
                                            "is_dir": is_dir,
                                            "size": st.st_size if not is_dir else 0,
                                            "mtime": st.st_mtime,
                                        }
                                    )
                                except (OSError, PermissionError):
                                    pass

                            if recursive and is_dir and depth < 8 and not entry.is_symlink():
                                queue.append((entry.path, depth + 1))
                except (OSError, PermissionError):
                    continue

        total = len(matched)
        paged = matched[offset : offset + limit]
        return {"items": paged, "total": total, "query": q, "limit": limit, "offset": offset}

    return await asyncio.to_thread(_execute_search)


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
                    orig_name = parts[1] if (len(parts) == 2 and parts[0].isdigit()) else item_id

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


def _extract_image_metadata(file_path: str) -> dict:
    """Size, color and EXIF details for the viewer's info panel (backend/services/photo_meta.py)."""
    from backend.services.photo_meta import extract_image_metadata

    return extract_image_metadata(file_path)


@router.get("/fs/preview", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))])
async def fs_preview(path: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Universal Quick Look preview generator.
    Redacts sensitive credentials from config/text files. Generates 1KB hex dumps for binaries.
    """
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot preview a directory")

    filename = os.path.basename(target)
    ext = os.path.splitext(filename)[1].lower()
    sz = os.path.getsize(target)

    # 1. Image formats
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tiff", ".heic", ".heif"}
    if ext in image_exts:
        is_heif = ext in {".heic", ".heif"}
        preview_url = f"/api/fs/preview/image?path={target}" if is_heif else f"/api/fs/download?path={target}"
        result = {
            "status": "ok",
            "type": "image",
            "path": target,
            "name": filename,
            "size": sz,
            "ext": ext,
            "url": preview_url,
            "download_url": f"/api/fs/download?path={target}",
        }
        img_meta = _extract_image_metadata(target)
        result.update(img_meta)
        return result

    # 2. Media (audio / video) formats
    media_exts = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"}
    if ext in media_exts:
        return {
            "status": "ok",
            "type": "media",
            "path": target,
            "name": filename,
            "size": sz,
            "ext": ext,
            "stream_url": f"/api/fs/stream?path={target}",
        }

    # 3. PDF
    if ext == ".pdf":
        return {
            "status": "ok",
            "type": "pdf",
            "path": target,
            "name": filename,
            "size": sz,
            "ext": ext,
            "url": f"/api/fs/download?path={target}",
        }

    # 4. Text / Code / Config formats
    text_exts = {
        ".txt",
        ".md",
        ".json",
        ".js",
        ".mjs",
        ".ts",
        ".html",
        ".css",
        ".py",
        ".sh",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".xml",
        ".csv",
        ".log",
        ".toml",
        ".sql",
        ".c",
        ".h",
        ".cpp",
        ".rs",
        ".go",
        ".dockerfile",
    }

    def _make_hex_dump(raw_bytes: bytes) -> list[str]:
        lines = []
        for i in range(0, len(raw_bytes), 16):
            chunk = raw_bytes[i : i + 16]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
            lines.append(f"{i:08x}  {hex_part:<48}  |{ascii_part}|")
        return lines

    def _read_preview_bytes(file_path: str, count: int) -> bytes:
        with open(file_path, "rb") as f:
            return f.read(count)

    if ext in text_exts or filename.startswith(".") or sz <= 1024 * 1024:
        try:
            head = await asyncio.to_thread(_read_preview_bytes, target, 65536)
            if b"\x00" not in head:
                text_content = head.decode("utf-8", errors="replace")
                sanitized = sanitize_string(text_content)
                lines = sanitized.splitlines()
                return {
                    "status": "ok",
                    "type": "text",
                    "path": target,
                    "name": filename,
                    "size": sz,
                    "ext": ext,
                    "content": sanitized,
                    "lines_count": len(lines),
                    "truncated": sz > 65536,
                }
        except Exception as e:
            logger.warning(f"[PREVIEW] Text read error for {target}: {e}")

    # 5. Binary Hex Preview (1KB)
    try:
        sample = await asyncio.to_thread(_read_preview_bytes, target, 1024)
        dump = _make_hex_dump(sample)
        return {
            "status": "ok",
            "type": "hex",
            "path": target,
            "name": filename,
            "size": sz,
            "ext": ext,
            "hex_dump": dump,
        }
    except Exception as e:
        logger.error(f"[PREVIEW] Hex dump error for {target}: {e}")
        raise HTTPException(status_code=500, detail="Unable to generate preview") from e


@router.get(
    "/fs/preview/image",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
async def fs_preview_image(
    path: str,
    thumb: int | None = None,
    max_dim: int | None = None,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Thumbnails and screen-sized previews as WebP: photos (including Apple HEIC/HEIF) and
    video frames, cached on disk (backend/services/thumbs.py). Other files are served as they are.
    """
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot preview a directory")

    ext = os.path.splitext(target)[1].lower()
    is_heif = ext in {".heic", ".heif"}
    if not thumb and not max_dim and not is_heif:
        return FileResponse(target, headers=_user_file_headers(mimetypes.guess_type(target)[0]))

    kind = thumbs.kind(target)
    if kind is None:
        if ext in {".svg", ".ico"}:
            return FileResponse(target, headers=_user_file_headers(mimetypes.guess_type(target)[0]))
        raise HTTPException(status_code=415, detail="No preview for this file type")

    limit = thumbs.THUMB_SIZE if thumb else (min(max_dim, thumbs.MAX_SIZE) if max_dim else 2560)
    data = await asyncio.to_thread(thumbs.get, target, limit)
    if data is None:
        if kind == "image" and not is_heif:
            return FileResponse(target, headers=_user_file_headers(mimetypes.guess_type(target)[0]))
        raise HTTPException(status_code=415, detail="This file can't be previewed")
    mtime = os.path.getmtime(target)
    etag = f'"{hashlib.md5(f"{target}:{mtime}:{limit}".encode()).hexdigest()}"'
    return Response(
        content=data,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400, stale-while-revalidate=3600", "ETag": etag},
    )


@router.get(
    "/fs/media/info",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
async def fs_media_info(path: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Duration, resolution, codecs, frame rate and rotation of a video or audio file."""
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Not a file")
    info = await asyncio.to_thread(media_info.probe, target)
    if info is None:
        raise HTTPException(status_code=415, detail="Not a video or audio file")
    return info


@router.get(
    "/fs/stream/compat",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
def fs_stream_compat(
    path: str,
    start: float = 0.0,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """The video converted to H.264/AAC in fragmented MP4 while it plays, from `start` seconds."""
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target) or thumbs.kind(target) != "video":
        raise HTTPException(status_code=415, detail="Not a video file")
    try:
        chunks, _stop = video_compat.stream(target, max(0.0, min(start, 7 * 24 * 3600)))
    except video_compat.Busy as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return StreamingResponse(
        iterate_in_threadpool(chunks),
        media_type="video/mp4",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/fs/stream")
def fs_stream(
    path: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """HTTP 206 Partial Content Range streaming for video and audio playback."""
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot stream a directory")

    file_size = os.path.getsize(target)
    range_header = request.headers.get("range")

    import mimetypes

    content_type, _ = mimetypes.guess_type(target)
    if not content_type:
        content_type = "application/octet-stream"

    if not range_header:

        def iter_full():
            with open(target, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            iter_full(),
            media_type=content_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
                **_user_file_headers(content_type),
            },
        )

    range_str = range_header.replace("bytes=", "").strip()
    range_parts = range_str.split("-")
    try:
        start = int(range_parts[0]) if range_parts[0] else 0
        end = int(range_parts[1]) if len(range_parts) > 1 and range_parts[1] else file_size - 1
    except ValueError:
        raise HTTPException(status_code=416, detail="Invalid range request") from None

    start = max(0, start)
    end = min(file_size - 1, end)
    if start > end or start >= file_size:
        raise HTTPException(
            status_code=416,
            detail="Requested range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_length = end - start + 1

    def iter_range():
        with open(target, "rb") as f:
            f.seek(start)
            remaining = chunk_length
            while remaining > 0:
                read_sz = min(remaining, 65536)
                data = f.read(read_sz)
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        iter_range(),
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_length),
            **_user_file_headers(content_type),
        },
    )


@router.get("/fs/download-zip")
def fs_download_zip(
    paths: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Streams a zip archive containing multiple selected files or folders without staging on disk."""
    path_list = [p.strip() for p in paths.split(",") if p.strip()]
    if not path_list:
        raise HTTPException(status_code=400, detail="No paths specified")

    for p in path_list:
        check_user_path_access(p, principal)
        target = _contained(p, must_exist=True)
        if resolve_within(target, ALLOWED_BROWSE_ROOTS) is None:
            raise HTTPException(status_code=403, detail="Path outside allowed folders")

    def _zip_generator():
        spool = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)  # noqa: SIM115
        try:
            with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                for p in path_list:
                    real_target = _contained(p, must_exist=True)
                    base = os.path.basename(real_target)
                    if os.path.isdir(real_target):
                        for root_dir, sub_dirs, files in os.walk(real_target):
                            prune_protected(root_dir, sub_dirs)
                            for f in files:
                                fp = os.path.join(root_dir, f)
                                # Ensure symlinks inside directories do not escape allowed roots or user bounds
                                if os.path.islink(fp):
                                    resolved_sym = os.path.realpath(fp)
                                    if resolve_within(resolved_sym, ALLOWED_BROWSE_ROOTS) is None:
                                        continue
                                    try:
                                        check_user_path_access(resolved_sym, principal)
                                    except HTTPException:
                                        continue
                                rel = os.path.relpath(fp, os.path.dirname(real_target))
                                zf.write(fp, arcname=rel)
                    else:
                        if os.path.islink(real_target):
                            resolved_sym = os.path.realpath(real_target)
                            if resolve_within(resolved_sym, ALLOWED_BROWSE_ROOTS) is None:
                                continue
                            try:
                                check_user_path_access(resolved_sym, principal)
                            except HTTPException:
                                continue
                        zf.write(real_target, arcname=base)
            spool.seek(0)
            while chunk := spool.read(65536):
                yield chunk
        finally:
            spool.close()

    ts = int(time.time())
    zip_name = f"download_{ts}.zip"
    return StreamingResponse(
        _zip_generator(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


# --- Temporary Public Share Links Subsystem ---

SHARE_LINKS_FILE = os.path.join(config.DATA_DIR, "shared_links.json")
_SHARE_LOCK = asyncio.Lock()


def _load_share_links() -> dict[str, Any]:
    try:
        return read_json(SHARE_LINKS_FILE, {})
    except Exception:
        return {}


def _save_share_links(links: dict[str, Any]) -> None:
    """Saves share links; a failure is an error the caller sees, never a silent "ok" (SEC-10)."""
    try:
        atomic_write_json(SHARE_LINKS_FILE, links)
    except Exception as e:
        logger.error(f"[FS] Failed to persist share links: {e}")
        raise HTTPException(
            status_code=500, detail="The share links could not be saved (is the disk full?). Nothing was changed."
        ) from e


class CreateShareLinkRequest(BaseModel):
    path: str
    expires_hours: int | None = None
    max_downloads: int | None = None
    password: str | None = None
    label: str | None = None


# Sliding-window rate limiter for shared link password attempts: IP -> list of timestamps
_SHARE_PWD_ATTEMPTS: dict[str, list[float]] = {}
_SHARE_PWD_LOCK = asyncio.Lock()


def _get_client_ip(request: Request) -> str:
    from backend.auth import client_ip

    return client_ip(request)


async def _check_share_rate_limit(ip: str):
    now = time.time()
    async with _SHARE_PWD_LOCK:
        attempts = _SHARE_PWD_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if now - t < 600]
        _SHARE_PWD_ATTEMPTS[ip] = attempts
        if len(attempts) >= 5:
            raise HTTPException(
                status_code=429,
                detail="Too many failed password attempts. Please wait 10 minutes before retrying.",
            )


async def _record_failed_share_attempt(ip: str):
    now = time.time()
    async with _SHARE_PWD_LOCK:
        attempts = _SHARE_PWD_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if now - t < 600]
        attempts.append(now)
        _SHARE_PWD_ATTEMPTS[ip] = attempts


async def _reset_share_rate_limit(ip: str):
    async with _SHARE_PWD_LOCK:
        _SHARE_PWD_ATTEMPTS.pop(ip, None)


@router.post(
    "/fs/share-links",
    dependencies=[
        Depends(require_scope("files:read", "files:write", "storage:read", "storage:admin")),
        Depends(rate_limit("share.create", 30, 3600)),
    ],
)
@router.post(
    "/share-links",
    dependencies=[
        Depends(require_scope("files:read", "files:write", "storage:read", "storage:admin")),
        Depends(rate_limit("share.create", 30, 3600)),
    ],
)
async def create_share_link(
    req: CreateShareLinkRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Generates a secure, temporary or password-protected public share link for a file or folder."""
    target_path = req.path.strip()
    check_user_path_access(target_path, principal)
    real_target = _contained(target_path, must_exist=True)

    if resolve_within(real_target, ALLOWED_BROWSE_ROOTS) is None:
        raise HTTPException(status_code=403, detail="Path outside allowed folders")

    token = secrets.token_urlsafe(24)
    now = time.time()
    expires_at = (now + (req.expires_hours * 3600)) if req.expires_hours and req.expires_hours > 0 else None

    password_hash = None
    if req.password and req.password.strip():
        password_hash = hash_password(req.password.strip())

    link_data = {
        "token": token,
        "path": target_path,
        "is_dir": os.path.isdir(real_target),
        "filename": os.path.basename(real_target),
        "label": req.label or os.path.basename(real_target),
        "created_by": principal.username,
        "created_at": now,
        "expires_at": expires_at,
        "max_downloads": req.max_downloads if req.max_downloads and req.max_downloads > 0 else None,
        "download_count": 0,
        "has_password": password_hash is not None,
        "password_hash": password_hash,
    }

    async with _SHARE_LOCK:
        links = _load_share_links()
        links[token] = link_data
        _save_share_links(links)

    sanitized = dict(link_data)
    sanitized.pop("password_hash", None)
    sanitized["url"] = f"/api/fs/shared/{token}"
    return sanitized


@router.get("/fs/share-links", dependencies=[Depends(require_scope("files:read", "storage:read", "storage:admin"))])
@router.get("/share-links", dependencies=[Depends(require_scope("files:read", "storage:read", "storage:admin"))])
def list_share_links(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Lists active public share links created by the current user or all if admin."""
    links = _load_share_links()
    is_admin = principal.has_scope("superadmin") or principal.has_scope("storage:admin") or principal.has_scope("*")
    now = time.time()

    results = []
    for token, item in links.items():
        if not is_admin and item.get("created_by") != principal.username:
            continue
        expired = item.get("expires_at") and now > item["expires_at"]
        limit_reached = item.get("max_downloads") and item.get("download_count", 0) >= item["max_downloads"]

        res = dict(item)
        res.pop("password_hash", None)
        res["url"] = f"/api/fs/shared/{token}"
        res["is_expired"] = bool(expired)
        res["limit_reached"] = bool(limit_reached)
        res["is_active"] = not expired and not limit_reached
        results.append(res)

    results.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return results


@router.delete("/fs/share-links/{token}", dependencies=[Depends(require_scope("files:write", "storage:admin"))])
@router.delete("/share-links/{token}", dependencies=[Depends(require_scope("files:write", "storage:admin"))])
async def revoke_share_link(
    token: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Revokes and deletes an existing share link."""
    async with _SHARE_LOCK:
        links = _load_share_links()
        if token not in links:
            raise HTTPException(status_code=404, detail="Share link not found")
        item = links[token]
        is_admin = principal.has_scope("superadmin") or principal.has_scope("storage:admin") or principal.has_scope("*")
        if not is_admin and item.get("created_by") != principal.username:
            raise HTTPException(status_code=403, detail="Cannot revoke share link created by another user")
        del links[token]
        _save_share_links(links)

    return {"status": "ok", "revoked": token}


_SHARE_PASSWORD_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>Shared file</title><style>body{font-family:system-ui;background:#0b0f14;
color:#e5e7eb;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}form{background:#111827;
padding:24px;border-radius:12px;width:min(320px,90vw)}input,button{width:100%;box-sizing:border-box;padding:10px;margin-top:10px;
border-radius:8px;border:1px solid #374151;background:#0b0f14;color:#fff}button{background:#0ea5e9;border:0;font-weight:700;
color:#000;cursor:pointer}</style></head><body><form method="post"><div>This shared item is password protected.</div>
<input type="password" name="password" autocomplete="current-password" placeholder="Password" required autofocus>
<button type="submit">Open</button></form></body></html>"""


@router.post("/fs/shared/{token}")
@router.post("/shared/{token}")
async def access_shared_file_with_password(token: str, request: Request, info: bool = False):
    """Same as the GET route, with the password in a form or JSON body instead of the URL (SEC-21)."""
    password = ""
    ctype = request.headers.get("content-type", "")
    try:
        if "application/json" in ctype:
            password = str((await request.json()).get("password") or "")
        else:
            # urlencoded form from the password page (no python-multipart dependency)
            from urllib.parse import parse_qs

            body = (await request.body())[:4096].decode("utf-8", errors="replace")
            password = (parse_qs(body).get("password") or [""])[0]
    except Exception:
        password = ""
    return await _serve_shared_item(token, request, info, password)


@router.get("/fs/shared/{token}")
@router.get("/shared/{token}")
async def access_shared_file(
    token: str,
    request: Request,
    info: bool = False,
):
    """
    Public access endpoint for shared files and folders (no session needed).
    Allows streaming the file or downloading a zip of a folder. A password goes in
    the X-Share-Password header or a POST body, never in the URL; browsers get a
    small password form.
    """
    return await _serve_shared_item(token, request, info, request.headers.get("X-Share-Password") or "")


def _share_creator_can_read(created_by: str | None, real_target: str) -> bool:
    """A link works only while the person who made it is active and can still read the item.
    Links saved before creators were recorded (no created_by) keep working."""
    if not created_by:
        return True
    from backend.users_db import get_user_by_username

    user = get_user_by_username(created_by)
    if not user or user.get("status") != "active":
        return False
    creator = AuthenticatedPrincipal(
        {
            "user_id": user["id"],
            "username": user["username"],
            "role_id": user.get("role_id"),
            "scopes": user.get("scopes") or [],
        }
    )
    return user_can_access_path(real_target, creator)


SHARE_ZIP_LIMIT = 5 * 1024**3
SHARE_ZIP_MAX_RUNNING = 2
SHARE_ZIP_SLOT_TTL = 6 * 3600  # a download that never started (client gone) frees its slot later
_SHARE_ZIP_ACTIVE: dict[str, float] = {}
_SHARE_ZIP_LOCK = threading.Lock()


def _share_zip_slot() -> str | None:
    """A slot for one folder download, or None when two are already running."""
    now = time.time()
    with _SHARE_ZIP_LOCK:
        for k in [k for k, t in _SHARE_ZIP_ACTIVE.items() if now - t > SHARE_ZIP_SLOT_TTL]:
            _SHARE_ZIP_ACTIVE.pop(k, None)
        if len(_SHARE_ZIP_ACTIVE) >= SHARE_ZIP_MAX_RUNNING:
            return None
        slot = secrets.token_hex(8)
        _SHARE_ZIP_ACTIVE[slot] = now
        return slot


def _release_share_zip_slot(slot: str) -> None:
    with _SHARE_ZIP_LOCK:
        _SHARE_ZIP_ACTIVE.pop(slot, None)


def _folder_size_capped(folder: str, limit: int) -> int:
    """Total size of a folder; raises ValueError as soon as it passes `limit`."""
    total = 0
    for root_dir, sub_dirs, files in os.walk(folder):
        prune_protected(root_dir, sub_dirs)
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root_dir, f))
            except OSError:
                continue
            if total > limit:
                raise ValueError("too large")
    return total


class _ZipSink:
    """A write-only stream for zipfile: the bytes written so far, handed out as they come."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.pos = 0

    def write(self, data) -> int:
        self.buf += data
        self.pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self.pos

    def flush(self) -> None:
        return None

    def take(self) -> bytes:
        out = bytes(self.buf)
        self.buf.clear()
        return out


def _stream_folder_zip(folder: str, slot: str = ""):
    """Yields a zip of `folder` while it is built; never holds more than one read buffer (SEC-9)."""
    folder_abs = os.path.realpath(folder)
    sink = _ZipSink()
    try:
        with zipfile.ZipFile(sink, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root_dir, sub_dirs, files in os.walk(folder):
                prune_protected(root_dir, sub_dirs)
                for f in files:
                    fp = os.path.join(root_dir, f)
                    real_fp = os.path.realpath(fp)
                    if not (real_fp == folder_abs or real_fp.startswith(folder_abs + os.sep)):
                        logger.warning(f"[Share Download] Skipping symlink outside shared directory: {fp} -> {real_fp}")
                        continue
                    rel = os.path.relpath(fp, os.path.dirname(folder))
                    try:
                        with open(fp, "rb") as src, zf.open(rel, "w", force_zip64=True) as dst:
                            while block := src.read(1024 * 1024):
                                dst.write(block)
                                if len(sink.buf) >= 256 * 1024:
                                    yield sink.take()
                    except OSError:
                        logger.warning(f"[Share Download] Skipping unreadable file {fp}", exc_info=True)
                    if sink.buf:
                        yield sink.take()
        if sink.buf:
            yield sink.take()
    finally:
        _release_share_zip_slot(slot)


async def _serve_shared_item(token: str, request: Request, info: bool, provided_pwd: str):
    from backend.rate_limit import hit as _rl_hit

    wait = _rl_hit(f"share.access:{_get_client_ip(request)}", 120, 60)
    if wait:
        raise HTTPException(
            status_code=429, detail=f"Too many requests. Try again in {wait}s.", headers={"Retry-After": str(wait)}
        )
    links = _load_share_links()
    if token not in links:
        raise HTTPException(status_code=404, detail="Share link not found or revoked")

    item = links[token]
    now = time.time()

    if item.get("expires_at") and now > item["expires_at"]:
        raise HTTPException(status_code=410, detail="Share link has expired")

    if item.get("max_downloads") and item.get("download_count", 0) >= item["max_downloads"]:
        raise HTTPException(status_code=410, detail="Download limit reached for this share link")

    client_ip = _get_client_ip(request)

    if item.get("has_password"):
        await _check_share_rate_limit(client_ip)
        if not provided_pwd:
            if "text/html" in request.headers.get("accept", "") and not info:
                return Response(content=_SHARE_PASSWORD_PAGE, media_type="text/html", status_code=401)
            raise HTTPException(
                status_code=401,
                detail="Password required to access this share",
                headers={"WWW-Authenticate": "ShareLink realm='Shared Resource'"},
            )
        expected_hash = item.get("password_hash") or ""
        if not verify_password(provided_pwd.strip(), expected_hash):
            await _record_failed_share_attempt(client_ip)
            raise HTTPException(status_code=401, detail="Incorrect password for this share link")
        await _reset_share_rate_limit(client_ip)

    target_path = item["path"]
    try:
        real_target = _contained(target_path, must_exist=True)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Underlying shared file or folder is no longer available") from None

    if resolve_within(real_target, ALLOWED_BROWSE_ROOTS) is None:
        raise HTTPException(status_code=403, detail="Target path is outside allowed system roots")
    if not _share_creator_can_read(item.get("created_by"), real_target):
        raise HTTPException(status_code=410, detail="This share link is no longer available")

    is_dir = os.path.isdir(real_target)

    if info:
        size = 0
        if not is_dir:
            try:
                size = os.path.getsize(real_target)
            except OSError:
                pass
        return {
            "token": token,
            "filename": item.get("filename", os.path.basename(real_target)),
            "label": item.get("label"),
            "is_dir": is_dir,
            "size_bytes": size,
            "has_password": bool(item.get("has_password")),
            "expires_at": item.get("expires_at"),
            "download_count": item.get("download_count", 0),
            "max_downloads": item.get("max_downloads"),
        }

    if is_dir:
        base_name = os.path.basename(real_target) or "shared_folder"
        # the size check walks the folder: in a thread, so a big folder never freezes the server
        try:
            await asyncio.to_thread(_folder_size_capped, real_target, SHARE_ZIP_LIMIT)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Shared folder exceeds maximum download size limit (5 GB)."
            ) from None
        slot = _share_zip_slot()
        if not slot:
            raise HTTPException(
                status_code=429,
                detail="Too many folder downloads at once. Try again in a minute.",
                headers={"Retry-After": "60"},
            )

    async with _SHARE_LOCK:
        cur_links = _load_share_links()
        if token in cur_links:
            cur_links[token]["download_count"] = cur_links[token].get("download_count", 0) + 1
            try:
                _save_share_links(cur_links)
            except HTTPException:
                logger.warning("[FS] Download count not saved; serving the download anyway")

    if is_dir:
        return StreamingResponse(
            _stream_folder_zip(real_target, slot),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{base_name}.zip"'},
        )
    else:
        media_type, _ = mimetypes.guess_type(real_target)
        if not media_type:
            media_type = "application/octet-stream"
        fname = os.path.basename(real_target)
        return FileResponse(
            real_target,
            media_type=media_type,
            filename=fname,
            headers={"Content-Disposition": f'inline; filename="{fname}"', **_user_file_headers(media_type)},
        )


# -------------------------------------------------------------------------
# Favorite folders (File Explorer sidebar), kept per user
# -------------------------------------------------------------------------

_FAVORITES_LOCK = threading.Lock()
_MAX_FAVORITES = 50


def _favorites_file() -> str:
    return os.path.join(config.DATA_DIR, "fm_favorites.json")


def _favorites_key(principal: AuthenticatedPrincipal | None) -> str:
    return ((principal.username if principal else "") or "_shared").lower()


def _load_favorites(principal: AuthenticatedPrincipal | None) -> list[dict[str, str]]:
    from backend.fsutil import read_json

    data = read_json(_favorites_file(), {})
    items = data.get(_favorites_key(principal), []) if isinstance(data, dict) else []
    return [i for i in items if isinstance(i, dict) and isinstance(i.get("path"), str)]


@json_locked(lambda *a, **k: _favorites_file())
def _save_favorites(principal: AuthenticatedPrincipal | None, items: list[dict[str, str]]) -> None:
    from backend.fsutil import atomic_write_json, read_json

    data = read_json(_favorites_file(), {})
    if not isinstance(data, dict):
        data = {}
    data[_favorites_key(principal)] = items
    atomic_write_json(_favorites_file(), data)


class FavoriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)
    name: str | None = Field(None, max_length=60)


@router.get("/fs/favorites", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))])
def fs_list_favorites(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """The signed-in user's favorite folders; ones that are gone or no longer allowed are marked."""
    out = []
    for fav in _load_favorites(principal):
        ok = True
        try:
            check_user_path_access(fav["path"], principal, allow_list=True)
            real = resolve_within(fav["path"], ALLOWED_BROWSE_ROOTS)
            ok = bool(real and os.path.isdir(real))
        except HTTPException:
            ok = False
        out.append({"path": fav["path"], "name": fav.get("name") or os.path.basename(fav["path"]), "available": ok})
    return {"favorites": out}


@router.post("/fs/favorites", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))])
def fs_add_favorite(req: FavoriteRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    path = req.path.rstrip("/") or "/"
    check_user_path_access(path, principal)
    real = resolve_within(path, ALLOWED_BROWSE_ROOTS)
    if real is None or not os.path.isdir(real):
        raise HTTPException(status_code=400, detail="Only folders inside the browsable locations can be favorites.")
    name = (req.name or "").strip() or os.path.basename(path) or path
    with _FAVORITES_LOCK:
        items = [f for f in _load_favorites(principal) if f["path"] != path]
        if len(items) >= _MAX_FAVORITES:
            raise HTTPException(status_code=400, detail=f"You can keep up to {_MAX_FAVORITES} favorites.")
        items.append({"path": path, "name": name})
        _save_favorites(principal, items)
    return {"status": "ok", "favorites": items}


@router.delete("/fs/favorites", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))])
def fs_remove_favorite(path: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    target = path.rstrip("/") or "/"
    with _FAVORITES_LOCK:
        items = [f for f in _load_favorites(principal) if f["path"] != target]
        _save_favorites(principal, items)
    return {"status": "ok", "favorites": items}
