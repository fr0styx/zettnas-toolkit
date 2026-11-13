"""Invite links: an administrator creates a one-time link with a role; the person opens it,
picks a username and password, and their account and private folder are created (Batch 6)."""

import json
import time
from collections import defaultdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, require_scope
from backend.config import logger
from backend.users_db import (
    accept_invite,
    create_invite,
    delete_invite,
    get_role,
    invite_extras,
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
    # SET-19 (Users decision 11): what the person gets with the role
    shares: dict[str, Literal["read", "write"]] = Field(default_factory=dict, max_length=100)
    signin_hours: dict[str, Any] | None = None


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


def _checked_extras(req: InviteIn, principal: AuthenticatedPrincipal) -> dict[str, Any] | None:
    """The invite's sign-in hours, normalized; raises for folders or hours it may not give."""
    if req.shares:
        if not principal.has_scope("shares:manage"):
            raise HTTPException(
                status_code=403, detail="Only someone who manages shared folders can give folders by invite."
            )
        from backend.services.share_access import known_shares

        unknown = sorted(set(req.shares) - {s["name"] for s in known_shares()})
        if unknown:
            raise HTTPException(status_code=400, detail=f"No such shared folder: {', '.join(unknown)}.")
    if not req.signin_hours:
        return None
    from backend.auth import has_scope
    from backend.signin_hours import normalize

    role_scopes = json.loads((get_role(req.role_id) or {}).get("scopes_json") or "[]")
    if has_scope(role_scopes, "users:write"):
        raise HTTPException(
            status_code=400, detail="Sign-in hours are for family accounts, not for people who manage accounts."
        )
    try:
        return normalize(req.signin_hours)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post("/invites")
def new_invite(req: InviteIn, principal: AuthenticatedPrincipal = Depends(require_scope("users:write"))):  # noqa: B008
    if req.role_id not in INVITABLE_ROLES or not get_role(req.role_id):
        raise HTTPException(status_code=400, detail="That role can't be given by invite.")
    from backend.api.auth import _role_within

    if not _role_within(list(principal.scopes or []), req.role_id):
        # SEC-26: an invite can't hand out more than its creator can do
        raise HTTPException(status_code=403, detail="You can't invite someone into a role with more rights than yours.")
    hours = _checked_extras(req, principal)
    token, invite = create_invite(
        req.role_id,
        req.days,
        req.max_uses,
        req.note,
        principal.username,
        req.quota_gb * 1024**3,
        shares=dict(req.shares),
        signin_hours=hours,
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
    # role_id lets the page name the role in the person's language; "role" alone read "ShareUser"
    return {
        "valid": True,
        "role": role.get("name", inv["role_id"]),
        "role_id": inv["role_id"],
        "expires_at": inv["expires_at"],
        **invite_extras(inv),  # what comes with it, so the page can say so (SET-19)
    }


@router.post("/invite/{token}/accept")
def accept(token: str, req: AcceptIn, request: Request):
    """Public: creates the account an invite allows, and the person's private folder."""
    _limit(request)
    from backend.password_policy import password_problem

    problem = password_problem(req.password)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    extras = invite_extras(lookup_invite(token) or {})
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
    _give_extras(user, extras)
    return {"status": "ok", "username": user["username"]}


def _give_extras(user: dict[str, Any], extras: dict[str, Any]) -> None:
    """The invite's sign-in hours and folders, for the new account (SET-19). A failure leaves the
    account as the role makes it and is logged; an administrator can set both afterwards."""
    if extras["signin_hours"]:
        from backend.users_db import update_user_profile

        update_user_profile(user["id"], signin_hours=extras["signin_hours"])
    if extras["shares"]:
        from backend.services import share_access
        from backend.services.samba_engine import refresh_access

        try:
            share_access.grant(user["username"], extras["shares"])
            refresh_access()  # SMB follows share access (SEC-28)
        except (ValueError, OSError):
            logger.warning("[Invites] could not give the invite's folders", exc_info=True)
