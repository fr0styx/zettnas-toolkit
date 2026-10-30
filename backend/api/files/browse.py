"""Folder listings (local and remote), the browsable roots and new folders.

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import json
import os
import stat
import subprocess
import sys
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import backend.config as config
from backend.api.files.common import _contained
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.fsutil import is_protected, resolve_within, root_for
from backend.ignored_errors import ignored
from backend.models.schemas import MkdirRequest
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, _is_files_admin, check_user_path_access

router = APIRouter()


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


def _bin_view(real: str, principal: AuthenticatedPrincipal | None) -> dict[str, Any]:
    """A Recycle Bin opened in the File Explorer shows every bin's items this person may open,
    newest first: each share has its own bin, and the sidebar's is only the top one (REL-15)."""
    from backend.api.files.trash import bin_listing

    out = []
    listing = bin_listing(principal) if principal else {"items": [], "asleep": []}
    for item in listing["items"]:
        out.append(
            {
                "name": item["name"],
                "path": item["path"],
                "is_dir": item["is_dir"],
                "size": item["size"],
                "mtime": float(item["deleted_at"]),
                "mode": "0755" if item["is_dir"] else "0644",
                "is_symlink": False,
                "ext": "" if item["is_dir"] else os.path.splitext(item["name"])[1].lower(),
                "trash_id": item["id"],
                "original_path": item["original_path"] or "",
            }
        )
    return {
        "current": real,
        "roots": list(ALLOWED_BROWSE_ROOTS),
        "dirs": out,
        "recycle_bin": True,
        "bins_asleep": len(listing.get("asleep") or []),
    }


def _handle_browse_logic(path: str, dirs_only: bool, principal: AuthenticatedPrincipal | None = None):
    real = _contained(path or ALLOWED_BROWSE_ROOTS[0])
    if os.path.basename(real.rstrip("/")) == ".RecycleBin" and not dirs_only:
        return _bin_view(real, principal)
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
    scanned_entries: list[Any] = []  # DirEntry objects from scandir, names from listdir
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

    # the app's own folders are never listed (SEC-3), nor the Recycle Bins: they have their own view (REL-15)
    scanned_entries = [
        e
        for e in scanned_entries
        if (e.name if use_scandir else str(e)) != ".RecycleBin"
        and not is_protected(os.path.join(real, e.name if use_scandir else str(e)))
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
            ignored("backend.api.fs._handle_browse_logic_unfiltered")

    return {"current": real, "roots": list(ALLOWED_BROWSE_ROOTS), "dirs": out}


@router.get("/browse")
async def browse(
    path: str = "",
    dirs_only: str = "0",
    limit: int | None = None,
    offset: int = 0,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """A folder's entries. With `limit`, one page of them and the `total` (PERF-25); without it,
    all of them as before."""
    check_user_path_access(path, principal, allow_list=True)
    result = await asyncio.to_thread(_handle_browse_logic, path, dirs_only == "1", principal)
    if limit is not None and isinstance(result, dict) and isinstance(result.get("dirs"), list):
        entries = result["dirs"]
        start = max(0, offset)
        result = {
            **result,
            "dirs": entries[start : start + max(1, min(limit, 5000))],
            "total": len(entries),
            "offset": start,
        }
    return result


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
    res = _do_mkdir(req.path)
    from backend.api.files.common import record_activity

    record_activity("mkdir", res.get("path") or req.path, principal)
    return res
