"""One family sign-in for the apps (NFEAT-6, D16): Pocket ID, run and filled by Kiboto.

Turned on (confirmed), Kiboto starts Pocket ID in a container of its own, kiboto-id, on port 1411,
with keys it makes and keeps sealed. Passkeys need https, so Pocket ID lives at the NAS's Tailscale
HTTPS address for apps (port 1411 + 10000), which remote access already serves for every app.

Kiboto keeps Pocket ID's people in step with its own: each active Kiboto user gets a Pocket ID account
in the group "kiboto-family" (administrators stay administrators), and a user turned off or removed
in Kiboto is turned off there. Pocket ID has no passwords: "Send a sign-in link" gives a link for
one person that signs them in once (24 hours) so they can add a passkey.

Connecting an app (Immich, Nextcloud, Paperless, Audiobookshelf, Jellyfin) makes it an OIDC client in
Pocket ID, limited to the family group, with the app's own callback addresses, and shows the issuer,
client ID and secret to paste into the app's sign-in settings, with where to put them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import urllib.error
import urllib.request
from typing import Any

from backend import product, secret_box
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

CONTAINER = "kiboto-id"
IMAGE = "ghcr.io/pocket-id/pocket-id:v2-distroless"  # runs as uid 1000, needs no capability
RUNS_AS = 1000
PORT = 1411
HTTPS_PORT = PORT + 10000  # remote_access.APP_HTTPS_OFFSET
CONFIG_FILE = os.path.join(DATA_DIR, "family_signin.json")
GROUP = "kiboto-family"
LINK_SECONDS = 24 * 3600
NO_DOCKER = "Docker didn't answer, so the sign-in service can't be started."
_lock = threading.Lock()
_open = urllib.request.urlopen  # Pocket ID on the Docker network or the host port

# OIDC presets: the callback addresses each app expects (relative to its address) and where its settings are
APPS: dict[str, dict[str, Any]] = {
    "immich": {
        "name": "Immich",
        "callbacks": ["auth/login", "user-settings", "app.immich:///oauth-callback"],
        "where": "Immich → Administration → Settings → Authentication Settings → OAuth: turn it on and paste "
        'the issuer URL, client ID and secret; button text "Sign in with Kiboto".',
    },
    "nextcloud": {
        "name": "Nextcloud",
        "callbacks": ["apps/user_oidc/code"],
        "where": 'Nextcloud → Apps: install "OpenID Connect user backend", then Administration settings → '
        "OpenID Connect → Register a provider named Kiboto with the client ID, secret and discovery URL.",
    },
    "paperless": {
        "name": "Paperless-ngx",
        "callbacks": ["accounts/oidc/kiboto/login/callback/"],
        "where": "Paperless-ngx: set PAPERLESS_APPS=allauth.socialaccount.providers.openid_connect and "
        'PAPERLESS_SOCIALACCOUNT_PROVIDERS with provider_id "kiboto", the client ID, secret and server URL '
        "(the issuer), then restart the app.",
    },
    "audiobookshelf": {
        "name": "Audiobookshelf",
        "callbacks": ["auth/openid/callback", "auth/openid/mobile-redirect"],
        "where": "Audiobookshelf → Settings → Authentication → OpenID Connect: paste the issuer URL and press "
        "Auto-populate, then the client ID and secret.",
    },
    "jellyfin": {
        "name": "Jellyfin",
        "callbacks": ["sso/OID/redirect/kiboto"],
        "where": 'Jellyfin: install the SSO-Auth plugin, then add an OpenID provider named "kiboto" with the '
        "issuer URL as endpoint, the client ID and secret.",
    },
}


class SignInError(RuntimeError):
    """Something the owner can act on: no HTTPS yet, Docker or Pocket ID not answering, an app not installed."""


def config() -> dict[str, Any]:
    data = read_json(CONFIG_FILE, {})
    data = data if isinstance(data, dict) else {}
    data.setdefault("users", {})
    data.setdefault("clients", {})
    return data


def _save(data: dict[str, Any]) -> None:
    atomic_write_json(CONFIG_FILE, data)


def _docker(method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    from backend.services.container_mutator import docker_request

    try:
        return docker_request(method, path, body=body)
    except (OSError, RuntimeError):
        logger.debug("[FamilySignIn] Docker did not answer %s %s", method, path, exc_info=True)
        return 0, None


def _self() -> dict[str, Any]:
    from backend.services import nas_name

    return nas_name._self()


def _remote() -> dict[str, Any]:
    from backend.services import remote_access

    return remote_access.status()


def app_url(remote: dict[str, Any] | None = None) -> str:
    """https://<name>:11411 when remote access serves HTTPS, else ""."""
    st = remote if remote is not None else _remote()
    return f"https://{st['name']}:{HTTPS_PORT}" if st.get("https") and st.get("name") else ""


def _network(me: dict[str, Any]) -> str:
    mode = str((me.get("HostConfig") or {}).get("NetworkMode") or "")
    return "" if mode in ("", "default", "bridge", "host") or mode.startswith("container:") else mode


def internal_base(me: dict[str, Any] | None = None) -> str:
    """Where Kiboto reaches Pocket ID: by name on a shared Docker network, else the host port."""
    me = me if me is not None else _self()
    return f"http://{CONTAINER}:{PORT}" if me and _network(me) else f"http://127.0.0.1:{PORT}"


def desired(me: dict[str, Any], data: dict[str, Any], url: str) -> dict[str, Any]:
    from backend.services.hw_helper_container import host_data_dir
    from backend.services.image_ref import pinned

    host = host_data_dir(me)
    want: dict[str, Any] = {
        "Image": pinned(IMAGE),
        "Env": [
            f"APP_URL={url}",
            f"ENCRYPTION_KEY={secret_box.unseal(data['enc_key'])}",
            f"STATIC_API_KEY={secret_box.unseal(data['api_key'])}",
            "APP_NAME=Kiboto sign-in",
            "ALLOW_USER_SIGNUPS=disabled",
            "TRUST_PROXY=true",
        ],
        "ExposedPorts": {f"{PORT}/tcp": {}},
        "HostConfig": {
            "PortBindings": {f"{PORT}/tcp": [{"HostPort": str(PORT)}]},
            "Binds": [f"{host}/pocket-id:/app/data"],
            "RestartPolicy": {"Name": "unless-stopped"},
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
        },
    }
    net = _network(me)
    if net:
        want["HostConfig"]["NetworkMode"] = net
    fingerprint = hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()[:16]
    want["Labels"] = {
        "app": CONTAINER,
        "managed-by": product.CONTAINER,
        "kiboto.config": fingerprint,
        "net.unraid.docker.webui": f"http://[IP]:[PORT:{PORT}]/",
    }
    return want


def _ensure_container(data: dict[str, Any], url: str) -> None:
    from backend.services.container_mutator import pull_container_image
    from backend.services.hw_helper_container import host_data_dir

    me = _self()
    if not me:
        raise SignInError(NO_DOCKER)
    if not host_data_dir(me):
        raise SignInError("Kiboto's data folder isn't a folder on the host, so Pocket ID can't keep its data there.")
    folder = os.path.join(DATA_DIR, "pocket-id")
    os.makedirs(folder, exist_ok=True)
    try:
        os.chown(folder, RUNS_AS, RUNS_AS)  # Pocket ID writes its database there as its own user
    except OSError as e:
        logger.info("[FamilySignIn] Could not hand %s to uid %s: %s", folder, RUNS_AS, e)
    want = desired(me, data, url)
    code, info = _docker("GET", f"/containers/{CONTAINER}/json")
    if code == 200 and isinstance(info, dict):
        if (info.get("Config") or {}).get("Labels", {}).get("kiboto.config") == want["Labels"]["kiboto.config"]:
            if not (info.get("State") or {}).get("Running"):
                _docker("POST", f"/containers/{CONTAINER}/start")
            return
        _docker("POST", f"/containers/{CONTAINER}/stop?t=5")
        _docker("DELETE", f"/containers/{CONTAINER}?force=true")
    try:
        pull_container_image(want["Image"])
    except RuntimeError as e:
        raise SignInError(f"Pocket ID's image couldn't be downloaded: {e}") from None
    created, resp = _docker("POST", f"/containers/create?name={CONTAINER}", want)
    if created not in (200, 201):
        logger.warning("[FamilySignIn] Could not create %s: %s %s", CONTAINER, created, resp)
        raise SignInError("Pocket ID's container could not be created.")
    _docker("POST", f"/containers/{CONTAINER}/start")


def enable(actor: str = "") -> dict[str, Any]:
    """Starts Pocket ID (its keys made once and kept), gives it its HTTPS address, then fills in the family."""
    url = app_url()
    if not url:
        raise SignInError("Passkeys need https: connect Tailscale and turn on HTTPS in Use from anywhere first.")
    with _lock:
        data = config()
        data.setdefault("enc_key", secret_box.seal(secrets.token_urlsafe(32)))
        data.setdefault("api_key", secret_box.seal(secrets.token_urlsafe(32)))
        data["enabled"] = True
        data["app_url"] = url
        _save(data)
        _ensure_container(data, url)
    _publish()
    audit("family_signin.enable", url, actor)
    try:
        sync(actor)
    except SignInError as e:
        logger.info("[FamilySignIn] First sync waits for Pocket ID to start: %s", e)
    return status()


def _publish() -> None:
    from backend.services import remote_access

    try:
        remote_access.publish()
    except remote_access.RemoteAccessError as e:
        logger.info("[FamilySignIn] HTTPS for Pocket ID waits: %s", e)


def disable(actor: str = "") -> dict[str, Any]:
    """Stops and removes the container; Pocket ID's data stays, so turning it on again keeps every passkey."""
    with _lock:
        data = config()
        data["enabled"] = False
        _save(data)
        _docker("POST", f"/containers/{CONTAINER}/stop?t=5")
        _docker("DELETE", f"/containers/{CONTAINER}?force=true")
    audit("family_signin.disable", "", actor)
    return status()


def api(method: str, path: str, body: Any = None, opener: Any = None) -> Any:
    """One call to Pocket ID's API with Kiboto's key."""
    data = config()
    if not data.get("api_key"):
        raise SignInError("Turn on family sign-in first.")
    raw = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{internal_base()}{path}", data=raw, method=method)
    req.add_header("X-API-KEY", secret_box.unseal(data["api_key"]))
    req.add_header("Accept", "application/json")
    if raw is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with (opener or _open)(req, timeout=10) as resp:
            text = resp.read(1 << 20)
    except urllib.error.HTTPError as e:
        try:
            detail = str(json.loads(e.read(4096) or b"{}").get("error") or "")
        except (ValueError, OSError):
            detail = ""
        raise SignInError(f"Pocket ID answered {e.code}: {detail or e.reason}") from None
    except (urllib.error.URLError, OSError) as e:
        raise SignInError(f"Pocket ID isn't answering yet: {getattr(e, 'reason', e)}") from None
    try:
        return json.loads(text) if text else None
    except ValueError:
        raise SignInError("Pocket ID sent something that isn't JSON.") from None


def _all(path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    while page < 50:
        got = api("GET", f"{path}?pagination[page]={page}&pagination[limit]=100") or {}
        items = got.get("data") or []
        out += [i for i in items if isinstance(i, dict)]
        total_pages = int(((got.get("pagination") or {}).get("totalPages")) or 1)
        if page >= total_pages or not items:
            return out
        page += 1
    return out


def _group_id() -> str:
    for g in _all("/api/user-groups"):
        if g.get("name") == GROUP:
            return str(g["id"])
    made = api("POST", "/api/user-groups", {"name": GROUP, "friendlyName": "Kiboto family"})
    return str((made or {}).get("id") or "")


def _account(user: dict[str, Any]) -> dict[str, Any]:
    name = str(user.get("display_name") or user.get("username") or "")
    first, _, last = name.partition(" ")
    body: dict[str, Any] = {
        "username": str(user.get("username") or "")[:50],
        "displayName": name[:100],
        "firstName": first[:50] or str(user.get("username") or "")[:50],
        "lastName": last[:50],
        "isAdmin": str(user.get("role_id") or "") == "admin",
        "disabled": user.get("status") != "active",
    }
    if user.get("email"):
        body["email"] = str(user["email"])
    return body


def sync(actor: str = "") -> dict[str, Any]:
    """Pocket ID's people follow Kiboto's: added, updated, turned off; all of them in the family group."""
    from backend.users_db import list_users

    with _lock:
        data = config()
        theirs = {str(u.get("username")): u for u in _all("/api/users")}
        group = _group_id()
        mapping: dict[str, str] = {}
        for user in list_users():
            body = _account(user)
            have = theirs.get(body["username"])
            if have:
                api("PUT", f"/api/users/{have['id']}", body)
                pid = "" if body["disabled"] else str(have["id"])
            elif not body["disabled"]:
                made = api("POST", "/api/users", body) or {}
                pid = str(made.get("id") or "")
            else:
                continue
            if pid:
                mapping[str(user["id"])] = pid
        for kib_id, pid in data["users"].items():
            if kib_id not in mapping:
                gone = next((u for u in theirs.values() if str(u.get("id")) == pid), None)
                if gone and not gone.get("disabled"):
                    api("PUT", f"/api/users/{pid}", {**_strip(gone), "disabled": True})
        members = [pid for kib_id, pid in mapping.items()]
        if group:
            api("PUT", f"/api/user-groups/{group}/users", {"userIds": members})
        data["users"] = mapping
        data["group"] = group
        _save(data)
    audit("family_signin.sync", f"{len(mapping)} people", actor)
    return status()


def _strip(user: dict[str, Any]) -> dict[str, Any]:
    keep = ("username", "email", "firstName", "lastName", "displayName", "isAdmin", "locale")
    return {k: user[k] for k in keep if k in user and user[k] is not None}


def sign_in_link(user_id: str, actor: str = "") -> dict[str, Any]:
    """A link that signs this person in to Pocket ID once (24 hours), to add a passkey there."""
    data = config()
    pid = data["users"].get(user_id)
    if not pid:
        sync(actor)
        pid = config()["users"].get(user_id)
    if not pid:
        raise SignInError("That person isn't an active Kiboto user.")
    got = api("POST", f"/api/users/{pid}/one-time-access-token", {"ttl": LINK_SECONDS}) or {}
    token = str(got.get("token") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,128}", token):
        raise SignInError("Pocket ID didn't make a sign-in link.")
    audit("family_signin.link", user_id, actor)
    return {"url": f"{data.get('app_url') or app_url()}/lc/{token}", "expires_in": LINK_SECONDS}


def installed_apps(remote: dict[str, Any] | None = None) -> dict[str, str]:
    """The preset apps that run here, with their address in the tailnet ({key: url ending in /})."""
    st = remote if remote is not None else _remote()
    addrs = st.get("addresses") or {}
    found: dict[str, str] = {}
    if addrs.get("immich"):
        found["immich"] = addrs["immich"]
    for app in addrs.get("apps") or []:
        name = str(app.get("name") or "").lower()
        for key in APPS:
            if key in name and key not in found:
                found[key] = str(app.get("url") or "")
    return {k: v if v.endswith("/") else v + "/" for k, v in found.items() if v}


def connect_app(key: str, actor: str = "") -> dict[str, Any]:
    """Makes the app an OIDC client of Pocket ID for the family group; the secret is shown this once."""
    if key not in APPS:
        raise SignInError("Kiboto has no sign-in preset for that app.")
    url = installed_apps().get(key)
    if not url:
        raise SignInError(f"{APPS[key]['name']} isn't running here.")
    if not url.startswith("https://"):
        raise SignInError(f"{APPS[key]['name']} needs its HTTPS address first: Use from anywhere → Turn on HTTPS.")
    preset = APPS[key]
    callbacks = [c if "://" in c else url + c for c in preset["callbacks"]]
    data = config()
    old = data["clients"].get(key)
    if old:
        try:
            api("DELETE", f"/api/oidc/clients/{old}")
        except SignInError as e:
            logger.info("[FamilySignIn] Old client for %s not removed: %s", key, e)
    client = (
        api(
            "POST",
            "/api/oidc/clients",
            {
                "name": preset["name"],
                "callbackURLs": callbacks,
                "isPublic": False,
                "pkceEnabled": False,
                "isGroupRestricted": True,
                "launchURL": url,
            },
        )
        or {}
    )
    cid = str(client.get("id") or "")
    if not cid:
        raise SignInError("Pocket ID didn't make the client.")
    if data.get("group"):
        api("PUT", f"/api/oidc/clients/{cid}/allowed-user-groups", {"userGroupIds": [data["group"]]})
    secret = str((api("POST", f"/api/oidc/clients/{cid}/secrets", {}) or {}).get("secret") or "")
    with _lock:
        data = config()
        data["clients"][key] = cid
        _save(data)
    issuer = data.get("app_url") or app_url()
    audit("family_signin.connect", preset["name"], actor)
    return {
        "app": key,
        "name": preset["name"],
        "issuer": issuer,
        "discovery": f"{issuer}/.well-known/openid-configuration",
        "client_id": cid,
        "client_secret": secret,
        "callbacks": callbacks,
        "where": preset["where"],
    }


def disconnect_app(key: str, actor: str = "") -> dict[str, Any]:
    with _lock:
        data = config()
        cid = data["clients"].pop(key, None)
        if not cid:
            raise KeyError(key)
        _save(data)
    try:
        api("DELETE", f"/api/oidc/clients/{cid}")
    except SignInError as e:
        logger.info("[FamilySignIn] Client for %s not removed in Pocket ID: %s", key, e)
    audit("family_signin.disconnect", key, actor)
    return status()


def status() -> dict[str, Any]:
    data = config()
    remote = _remote()
    running = False
    if data.get("enabled"):
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        running = code == 200 and isinstance(info, dict) and bool((info.get("State") or {}).get("Running"))
    apps = installed_apps(remote)
    return {
        "enabled": bool(data.get("enabled")),
        "running": running,
        "url": data.get("app_url") or "",
        "https_ready": bool(app_url(remote)),
        "people": len(data["users"]),
        "apps": [
            {"key": k, "name": APPS[k]["name"], "connected": k in data["clients"], "url": apps.get(k, "")}
            for k in APPS
            if k in apps or k in data["clients"]
        ],
    }


def reseal() -> int:
    """After a key rotation: seal Pocket ID's keys again."""
    with _lock:
        data = config()
        n = 0
        for k in ("enc_key", "api_key"):
            if data.get(k):
                data[k] = secret_box.seal(secret_box.unseal(data[k]))
                n += 1
        if n:
            _save(data)
    return n


def audit(event: str, detail: str, actor: str) -> None:
    from backend.users_db import log_security_event

    try:
        log_security_event(event, "success", actor_username=actor or None, details={"what": detail})
    except (OSError, ValueError, TypeError, sqlite3.Error):
        logger.debug("[FamilySignIn] could not write the security log", exc_info=True)
