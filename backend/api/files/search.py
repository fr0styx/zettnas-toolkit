"""File search below a folder.

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import os
import time

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.fsutil import is_protected, resolve_within
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, check_user_path_access, user_can_access_path

router = APIRouter()

# File-name search (PERF-25): the AI index answers for the folders it covers, a live walk adds
# the rest without ever waking a sleeping disk, and the whole result is kept for a minute so
# the next page doesn't walk again.
MAX_SCANNED = 10000
SEARCH_CACHE_SECS = 60.0
_SEARCH_CACHE: dict[tuple, tuple[float, list[dict], str | None]] = {}


def _remember(key: tuple, matched: list[dict], partial: str | None) -> None:
    if len(_SEARCH_CACHE) >= 32:
        _SEARCH_CACHE.pop(next(iter(_SEARCH_CACHE)))
    _SEARCH_CACHE[key] = (time.monotonic(), matched, partial)


def _asleep(root: str) -> bool:
    try:
        from backend.services.rag_standby import is_backing_disk_in_standby

        return bool(is_backing_disk_in_standby(root))
    except Exception:
        return False


def _index_hits(root: str, query: str, recursive: bool, principal) -> list[dict]:
    """Names from the AI index under `root` (no disk access); [] when there is no index."""
    try:
        from backend.services import rag_engine

        engine = rag_engine._RAG_ENGINE  # only an index that is already open; never start one here
        if engine is None or not os.path.exists(engine.db_path):
            return []
        conn = engine._get_conn(readonly=True)
    except Exception:
        return []
    base = root.rstrip("/") or "/"
    like = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
    try:
        if recursive:
            rows = conn.execute(
                "SELECT canonical_path, file_name, size_bytes, mtime_ns FROM indexed_files "
                "WHERE canonical_path LIKE ? ESCAPE '\\' AND instr(lower(file_name), ?) > 0 LIMIT 5000",
                (like, query),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT canonical_path, file_name, size_bytes, mtime_ns FROM indexed_files "
                "WHERE parent_dir = ? AND instr(lower(file_name), ?) > 0 LIMIT 5000",
                (base, query),
            ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    out = []
    for path, name, size, mtime_ns in rows:
        rel = path[len(base) :].lstrip("/")
        if any(part.startswith(".") for part in rel.split("/")) or is_protected(path):
            continue
        if not user_can_access_path(path, principal, allow_list=True):
            continue
        out.append(
            {"name": name, "path": path, "is_dir": False, "size": int(size or 0), "mtime": (mtime_ns or 0) / 1e9}
        )
    return out


def _walk(root: str, query: str, recursive: bool, principal, budget: list[int]) -> list[dict]:
    matched = []
    queue = [(root, 0)]
    while queue and budget[0] > 0:
        curr_dir, depth = queue.pop(0)
        try:
            with os.scandir(curr_dir) as it:
                for entry in it:
                    budget[0] -= 1
                    if budget[0] <= 0:
                        break
                    if entry.name.startswith(".") or is_protected(entry.path):
                        continue
                    if not user_can_access_path(entry.path, principal, allow_list=True):
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)
                    if query in entry.name.lower():
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
                        except OSError:
                            pass
                    if recursive and is_dir and depth < 8 and not entry.is_symlink():
                        queue.append((entry.path, depth + 1))
        except OSError:
            continue
    return matched


def _search(roots: list[str], query: str, recursive: bool, principal) -> tuple[list[dict], str | None]:
    matched: list[dict] = []
    seen: set[str] = set()
    partial: str | None = None
    budget = [MAX_SCANNED]
    for root in roots:
        if _asleep(root):
            partial = "asleep"  # only the index answers for a sleeping disk
            found = _index_hits(root, query, recursive, principal)
        else:
            found = _walk(root, query, recursive, principal, budget)
            if budget[0] <= 0:
                partial = partial or "capped"
                found += _index_hits(root, query, recursive, principal)  # the index covers the rest
        for item in found:
            if item["path"] not in seen:
                seen.add(item["path"])
                matched.append(item)
    return matched, partial


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
        key = (principal.username if principal else "", tuple(search_roots), query, recursive)
        hit = _SEARCH_CACHE.get(key) if offset > 0 else None  # a first page is always fresh
        if hit and time.monotonic() - hit[0] < SEARCH_CACHE_SECS:
            matched, partial = hit[1], hit[2]  # a later page of the same search: no new walk
        else:
            matched, partial = _search(search_roots, query, recursive, principal)
            _remember(key, matched, partial)
        return {
            "items": matched[offset : offset + limit],
            "total": len(matched),
            "query": q,
            "limit": limit,
            "offset": offset,
            # "asleep": a folder's disk was in standby, so only what the index knows of it is
            # here; "capped": the walk stopped at its entry limit (PERF-25)
            "partial": partial,
        }

    return await asyncio.to_thread(_execute_search)
