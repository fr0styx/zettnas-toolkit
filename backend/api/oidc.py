"""OpenID Connect sign-in endpoints (M6)."""

import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
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


STATE_COOKIE = "zn_sso_state"


@router.get("/login")
def sso_login(request: Request):
    try:
        url = oidc.start_login(_base(request))
        resp = RedirectResponse(url, status_code=303)
        # The callback must come back to the browser that started it (B11, SEC-29): a sign-in
        # link started elsewhere cannot sign this browser in to someone else's account.
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("state", [""])[0]
        resp.set_cookie(
            STATE_COOKIE,
            state,
            max_age=oidc.STATE_TTL_S,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/api",
        )
        return resp
    except Exception as e:
        logger.warning(f"[OIDC] Could not start sign-in: {e}")
        return _fail(str(e) if isinstance(e, oidc.OidcError) else "The sign-in provider is not reachable.")


@router.get("/callback")
def sso_callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    if error:
        return _fail(error_description or error)
    started_here = request.cookies.get(STATE_COOKIE)
    if started_here and started_here != state:
        return _fail("This sign-in was started in another browser. Start it again here.")
    if not started_here:
        # warned for one release (D11): from the next one a sign-in without the cookie is refused
        logger.warning("[OIDC] Sign-in callback without the browser cookie it was started with")
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
    resp.delete_cookie(STATE_COOKIE, path="/api")
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


ldap_router = APIRouter(prefix="/auth/ldap", tags=["LDAP"])


class LdapSettings(BaseModel):
    enabled: bool | None = None
    server_url: str | None = Field(default=None, max_length=512)
    start_tls: bool | None = None
    verify_tls: bool | None = None
    bind_dn: str | None = Field(default=None, max_length=512)
    bind_password: str | None = Field(default=None, max_length=512)
    base_dn: str | None = Field(default=None, max_length=512)
    user_filter: str | None = Field(default=None, max_length=512)
    username_attr: str | None = Field(default=None, max_length=64)
    admin_groups: list[str] | None = None
    role_map: dict[str, str] | None = None
    default_role: str | None = Field(default=None, max_length=64)
    auto_create: bool | None = None
    sync_roles: bool | None = None


@ldap_router.get("/settings", dependencies=[Depends(require_scope("users:write", "system:config"))])
def ldap_settings() -> dict[str, Any]:
    from backend.services import ldap_auth

    return ldap_auth.masked_config()


@ldap_router.put("/settings", dependencies=[Depends(require_scope("users:write", "system:config"))])
def ldap_save_settings(req: LdapSettings) -> dict[str, Any]:
    from backend.services import ldap_auth

    try:
        return ldap_auth.save_config(req.model_dump())
    except ldap_auth.LdapError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@ldap_router.post("/test", dependencies=[Depends(require_scope("users:write", "system:config"))])
def ldap_test() -> dict[str, Any]:
    from backend.services import ldap_auth

    return ldap_auth.test_connection()


class ImmichConnect(BaseModel):
    immich_url: str = Field(..., max_length=256, pattern=r"^https?://")
    client_id: str = Field(default="", max_length=256)
    client_secret: str = Field(default="", max_length=512)


def _immich_app_dir() -> str:
    """The Immich app folder from its container's /data mount, or appdata/immich."""
    import os

    try:
        from backend.services.container_mutator import _docker_request

        st, info = _docker_request("GET", "/containers/immich/json")
        if st == 200:
            for m in info.get("Mounts") or []:
                if m.get("Destination") == "/data" and m.get("Source"):
                    return os.path.dirname(m["Source"].rstrip("/"))
    except Exception:
        logger.debug("oidc: immich container not found", exc_info=True)
    return "/mnt/user/appdata/immich"


@router.post("/apps/immich", dependencies=[Depends(require_scope("users:write", "system:config"))])
def connect_immich(req: ImmichConnect, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Turns on sign-in with ZettNAS's provider in a freshly installed Immich (M3)."""
    from backend.services import immich_sso
    from backend.users_db import get_user_by_username

    me = get_user_by_username(principal.username) or {}
    try:
        res = immich_sso.connect(
            req.immich_url,
            me.get("email") or "",
            _immich_app_dir(),
            oidc.load_config(),
            req.client_id,
            req.client_secret,
        )
        from backend.services import immich_photos

        immich_photos.set_sso(True)  # the Back up my phone card says "Sign in with ZettNAS"
        return res
    except immich_sso.ImmichSsoError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
