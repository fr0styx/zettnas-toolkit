"""A filter for the kids' devices through AdGuard Home (COMP-13).

AdGuard Home (App Catalog) answers the home network's DNS. For each family account an admin
lists that person's devices (IP addresses, MAC addresses or AdGuard client IDs); ZettNAS then
keeps one AdGuard client per person, named "ZettNAS: <account>", with parental control, safe
browsing and safe search on, and the services the admin picked (TikTok, games, ...) blocked.
Everyone else keeps AdGuard's own settings.

ZettNAS signs in to AdGuard's API with the admin's AdGuard user and password, kept sealed
(secret_box) and never sent back to the browser.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, json_locked, read_json

SETTINGS_FILE = f"{DATA_DIR}/adguard_kids.json"
DEFAULT_URL = "http://adguardhome:3000"
PREFIX = "ZettNAS: "
# AdGuard Home's own ids for services it can block
SERVICES = (
    "tiktok",
    "youtube",
    "instagram",
    "snapchat",
    "facebook",
    "discord",
    "twitch",
    "roblox",
    "fortnite",
    "steam",
)
_URL = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?/?$")
_MAC = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")
_CLIENT_ID = re.compile(r"^[a-z0-9-]{1,63}$")
_USER = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")


class AdGuardError(Exception):
    """AdGuard Home refused or didn't answer; the message says which."""


def _settings() -> dict[str, Any]:
    return {"url": DEFAULT_URL, "user": "", "password": "", "people": {}, **(read_json(SETTINGS_FILE, {}) or {})}


def public() -> dict[str, Any]:
    s = _settings()
    return {"url": s["url"], "user": s["user"], "has_password": bool(s["password"]), "people": s["people"]}


def _ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None  # not an IP address; the caller tries MAC and client ID


def device_id(value: str) -> str:
    """One device as AdGuard knows it: an IP address, a MAC address or a client ID."""
    v = str(value or "").strip()
    ip = _ip(v)
    if ip:
        return ip
    if _MAC.match(v):
        return v.lower().replace("-", ":")
    if _CLIENT_ID.match(v):
        return v
    raise ValueError(f"{v or 'An empty entry'} isn't an IP address, MAC address or AdGuard client ID.")


@json_locked(lambda *a, **k: SETTINGS_FILE)
def save_connection(url: str | None = None, user: str | None = None, password: str | None = None) -> dict[str, Any]:
    from backend import secret_box

    s = _settings()
    if url is not None:
        url = url.strip().rstrip("/") or DEFAULT_URL
        if not _URL.match(url + "/"):
            raise ValueError("Use AdGuard Home's address, like http://adguardhome:3000.")
        s["url"] = url
    if user is not None:
        if user and not _USER.match(user):
            raise ValueError("That doesn't look like an AdGuard Home user name.")
        s["user"] = user
    if password is not None:
        s["password"] = secret_box.seal(password) if password else ""
    atomic_write_json(SETTINGS_FILE, s)
    return public()


def _call(s: dict[str, Any], method: str, path: str, body: Any = None, opener: Callable | None = None) -> Any:
    from backend import secret_box

    if not s.get("user") or not s.get("password"):
        raise AdGuardError("Connect AdGuard Home first: its address, user and password.")
    token = base64.b64encode(f"{s['user']}:{secret_box.unseal(s['password'])}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{s['url']}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    try:
        with (opener or urllib.request.urlopen)(req, timeout=8) as r:  # noqa: S310 - the admin's AdGuard address
            raw = r.read(2_000_000)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AdGuardError("AdGuard Home refused the user name or password.") from e
        raise AdGuardError(f"AdGuard Home answered {e.code} to {path}.") from e
    except (OSError, ValueError) as e:
        raise AdGuardError(f"AdGuard Home didn't answer at {s['url']}: {getattr(e, 'reason', e)}") from e
    try:
        return json.loads(raw) if raw.strip() else None
    except ValueError:
        return raw.decode("utf-8", "replace")


def check(opener: Callable | None = None) -> dict[str, Any]:
    """Whether AdGuard Home answers with these credentials, and its version."""
    try:
        st = _call(_settings(), "GET", "/control/status", opener=opener) or {}
    except AdGuardError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "version": str(st.get("version") or ""), "protection": bool(st.get("protection_enabled"))}


def client_for(username: str, devices: list[str], blocked: list[str]) -> dict[str, Any]:
    """The AdGuard client for one person's devices: family filtering on, chosen services off."""
    return {
        "name": PREFIX + username,
        "ids": devices,
        "use_global_settings": False,
        "filtering_enabled": True,
        "parental_enabled": True,
        "safebrowsing_enabled": True,
        "safe_search": {
            "enabled": True,
            "bing": True,
            "duckduckgo": True,
            "ecosia": True,
            "google": True,
            "pixabay": True,
            "yandex": True,
            "youtube": True,
        },
        "use_global_blocked_services": not blocked,
        "blocked_services": blocked,
        "tags": ["user_child"],
        "upstreams": [],
    }


def _existing(s: dict[str, Any], opener: Callable | None) -> set[str]:
    data = _call(s, "GET", "/control/clients", opener=opener) or {}
    return {str(c.get("name")) for c in (data.get("clients") or []) if isinstance(c, dict)}


@json_locked(lambda *a, **k: SETTINGS_FILE)
def set_person(username: str, devices: list[str], blocked: list[str], opener: Callable | None = None) -> dict:
    """Filters (or with no devices, stops filtering) one person's devices, in AdGuard and here."""
    if not _USER.match(username or ""):
        raise ValueError("No such account.")
    ids = sorted({device_id(d) for d in devices})
    bad = [b for b in blocked if b not in SERVICES]
    if bad:
        raise ValueError(f"AdGuard Home can't block {', '.join(bad)} here; pick from {', '.join(SERVICES)}.")
    s = _settings()
    name = PREFIX + username
    have = _existing(s, opener)
    if not ids:
        if name in have:
            _call(s, "POST", "/control/clients/delete", {"name": name}, opener)
        s["people"].pop(username, None)
    else:
        client = client_for(username, ids, sorted(set(blocked)))
        if name in have:
            _call(s, "POST", "/control/clients/update", {"name": name, "data": client}, opener)
        else:
            _call(s, "POST", "/control/clients/add", client, opener)
        s["people"][username] = {"devices": ids, "blocked": sorted(set(blocked))}
    atomic_write_json(SETTINGS_FILE, s)
    return public()


def reseal() -> int:
    """Seals the AdGuard password again with a new secret key (services/key_rotation.py)."""
    from backend import secret_box

    s = _settings()
    if not secret_box.is_sealed(s.get("password") or ""):
        return 0
    s["password"] = secret_box.seal(secret_box.unseal(s["password"]))
    atomic_write_json(SETTINGS_FILE, s)
    return 1
