"""Passkeys (RES-3): add and remove your own, and sign in with one, alone or after the password."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.api.auth import (
    _build_session_response,
    _client_ip,
    _lockout_remaining,
    _rate_limited,
    _register_failure,
    _role_within,
    verify_mfa_token,
)
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.errors import error_response
from backend.services import passkeys
from backend.users_db import get_user_by_id, log_security_event

router = APIRouter(tags=["Authentication"])


class RegisterIn(BaseModel):
    ticket: str = Field(min_length=8, max_length=128)
    credential: dict[str, Any]
    name: str = Field(default="", max_length=60)


class LoginOptionsIn(BaseModel):
    mfa_token: str = Field(
        default="", max_length=2048, description="After the password: the passkey is the second step"
    )
    remember_me: bool = False


class LoginIn(BaseModel):
    ticket: str = Field(min_length=8, max_length=128)
    credential: dict[str, Any]


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def _me(principal: Any) -> dict[str, Any] | None:
    uid = getattr(principal, "user_id", None)
    if not uid or getattr(principal, "is_api_token", False) or getattr(principal, "is_system", False):
        return None  # a person signed in to Kiboto, not an API token
    return get_user_by_id(uid)


def _host(request: Request) -> str:
    return request.headers.get("host", "")


def _fail(err: Exception, status: int = 400):
    return error_response(status, str(err), error="passkey_failed")


@router.get("/auth/passkeys")
def list_passkeys(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Your passkeys, and the name passkeys made on this address belong to."""
    user = _me(principal)
    if not user:
        return error_response(403, "Passkeys belong to a person signed in to Kiboto.", error="not_a_person")
    return {"passkeys": passkeys.list_for(user["id"])}


@router.post("/auth/passkeys/options")
def passkey_register_options(request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """What the browser needs to make a passkey for you on this address."""
    user = _me(principal)
    if not user:
        return error_response(403, "Passkeys belong to a person signed in to Kiboto.", error="not_a_person")
    try:
        return passkeys.register_options(user, _host(request))
    except passkeys.PasskeyError as e:
        return _fail(e)


@router.post("/auth/passkeys")
def passkey_register(
    req: RegisterIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Saves the passkey the browser made."""
    user = _me(principal)
    if not user:
        return error_response(403, "Passkeys belong to a person signed in to Kiboto.", error="not_a_person")
    try:
        added = passkeys.register_finish(user, req.ticket, req.credential, req.name)
    except passkeys.PasskeyError as e:
        return _fail(e)
    log_security_event(
        "auth.passkey.added",
        "success",
        actor_id=user["id"],
        actor_username=user["username"],
        actor_ip=_client_ip(request),
        details={"name": added["name"]},
    )
    return {"added": added, "passkeys": passkeys.list_for(user["id"])}


@router.patch("/auth/passkeys/{pk_id}")
def passkey_rename(pk_id: str, req: RenameIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    user = _me(principal)
    if not user:
        return error_response(403, "Passkeys belong to a person signed in to Kiboto.", error="not_a_person")
    try:
        if not passkeys.rename(user["id"], pk_id, req.name):
            return error_response(404, "No such passkey.", error="not_found")
    except passkeys.PasskeyError as e:
        return _fail(e)
    return {"passkeys": passkeys.list_for(user["id"])}


@router.delete("/auth/passkeys/{pk_id}")
def passkey_delete(pk_id: str, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Removes one of your passkeys. The last one goes only if a code still protects the account where
    your role requires two-step sign-in."""
    user = _me(principal)
    if not user:
        return error_response(403, "Passkeys belong to a person signed in to Kiboto.", error="not_a_person")
    from backend.services import mfa_policy

    mine = passkeys.list_for(user["id"])
    if (
        len(mine) == 1
        and mine[0]["id"] == pk_id
        and not user.get("mfa_enabled")
        and user.get("role_id") in mfa_policy.required_roles()
    ):
        return error_response(
            409,
            "Your role requires two-step sign-in: turn on the code first, or add another passkey.",
            error="last_second_step",
        )
    if not passkeys.delete(user["id"], pk_id):
        return error_response(404, "No such passkey.", error="not_found")
    log_security_event(
        "auth.passkey.removed",
        "success",
        actor_id=user["id"],
        actor_username=user["username"],
        actor_ip=_client_ip(request),
    )
    return {"passkeys": passkeys.list_for(user["id"])}


@router.post("/auth/passkey/login/options")
def passkey_login_options(req: LoginOptionsIn, request: Request):
    """A challenge to sign in with a passkey: any passkey on this address, or, with the token the
    password step gave, one of that person's own."""
    ip = _client_ip(request)
    remaining = _lockout_remaining(ip)
    if remaining > 0:
        return _rate_limited(remaining)
    user_id = ""
    remember = req.remember_me
    if req.mfa_token:
        token = verify_mfa_token(req.mfa_token)
        if not token:
            return error_response(
                401, "Invalid or expired MFA session. Please log in again.", error="invalid_mfa_token"
            )
        user_id, remember = token.get("uid", ""), bool(token.get("rm", False))
    try:
        return passkeys.login_options(_host(request), user_id, {"remember_me": remember})
    except passkeys.PasskeyError as e:
        return _fail(e)


@router.post("/auth/passkey/login")
async def passkey_login(req: LoginIn, request: Request):
    """Signs in with the signed challenge (counts as both steps: the device checked who you are)."""
    ip = _client_ip(request)
    remaining = _lockout_remaining(ip)
    if remaining > 0:
        return _rate_limited(remaining)
    try:
        user_id, extra = await run_in_threadpool(passkeys.login_finish, req.ticket, req.credential)
    except passkeys.PasskeyError as e:
        _register_failure(ip, is_ip=True)
        log_security_event("auth.passkey.failure", "failure", actor_ip=ip, details={"reason": str(e)[:120]})
        return _fail(e, 401)
    user = await run_in_threadpool(get_user_by_id, user_id)
    if not user or user.get("status") != "active":
        return error_response(403, "Account is disabled or locked.", error="account_disabled")
    return _build_session_response(user, bool(extra.get("remember_me")), request, method="passkey")


@router.delete("/users/{user_id}/passkeys", dependencies=[Depends(require_scope("users:write"))])
def admin_remove_passkeys(
    user_id: str, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Removes every passkey of a person who lost their devices (an administrator, for an account whose
    role they could give)."""
    target = get_user_by_id(user_id)
    if not target:
        return error_response(404, "No such person.", error="not_found")
    if not _role_within(list(getattr(principal, "scopes", None) or []), target.get("role_id")):
        return error_response(403, "That account can do more than you can.", error="forbidden")
    removed = len(passkeys.list_for(user_id))
    passkeys.forget_user(user_id)
    log_security_event(
        "auth.passkey.reset",
        "success",
        actor_id=getattr(principal, "user_id", None),
        actor_username=getattr(principal, "username", None),
        actor_ip=_client_ip(request),
        details={"user": target["username"], "removed": removed},
    )
    return {"removed": removed}
