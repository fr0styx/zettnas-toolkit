"""Invite links: an administrator creates a one-time link with a role; the person opens it,
picks a username and password, and their account and private folder are created (Batch 6)."""

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, require_scope
from backend.config import logger
from backend.users_db import (
    accept_invite,
    create_invite,
    delete_invite,
    get_role,
    list_invites,
    lookup_invite,
)

router = APIRouter(tags=["Invites"])
_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
INVITABLE_ROLES = ("share_user", "kid", "guest", "backup_operator", "app_operator", "auditor")


class InviteIn(BaseModel):
    role_id: str = "share_user"
    days: int = Field(default=7, ge=1, le=90)
    max_uses: int = Field(default=1, ge=1, le=50)
    note: str = Field(default="", max_length=120)
    quota_gb: int = Field(default=0, ge=0, le=100000)


class AcceptIn(BaseModel):
    username: str = Field(min_length=2, max_length=32, pattern=r"^[a-z_][a-z0-9_.-]*$")
    display_name: str = Field(default="", max_length=80)
    password: str = Field(min_length=8, max_length=256)


def _limit(request: Request) -> None:
    ip = request.client.host if request.client else "?"
    now = time.time()
    _ATTEMPTS[ip] = [t for t in _ATTEMPTS[ip] if now - t < 3600]
    if len(_ATTEMPTS[ip]) >= 20:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    _ATTEMPTS[ip].append(now)


@router.post("/invites")
def new_invite(req: InviteIn, principal: AuthenticatedPrincipal = Depends(require_scope("users:write"))):  # noqa: B008
    if req.role_id not in INVITABLE_ROLES or not get_role(req.role_id):
        raise HTTPException(status_code=400, detail="That role can't be given by invite.")
    from backend.api.auth import _role_within

    if not _role_within(list(principal.scopes or []), req.role_id):
        # SEC-26: an invite can't hand out more than its creator can do
        raise HTTPException(status_code=403, detail="You can't invite someone into a role with more rights than yours.")
    token, invite = create_invite(
        req.role_id, req.days, req.max_uses, req.note, principal.username, req.quota_gb * 1024**3
    )
    # the token is shown once; only its hash is stored
    return {"invite": invite, "token": token, "link": f"/#/invite/{token}"}


@router.get("/invites", dependencies=[Depends(require_scope("users:read", "users:write"))])
def get_invites():
    return {"invites": list_invites()}


@router.delete("/invites/{invite_id}", dependencies=[Depends(require_scope("users:write"))])
def revoke(invite_id: str):
    if not delete_invite(invite_id):
        raise HTTPException(status_code=404, detail="No such invite.")
    return {"status": "revoked"}


@router.get("/invite/{token}")
def check_invite(token: str, request: Request):
    """Public: whether an invite link is still valid, and for which role."""
    _limit(request)
    inv = lookup_invite(token)
    if not inv:
        raise HTTPException(status_code=404, detail="This invite link is not valid any more.")
    role = get_role(inv["role_id"]) or {}
    return {"valid": True, "role": role.get("name", inv["role_id"]), "expires_at": inv["expires_at"]}


@router.post("/invite/{token}/accept")
def accept(token: str, req: AcceptIn, request: Request):
    """Public: creates the account an invite allows, and the person's private folder."""
    _limit(request)
    from backend.password_policy import password_problem

    problem = password_problem(req.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    try:
        user = accept_invite(token, req.username, req.display_name or req.username, req.password)
    except LookupError:
        raise HTTPException(status_code=404, detail="This invite link is not valid any more.") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    try:
        from backend.services.user_spaces import ensure_home

        ensure_home(user["username"], int(user.get("storage_quota_bytes") or 0))
    except Exception:
        logger.warning("[Invites] could not create the private folder", exc_info=True)
    return {"status": "ok", "username": user["username"]}
