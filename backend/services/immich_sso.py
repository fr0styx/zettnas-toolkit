"""
Connect Immich to the same sign-in provider as Kiboto (M3).

Steps, through Immich's own API:
1. If Immich has no admin yet, create one with the Kiboto user's email and a generated
   password (kept in appdata/immich/.zettnas-secrets.json as immich_admin_password).
2. Sign in as that admin.
3. Read the system config, turn on OAuth with Kiboto's OpenID Connect issuer and the
   client ID/secret (Kiboto's own client unless others are given), and write it back.
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
from backend.fsutil import atomic_write_json


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
        atomic_write_json(path, data)  # owner-only (0600)
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
        raise ImmichSsoError("Set up single sign-on for Kiboto first (Security → Single sign-on).")
    if not admin_email or "@" not in admin_email:
        raise ImmichSsoError("Your Kiboto account needs an email address; Immich uses it for the admin account.")
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
                "Immich already has an admin that Kiboto didn't create. Turn on OAuth in Immich "
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
    logger.info("[ImmichSSO] %s at %s", ", ".join(steps), base)
    return {
        "ok": True,
        "steps": steps,
        "redirect_uris": ["app.immich:///oauth-callback", f"{base}/auth/login", f"{base}/user-settings"],
    }


def app_dir() -> str:
    """The Immich app folder from its container's /data mount, or appdata/immich."""
    try:
        from backend.services.container_mutator import _docker_request

        st, info = _docker_request("GET", "/containers/immich/json")
        if st == 200:
            for m in info.get("Mounts") or []:
                if m.get("Destination") == "/data" and m.get("Source"):
                    return os.path.dirname(m["Source"].rstrip("/"))
    except (OSError, ValueError, RuntimeError, KeyError):
        logger.debug("immich_sso: immich container not found", exc_info=True)
    return "/mnt/user/appdata/immich"


def follow_move(new_url: str) -> dict[str, Any]:
    """Immich moved to `new_url` (decision B6): connects its family sign-in again there, so Immich
    itself knows its new address, and leaves an alert with the sign-in addresses to add in the
    sign-in provider (Kiboto cannot change the provider). Never raises."""
    from backend.services import immich_photos, oidc
    from backend.state import add_event

    conn = immich_photos.sso_connection()
    if not conn:
        return {"skipped": True}
    try:
        res = connect(new_url, conn["email"], app_dir(), oidc.load_config())
    except (ImmichSsoError, httpx.HTTPError, OSError, ValueError) as e:
        add_event(
            "warning",
            "Immich moved: connect its family sign-in again",
            f"Immich now answers at {new_url}. Kiboto could not connect its family sign-in there ({e}); "
            "connect Immich again in People.",
        )
        return {"ok": False, "error": str(e)}
    immich_photos.set_sso(True, new_url, conn["email"])
    uris = [u for u in res.get("redirect_uris", []) if u.startswith("http")]
    add_event(
        "info",
        "Immich moved: add its new sign-in addresses",
        f"Immich now answers at {new_url} and Kiboto connected its family sign-in there. "
        f"Add these addresses to Immich in your sign-in provider: {', '.join(uris)}.",
    )
    return {"ok": True, "redirect_uris": res.get("redirect_uris", [])}
