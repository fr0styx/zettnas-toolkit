"""The file API's router and the helpers its areas share: path checks, file headers, task ownership.

Part of backend/api/fs.py, split out by ARC-5."""

import os
from typing import Any

from fastapi import HTTPException

from backend.auth import AuthenticatedPrincipal
from backend.config import logger
from backend.fsutil import resolve_within
from backend.ignored_errors import ignored
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, _is_files_admin

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    ignored("backend.api.fs.<module>")


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


def _observe(kind: str, path: str, principal: Any, new_path: str = "") -> None:
    """Feeds file-manager changes to the ransomware guard (M4)."""
    from backend.auth import CLIENT_IP_CTX
    from backend.services.ransomware_guard import get_guard

    get_guard().observe(
        kind, path, user=getattr(principal, "username", "") or "", ip=CLIENT_IP_CTX.get(), new_path=new_path
    )


def record_activity(action: str, path: str, principal: Any, target: str = "", detail: str = "") -> None:
    """Adds the change to the file activity log (FEAT-12)."""
    from backend.services import file_activity

    file_activity.record(action, path, principal, target=target, detail=detail)


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


def _task_owner_filter(principal: AuthenticatedPrincipal | None) -> str | None:
    """None (see every task) for admins, else the caller's username (SEC-11)."""
    return None if _is_files_admin(principal) else (principal.username or "").lower() if principal else ""


def _assert_task_owner(task_id: str, principal: AuthenticatedPrincipal | None) -> None:
    from backend.services.fs_transfer import transfer_manager

    owner = _task_owner_filter(principal)
    if owner is not None and transfer_manager.owner_of(task_id) not in (owner,):
        raise HTTPException(status_code=404, detail="Task not found")
