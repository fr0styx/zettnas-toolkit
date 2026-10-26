"""File search below a folder.

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.fsutil import is_protected, resolve_within
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, check_user_path_access, user_can_access_path

router = APIRouter()


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
