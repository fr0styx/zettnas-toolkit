"""Favorite folders in the File Explorer sidebar.

Part of backend/api/fs.py, split out by ARC-5."""

import os
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import backend.config as config
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.fsutil import json_locked, resolve_within
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, check_user_path_access

router = APIRouter()


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
