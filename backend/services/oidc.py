"""
Sign in with an OpenID Connect provider (M6): Authentik, Keycloak, Authelia, Zitadel,
Entra ID, Google and others.

Authorization code flow with PKCE (S256), state and nonce. The ID token comes straight
from the provider's token endpoint, so its claims are checked (issuer, audience, expiry,
nonce) without verifying the signature, as OpenID Connect Core 3.1.3.7 allows for that
channel. Use HTTPS for the provider.

Accounts: the provider's `sub` is stored on the ZettNAS user (idp_type "oidc"), so a
renamed IdP user keeps their account. A provider login never takes over an existing
local account, unless "link by verified email" is turned on and the provider says the
email is verified. Roles come from groups: admin_groups -> SuperAdmin, role_map for the
rest, default_role otherwise; with sync_roles they are re-applied at every sign-in.
"""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from typing import Any

import httpx

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked

CONFIG_FILE = os.path.join(DATA_DIR, "oidc.json")
STATE_TTL_S = 600
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "label": "Single sign-on",
    "issuer": "",
    "client_id": "",
    "client_secret": "",
    "scopes": "openid profile email groups",
    "public_url": "",
    "username_claim": "preferred_username",
    "groups_claim": "groups",
    "admin_groups": [],
    "role_map": {},
    "default_role": "share_user",
    "auto_create": True,
    "sync_roles": True,
    "link_by_verified_email": False,
}
_states: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_discovery: dict[str, tuple[float, dict[str, Any]]] = {}


class OidcError(Exception):
    pass


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        logger.debug("oidc: no saved config", exc_info=False)
    return cfg


def public_config() -> dict[str, Any]:
    cfg = load_config()
    on = bool(cfg["enabled"] and cfg["issuer"] and cfg["client_id"])
    return {"enabled": on, "label": cfg["label"] if on else ""}


def masked_config() -> dict[str, Any]:
    cfg = load_config()
    cfg["client_secret"] = "********" if cfg.get("client_secret") else ""
    return cfg


@json_locked(lambda *a, **k: CONFIG_FILE)
def save_config(changes: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    for k, v in changes.items():
        if k not in DEFAULTS or v is None:
            continue
        if k == "client_secret" and v == "********":
            continue
        cfg[k] = v
    issuer = str(cfg.get("issuer") or "").strip().rstrip("/")
    if issuer:
        p = urllib.parse.urlparse(issuer)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise OidcError("The issuer must be an http(s) URL")
        if p.hostname in ("169.254.169.254", "metadata.google.internal"):
            raise OidcError("That address is not allowed")
    cfg["issuer"] = issuer
    cfg["admin_groups"] = [str(g) for g in cfg.get("admin_groups") or []]
    cfg["role_map"] = {str(k): str(v) for k, v in (cfg.get("role_map") or {}).items()}
    atomic_write_json(CONFIG_FILE, cfg, indent=1)  # owner-only (0600)
    _discovery.clear()
    return masked_config()


def discover(issuer: str, client: httpx.Client) -> dict[str, Any]:
    hit = _discovery.get(issuer)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    r = client.get(f"{issuer}/.well-known/openid-configuration", timeout=10)
    r.raise_for_status()
    meta = r.json()
    if str(meta.get("issuer", "")).rstrip("/") != issuer:
        raise OidcError("The provider's issuer doesn't match the configured issuer")
    _discovery[issuer] = (time.time(), meta)
    return meta


def redirect_uri(cfg: dict[str, Any], request_base: str) -> str:
    base = (cfg.get("public_url") or request_base).rstrip("/")
    return f"{base}/api/auth/oidc/callback"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def start_login(request_base: str, client: httpx.Client | None = None) -> str:
    """The provider URL to send the browser to."""
    cfg = load_config()
    if not public_config()["enabled"]:
        raise OidcError("Single sign-on is not set up")
    with client or httpx.Client() as c:
        meta = discover(cfg["issuer"], c)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    now = time.time()
    with _lock:
        for k in [k for k, v in _states.items() if now - v["at"] > STATE_TTL_S]:
            _states.pop(k, None)
        if len(_states) > 1000:
            raise OidcError("Too many sign-ins in progress; try again shortly")
        _states[state] = {
            "nonce": nonce,
            "verifier": verifier,
            "at": now,
            "redirect_uri": redirect_uri(cfg, request_base),
        }
    q = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri(cfg, request_base),
        "scope": cfg["scopes"],
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    }
    return f"{meta['authorization_endpoint']}?{urllib.parse.urlencode(q)}"


def _jwt_claims(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError) as e:
        raise OidcError("The provider returned an unreadable ID token") from e


def finish_login(code: str, state: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """Exchanges the code and returns the verified claims (merged with userinfo)."""
    cfg = load_config()
    with _lock:
        st = _states.pop(state or "", None)
    if not st or time.time() - st["at"] > STATE_TTL_S:
        raise OidcError("This sign-in link expired or was already used. Start again.")
    with client or httpx.Client() as c:
        meta = discover(cfg["issuer"], c)
        r = c.post(
            meta["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": st["redirect_uri"],
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "code_verifier": st["verifier"],
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            raise OidcError(f"The provider refused the sign-in ({r.status_code})")
        tokens = r.json()
        claims = _jwt_claims(tokens.get("id_token") or "")
        aud = claims.get("aud")
        auds = aud if isinstance(aud, list) else [aud]
        if str(claims.get("iss", "")).rstrip("/") != cfg["issuer"]:
            raise OidcError("ID token from the wrong issuer")
        if cfg["client_id"] not in auds:
            raise OidcError("ID token for another application")
        if float(claims.get("exp", 0)) < time.time() - 60:
            raise OidcError("ID token expired")
        if claims.get("nonce") != st["nonce"]:
            raise OidcError("ID token does not belong to this sign-in")
        if tokens.get("access_token") and meta.get("userinfo_endpoint"):
            try:
                u = c.get(
                    meta["userinfo_endpoint"], headers={"Authorization": f"Bearer {tokens['access_token']}"}, timeout=10
                )
                if u.status_code == 200 and u.json().get("sub") == claims.get("sub"):
                    claims = {**u.json(), **claims}
            except (httpx.HTTPError, ValueError):
                logger.debug("oidc: userinfo unavailable", exc_info=True)
    if not claims.get("sub"):
        raise OidcError("The provider did not say who you are")
    return claims


def role_for(groups: list[str], cfg: dict[str, Any]) -> str:
    if any(g in cfg.get("admin_groups", []) for g in groups):
        return "superadmin"
    for g in groups:
        if g in (cfg.get("role_map") or {}):
            return cfg["role_map"][g]
    return cfg.get("default_role") or "share_user"


def _clean_username(raw: str) -> str:
    base = "".join(ch for ch in str(raw or "").lower().split("@")[0] if ch.isalnum() or ch in "._-")
    base = base.lstrip(".")[:28]  # a name like ".." would be a folder above the private folders
    return base if len(base) >= 2 else f"user{secrets.token_hex(3)}"


def user_for_claims(claims: dict[str, Any]) -> dict[str, Any]:
    """Finds or creates the ZettNAS user for these claims."""
    from backend.users_db import create_user, get_user_by_idp, get_user_by_username, list_users, update_user_profile

    cfg = load_config()
    groups = claims.get(cfg["groups_claim"]) or []
    groups = [str(g).lstrip("/") for g in (groups if isinstance(groups, list) else [groups])]
    role = role_for(groups, cfg)
    user = get_user_by_idp("oidc", str(claims["sub"]))
    if not user and cfg.get("link_by_verified_email") and claims.get("email") and claims.get("email_verified") is True:
        matches = [u for u in list_users() if (u.get("email") or "").lower() == str(claims["email"]).lower()]
        if len(matches) == 1:
            user = get_user_by_username(matches[0]["username"])
            if user:
                from backend.users_db import set_user_idp

                set_user_idp(user["id"], "oidc", str(claims["sub"]))
    if not user:
        if not cfg.get("auto_create", True):
            raise OidcError("No ZettNAS account is linked to this sign-in. Ask an admin to create one.")
        name = _clean_username(claims.get(cfg["username_claim"]) or claims.get("email") or claims["sub"])
        if get_user_by_username(name):
            name = f"{name[:24]}-sso"
            while get_user_by_username(name):
                name = f"{name[:24]}-{secrets.token_hex(2)}"
        user = create_user(
            username=name,
            display_name=str(claims.get("name") or name)[:64],
            password=secrets.token_urlsafe(32),
            email=str(claims.get("email") or ""),
            role_id=role,
            idp_type="oidc",
            idp_sub=str(claims["sub"]),
        )
        user = get_user_by_username(user["username"])
    elif cfg.get("sync_roles", True) and user.get("role_id") != role:
        try:
            update_user_profile(user["id"], role_id=role)
            user = get_user_by_username(user["username"]) or user
        except Exception:
            logger.warning("[OIDC] Could not update the role (last SuperAdmin?)", exc_info=True)
    if not user or user.get("status") != "active":
        raise OidcError("This account is disabled")
    return user
