"""OpenID Connect sign-in endpoints (M6)."""

import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.config import logger
from backend.services import oidc

router = APIRouter(prefix="/auth/oidc", tags=["Single sign-on"])


class OidcSettings(BaseModel):
    enabled: bool | None = None
    label: str | None = Field(default=None, max_length=40)
    issuer: str | None = Field(default=None, max_length=512)
    client_id: str | None = Field(default=None, max_length=256)
    client_secret: str | None = Field(default=None, max_length=512)
    scopes: str | None = Field(default=None, max_length=256)
    public_url: str | None = Field(default=None, max_length=512)
    username_claim: str | None = Field(default=None, max_length=64)
    groups_claim: str | None = Field(default=None, max_length=64)
    admin_groups: list[str] | None = None
    role_map: dict[str, str] | None = None
    default_role: str | None = Field(default=None, max_length=64)
    auto_create: bool | None = None
    sync_roles: bool | None = None
    link_by_verified_email: bool | None = None


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _fail(message: str) -> RedirectResponse:
    return RedirectResponse(f"/?sso_error={urllib.parse.quote(message[:200])}", status_code=303)


@router.get("/config")
def sso_public_config() -> dict[str, Any]:
    """Whether to show the single sign-on button, and its label (public)."""
    return oidc.public_config()


@router.get("/login")
def sso_login(request: Request):
    try:
        return RedirectResponse(oidc.start_login(_base(request)), status_code=303)
    except Exception as e:
        logger.warning(f"[OIDC] Could not start sign-in: {e}")
        return _fail(str(e) if isinstance(e, oidc.OidcError) else "The sign-in provider is not reachable.")


@router.get("/callback")
def sso_callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    if error:
        return _fail(error_description or error)
    try:
        claims = oidc.finish_login(code, state)
        user = oidc.user_for_claims(claims)
    except oidc.OidcError as e:
        return _fail(str(e))
    except Exception as e:
        logger.warning(f"[OIDC] Sign-in failed: {e}", exc_info=True)
        return _fail("Single sign-on failed. Check the provider settings.")
    from backend.api.auth import _build_session_response

    session = _build_session_response(user, False, request, method="oidc")
    resp = RedirectResponse("/", status_code=303)
    for k, v in session.raw_headers:
        if k.lower() == b"set-cookie":
            resp.raw_headers.append((k, v))
    return resp


@router.get("/settings", dependencies=[Depends(require_scope("users:write", "system:config"))])
def sso_settings(request: Request) -> dict[str, Any]:
    cfg = oidc.masked_config()
    cfg["redirect_uri"] = oidc.redirect_uri(cfg, _base(request))
    return cfg


@router.put("/settings", dependencies=[Depends(require_scope("users:write", "system:config"))])
def sso_save_settings(req: OidcSettings, request: Request) -> dict[str, Any]:
    try:
        cfg = oidc.save_config(req.model_dump())
    except oidc.OidcError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    cfg["redirect_uri"] = oidc.redirect_uri(cfg, _base(request))
    return cfg
