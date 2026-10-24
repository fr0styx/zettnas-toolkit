"""Who may read or write which paths (SEC-10). Used by the file API, the AI index and VMs.

Lives in the service layer so services don't import the API (ARCH-2).
"""

import os
from typing import Any

from fastapi import HTTPException

import backend.config as config
from backend.auth import AuthenticatedPrincipal
from backend.fsutil import resolve_within


class _AllowedBrowseRootsProxy:
    """The browsable roots, read from config on every use (settings and tests can change them)."""

    def _get_list(self):
        roots = getattr(config, "ALLOWED_BROWSE_ROOTS", None)
        if roots is not None and not isinstance(roots, _AllowedBrowseRootsProxy):
            return list(roots)
        return ["/mnt/user", "/mnt/remotes"]

    def __iter__(self):
        return iter(self._get_list())

    def __getitem__(self, item):
        return self._get_list()[item]

    def __len__(self):
        return len(self._get_list())

    def __contains__(self, item):
        return item in self._get_list()

    def __bool__(self):
        return bool(self._get_list())

    def __repr__(self):
        return repr(self._get_list())


ALLOWED_BROWSE_ROOTS = _AllowedBrowseRootsProxy()


def _is_files_admin(principal: AuthenticatedPrincipal | None) -> bool:
    return bool(
        principal
        and (
            principal.has_scope("superadmin")
            or principal.has_scope("storage:admin")
            or principal.has_scope("shares:manage")
            or principal.has_scope("*")
        )
    )


def check_user_path_access(
    req_path: str, principal: AuthenticatedPrincipal | None, write: bool = False, allow_list: bool = False
) -> None:
    """Non-admins only reach their home and shares granted to them (SEC-10); write needs write access.

    A folder above a granted share (the pool root, "homes") has level "list": it can be
    browsed to reach the share, but it is not readable. Only listing-type callers pass
    allow_list=True; anything that reads, copies, zips or shares content does not.
    """
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if _is_files_admin(principal):
        return
    raw_path = str(req_path or "").strip()
    raw_norm = os.path.normpath(raw_path).replace("\\", "/")
    candidates = [raw_norm]
    # Only resolve symlinks for absolute paths: realpath() on a relative path
    # resolves against the server's working directory, not a browse root.
    if os.path.isabs(raw_path):
        candidates.append(os.path.normpath(os.path.realpath(raw_path)).replace("\\", "/"))
    for candidate_path in candidates:
        parts = [p for p in candidate_path.split("/") if p]
        if parts and parts[0] == "boot":
            raise HTTPException(status_code=403, detail="Access to /boot requires storage:admin privileges.")
        if "appdata" in parts:
            idx_app = parts.index("appdata")
            if idx_app == 0 or (idx_app > 0 and parts[0] == "mnt"):
                raise HTTPException(status_code=403, detail="Access to appdata requires storage:admin privileges.")
        if "homes" in parts:
            idx_homes = parts.index("homes")
            if idx_homes + 1 < len(parts):
                target_user = parts[idx_homes + 1].lower()
                current_user = (principal.username or "").lower()
                if target_user != current_user:
                    raise HTTPException(status_code=403, detail="Access denied to another user home folder.")

    if not raw_path:
        if write:
            raise HTTPException(status_code=403, detail="Choose a folder you can write to.")
        return  # default root listing; entries are filtered by share access
    real = os.path.realpath(raw_path) if os.path.isabs(raw_path) else resolve_within(raw_path, ALLOWED_BROWSE_ROOTS)
    if not real:
        return  # _contained() answers 403/404 for paths outside the roots
    from backend.services.share_access import level_for

    level = level_for(principal.username or "", real)
    if level == "none" or (level == "list" and not allow_list):
        raise HTTPException(status_code=403, detail="You don't have access to this folder.")
    if write and level != "write":
        raise HTTPException(status_code=403, detail="You have read-only access to this folder.")


def indexed_path_checker(principal: AuthenticatedPrincipal | None) -> Any:
    """Read access for file paths taken from the AI index, without touching the disks.

    Same rules as check_user_path_access, applied to the stored canonical path, with the
    user's share grants loaded once. Returns a function path -> bool (cached per path).
    """
    if not principal:
        return lambda _path: False
    if _is_files_admin(principal):
        return lambda _path: True
    from backend.services.share_access import file_level, grants_for

    username = (principal.username or "").lower()
    grants = grants_for(username) if username else []
    cache: dict[str, bool] = {}

    def readable(path: str) -> bool:
        ok = cache.get(path)
        if ok is None:
            ok = cache[path] = _indexed_readable(path, username, grants, file_level)
        return ok

    return readable


def _indexed_readable(path: str, username: str, grants: list[tuple[str, str]], file_level: Any) -> bool:
    norm = os.path.normpath(str(path or "")).replace("\\", "/")
    if not username or not norm.startswith("/"):
        return False
    parts = [p for p in norm.split("/") if p]
    if parts and parts[0] == "boot":
        return False
    if "appdata" in parts:
        idx_app = parts.index("appdata")
        if idx_app == 0 or parts[0] == "mnt":
            return False
    if "homes" in parts:
        idx_homes = parts.index("homes")
        if idx_homes + 1 < len(parts) and parts[idx_homes + 1].lower() != username:
            return False
    return file_level(username, norm, grants) in ("read", "write")


def user_can_access_path(req_path: str, principal: AuthenticatedPrincipal | None, allow_list: bool = False) -> bool:
    try:
        check_user_path_access(req_path, principal, allow_list=allow_list)
        return True
    except HTTPException:
        return False
