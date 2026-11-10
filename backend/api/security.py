"""Ransomware guard, IP block-list and two-step sign-in policy endpoints (M4, M5)."""

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import require_confirmation
from backend.services import ip_block, mfa_policy
from backend.services.ransomware_guard import get_guard

router = APIRouter(prefix="/security", tags=["Security"])


class GuardSettings(BaseModel):
    enabled: bool | None = None
    canaries: bool | None = None
    rename_delete_limit: int | None = Field(default=None, ge=3, le=100000)
    suspicious_limit: int | None = Field(default=None, ge=3, le=100000)


class MfaPolicyIn(BaseModel):
    required_roles: list[str] = Field(default_factory=list, max_length=64)


class BlockRequest(BaseModel):
    ip: str = Field(..., max_length=64)
    reason: str = Field(default="blocked by an admin", max_length=200)
    hours: float | None = Field(default=None, ge=0.1, le=24 * 365)


@router.get("/ransomware", dependencies=[Depends(require_scope("system:view", "audit:read"))])
def ransomware_status() -> dict[str, Any]:
    return get_guard().status()


@router.put("/ransomware", dependencies=[Depends(require_scope("system:config"))])
def ransomware_settings(req: GuardSettings) -> dict[str, Any]:
    return get_guard().update_settings(**req.model_dump())


@router.post("/ransomware/unfreeze", dependencies=[Depends(require_scope("system:config"))])
def ransomware_unfreeze(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    return get_guard().unfreeze(by=principal.username)


@router.get("/ip-blocks", dependencies=[Depends(require_scope("system:view", "audit:read"))])
def list_ip_blocks() -> list[dict[str, Any]]:
    return ip_block.list_blocks()


@router.post("/ip-blocks", dependencies=[Depends(require_scope("system:config"))])
def add_ip_block(req: BlockRequest) -> dict[str, Any]:
    try:
        ipaddress.ip_address(req.ip)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not an IP address") from None
    seconds = int(req.hours * 3600) if req.hours else None
    if not ip_block.block(req.ip, req.reason, seconds=seconds):
        raise HTTPException(status_code=400, detail="Loopback and trusted addresses can't be blocked")
    return {"status": "ok"}


@router.delete("/ip-blocks/{ip}", dependencies=[Depends(require_scope("system:config"))])
def remove_ip_block(ip: str) -> dict[str, Any]:
    if not ip_block.unblock(ip):
        raise HTTPException(status_code=404, detail="Not blocked")
    return {"status": "ok"}


@router.post(
    "/rotate-secret-key",
    dependencies=[Depends(require_scope("*")), Depends(require_confirmation("security.rotate_key"))],
)
def rotate_secret_key_route():
    """Replaces the install's secret key and re-encrypts two-factor secrets and backup passphrases.
    Use it when someone may have copied the data folder."""
    from backend.services.key_rotation import rotate_secret_key

    try:
        return {"status": "ok", **rotate_secret_key()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


def _mfa_policy_view() -> dict[str, Any]:
    from backend.services import passkeys
    from backend.users_db import list_users

    with_passkey = passkeys.users_with_passkeys()  # a passkey is a second step too (RES-3)
    people: dict[str, int] = {}  # per role: active people without two-step sign-in (not directory sign-ins)
    for u in list_users():
        protected = u.get("mfa_enabled") or u["id"] in with_passkey
        if u.get("status", "active") == "active" and not protected and u.get("idp_type") != "oidc":
            people[u["role_id"]] = people.get(u["role_id"], 0) + 1
    return {"required_roles": sorted(mfa_policy.required_roles()), "without_two_step": people}


@router.get("/mfa-policy", dependencies=[Depends(require_scope("system:view", "audit:read"))])
def get_mfa_policy() -> dict[str, Any]:
    """Which roles must use two-step sign-in; per role, how many people still have to set it up."""
    return _mfa_policy_view()


@router.put("/mfa-policy", dependencies=[Depends(require_scope("system:config"))])
def put_mfa_policy(
    req: MfaPolicyIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    from backend.services import passkeys
    from backend.users_db import get_role, get_user_by_id, log_security_event

    unknown = [r for r in req.required_roles if not get_role(r)]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown role: {', '.join(unknown)}")
    me = get_user_by_id(principal.user_id) if principal.user_id else None
    if (
        me
        and me.get("role_id") in req.required_roles
        and not me.get("mfa_enabled")
        and not passkeys.has_passkeys(me["id"])
        and not (me.get("idp_type") == "oidc" and not me.get("password_hash"))
    ):
        raise HTTPException(
            status_code=409,
            detail="Turn on two-step sign-in for yourself first: your own role would require it.",
        )
    roles = mfa_policy.set_required_roles(req.required_roles)
    log_security_event(
        "security.mfa_policy.update",
        "success",
        actor_id=principal.user_id,
        actor_username=principal.username,
        details={"required_roles": roles},
    )
    return _mfa_policy_view()
