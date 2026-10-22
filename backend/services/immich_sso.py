"""
Connect Immich to the same sign-in provider as ZettNAS (M3).

Steps, through Immich's own API:
1. If Immich has no admin yet, create one with the ZettNAS user's email and a generated
   password (kept in appdata/immich/.zettnas-secrets.json as immich_admin_password).
2. Sign in as that admin.
3. Read the system config, turn on OAuth with ZettNAS's OpenID Connect issuer and the
   client ID/secret (ZettNAS's own client unless others are given), and write it back.
   Every other Immich setting is left as it is, and stays editable in Immich.

The provider must allow Immich's redirect URIs: app.immich:///oauth-callback,
<immich>/auth/login and <immich>/user-settings (docs/SSO.md).
"""

import json
import os
import secrets
from typing import Any

import httpx

from backend.config import logger


class ImmichSsoError(Exception):
    pass


def _secret_file(app_dir: str) -> str:
    return os.path.join(app_dir, ".zettnas-secrets.json")


def _admin_password(app_dir: str) -> str:
    path = _secret_file(app_dir)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not data.get("immich_admin_password"):
        data["immich_admin_password"] = secrets.token_urlsafe(18)
        os.makedirs(app_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(path, 0o600)
    return data["immich_admin_password"]


def connect(
    immich_url: str,
    admin_email: str,
    app_dir: str,
    oidc_cfg: dict[str, Any],
    client_id: str = "",
    client_secret: str = "",
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    if not oidc_cfg.get("issuer"):
        raise ImmichSsoError("Set up single sign-on for ZettNAS first (Security → Single sign-on).")
    if not admin_email or "@" not in admin_email:
        raise ImmichSsoError("Your ZettNAS account needs an email address; Immich uses it for the admin account.")
    base = immich_url.rstrip("/")
    steps = []
    with httpx.Client(base_url=f"{base}/api", timeout=20, transport=transport) as c:
        cfg_ok = c.get("/server/config")
        if cfg_ok.status_code != 200:
            raise ImmichSsoError(f"Immich is not reachable at {base} ({cfg_ok.status_code})")
        password = _admin_password(app_dir)
        if not cfg_ok.json().get("isInitialized", True):
            r = c.post("/auth/admin-sign-up", json={"email": admin_email, "password": password, "name": "Admin"})
            if r.status_code not in (200, 201):
                raise ImmichSsoError(f"Could not create the Immich admin ({r.status_code})")
            steps.append("admin created")
        r = c.post("/auth/login", json={"email": admin_email, "password": password})
        if r.status_code not in (200, 201):
            raise ImmichSsoError(
                "Immich already has an admin that ZettNAS didn't create. Turn on OAuth in Immich "
                "(Administration → Settings → Authentication) by hand, see docs/SSO.md."
            )
        auth = {"Authorization": f"Bearer {r.json()['accessToken']}"}
        steps.append("signed in")
        cfg = c.get("/system-config", headers=auth).json()
        oauth = dict(cfg.get("oauth") or {})
        oauth.update(
            {
                "enabled": True,
                "issuerUrl": oidc_cfg["issuer"],
                "clientId": client_id or oidc_cfg.get("client_id", ""),
                "clientSecret": client_secret or oidc_cfg.get("client_secret", ""),
                "scope": "openid email profile",
                "buttonText": f"Sign in with {oidc_cfg.get('label') or 'SSO'}",
                "autoRegister": True,
                # Immich refuses an http:// issuer (a LAN-only provider) unless told otherwise
                "allowInsecureRequests": str(oidc_cfg["issuer"]).startswith("http://"),
            }
        )
        cfg["oauth"] = oauth
        r = c.put("/system-config", json=cfg, headers=auth)
        if r.status_code not in (200, 201):
            raise ImmichSsoError(f"Immich refused the sign-in settings ({r.status_code}): {r.text[:200]}")
        steps.append("oauth enabled")
    logger.info(f"[ImmichSSO] {', '.join(steps)} at {base}")
    return {
        "ok": True,
        "steps": steps,
        "redirect_uris": ["app.immich:///oauth-callback", f"{base}/auth/login", f"{base}/user-settings"],
    }
