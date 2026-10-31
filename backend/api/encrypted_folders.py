"""Encrypted folders inside a share (FEAT-13): make, open, lock, keep open at start, take off.

Who may open and lock one: the people on its own list (its maker at first, NSEC-5), or, for a
folder without a list, anyone who may write to its share; seeing it needs read on the share too.
Making one, choosing its people, keeping its password for the next start and taking it off need
shares:manage."""

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.rate_limit import rate_limit

router = APIRouter(prefix="/encrypted-folders", tags=["Storage"])
MANAGE = Depends(require_scope("shares:manage"))
# beside these, what the share allows is checked per folder (_can_use)
READ = Depends(require_scope("files:read", "shares:read", "shares:user_write", "storage:read", "storage:admin"))
WRITE = Depends(require_scope("files:write", "shares:manage", "shares:user_write", "storage:write", "storage:admin"))


class CreateIn(BaseModel):
    share: str = Field(max_length=128)
    name: str = Field(max_length=48)
    password: str = Field(min_length=1, max_length=256)
    unlock_at_start: bool = False


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class PeopleIn(BaseModel):
    people: list[str] | None = Field(default=None, max_length=64)  # None: everyone with the share


class StartIn(BaseModel):
    password: str | None = Field(default=None, max_length=256)  # None: forget the kept password


def _can_use(principal: AuthenticatedPrincipal, share: str, write: bool, name: str = "") -> bool:
    if principal.has_scope("shares:manage") or principal.has_scope("*"):
        return True
    from backend.services.encrypted_index import may_open

    if name and not may_open(name, principal.username or ""):
        return False
    from backend.services.app_catalog import share_mounts
    from backend.services.share_access import level_for

    path = share_mounts().get(share)
    level = level_for(principal.username or "", path) if path else "none"
    return level == "write" or (not write and level == "read")


def _errors(fn: Any, *args: Any) -> Any:
    from backend.services.encrypted_folders import EncryptedFolderError

    try:
        return fn(*args)
    except KeyError:
        raise HTTPException(status_code=404, detail="There is no such encrypted folder.") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except EncryptedFolderError as e:
        from backend.errors import ApiError

        text = str(e)
        slug = (
            "wrong_password"
            if "password is wrong" in text
            else "rate_limited"
            if "Too many wrong" in text
            else "folder_busy"
            if "file open" in text
            else "unavailable"
            if "no gocryptfs" in text
            else "conflict"
        )
        raise ApiError(409 if slug != "rate_limited" else 429, text, slug) from None


@router.get("", dependencies=[READ])
async def get_encrypted_folders(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """The encrypted folders in the shares this person can open, and whether this server can."""
    from backend.services import encrypted_folders as ef

    folders = await asyncio.to_thread(ef.listing)
    visible = [f for f in folders if await asyncio.to_thread(_can_use, principal, f["share"], False, f["name"])]
    manage = principal.has_scope("shares:manage") or principal.has_scope("*")
    shares: list[str] = []
    if manage:
        from backend.services.app_catalog import share_mounts

        shares = sorted(await asyncio.to_thread(share_mounts))
    return {
        "available": bool(ef.tool()) and os.path.exists("/dev/fuse"),
        "can_manage": manage,
        "shares": shares,
        "folders": visible,
    }


@router.post("", dependencies=[MANAGE])
async def post_encrypted_folder(
    req: CreateIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Makes one and opens it; the answer carries its recovery key, shown this once. Only its maker
    may open it until others are chosen (NSEC-5)."""
    from backend.services import encrypted_folders as ef

    return await asyncio.to_thread(
        _errors, ef.create, req.share, req.name, req.password, req.unlock_at_start, principal.username or ""
    )


@router.put("/{name}/people", dependencies=[MANAGE])
async def put_people(name: str, req: PeopleIn) -> dict[str, Any]:
    """Who may open and lock it: these accounts, or (null) everyone who may use its share."""
    from backend.services import encrypted_folders as ef

    return await asyncio.to_thread(_errors, ef.set_people, name, req.people)


@router.post("/adopt", dependencies=[MANAGE])
async def post_adopt_encrypted_folder(req: CreateIn) -> dict[str, Any]:
    """Adds back one whose encrypted files are already in the share."""
    from backend.services import encrypted_folders as ef

    return await asyncio.to_thread(_errors, ef.adopt, req.share, req.name, req.password)


@router.post("/{name}/unlock", dependencies=[WRITE, Depends(rate_limit("ef.unlock", 5, 60))])
async def post_unlock(
    name: str, req: PasswordIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    from backend.services import encrypted_folders as ef

    share = ef.share_of(name)
    if share is None:
        raise HTTPException(status_code=404, detail="There is no such encrypted folder.")
    if not await asyncio.to_thread(_can_use, principal, share, True, name):
        raise HTTPException(status_code=403, detail="You can't open this folder.")
    return await asyncio.to_thread(_errors, ef.unlock, name, req.password)


@router.post("/{name}/lock", dependencies=[WRITE])
async def post_lock(name: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    from backend.services import encrypted_folders as ef

    share = ef.share_of(name)
    if share is None:
        raise HTTPException(status_code=404, detail="There is no such encrypted folder.")
    if not await asyncio.to_thread(_can_use, principal, share, True, name):
        raise HTTPException(status_code=403, detail="You can't lock this folder.")
    return await asyncio.to_thread(_errors, ef.lock, name)


@router.put("/{name}/unlock-at-start", dependencies=[MANAGE])
async def put_unlock_at_start(name: str, req: StartIn) -> dict[str, Any]:
    from backend.services import encrypted_folders as ef

    return await asyncio.to_thread(_errors, ef.set_unlock_at_start, name, req.password)


@router.delete("/{name}", dependencies=[MANAGE])
async def delete_encrypted_folder(name: str) -> dict[str, Any]:
    """Takes a locked folder off ZettNAS; its encrypted files stay in the share."""
    from backend.services import encrypted_folders as ef

    return await asyncio.to_thread(_errors, ef.forget, name)
