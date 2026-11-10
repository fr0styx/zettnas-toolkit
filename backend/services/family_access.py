"""Each family member's own way in from outside (NFEAT-1, D12).

The owner invites a Kiboto user; Kiboto asks Tailscale for a share invite of the NAS alone (the
person gets their own free Tailscale account and sees nothing else of the owner's tailnet) and
gives the owner a link to a guided page to send. That page sits under /api/fs/shared, so it opens
from anywhere when public share links are on (Funnel), and walks the person through three steps:
get the Tailscale app, sign in with Google, Apple or Microsoft, accept. Then it opens Kiboto.

Tailscale lets only a person's own API access key make share invites (not an OAuth client), and
such a key lasts at most 90 days, so Kiboto keeps it sealed, reads its expiry from Tailscale and
says when it is about to run out. Accepted shares can't be taken back through the API: revoking
one points the owner at the machine's Sharing menu in Tailscale. Tailscale only opens the way to
the NAS; Kiboto's own sign-in still decides what the person sees.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timezone
from typing import Any

from backend import secret_box
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

API = "https://api.tailscale.com/api/v2"
KEYS_PAGE = "https://login.tailscale.com/admin/settings/keys"
MACHINES_PAGE = "https://login.tailscale.com/admin/machines"
STATE_FILE = f"{DATA_DIR}/family_access.json"
PAGE_PATH = "/api/fs/shared/join"
INVITE_DAYS = 7
KEY_WARN_DAYS = 14
REFRESH_EVERY = 5.0  # seconds between asking Tailscale, however many pages poll
_KEY = re.compile(r"^tskey-api-([A-Za-z0-9]{4,40})-[A-Za-z0-9]{8,80}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_lock = threading.Lock()
_asked = {"at": 0.0}

Opener = Callable[..., Any]


class _Refuse(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the API key on to another address."""

    def redirect_request(self, *args, **kwargs):
        return None


_NO_REDIRECTS = urllib.request.build_opener(_Refuse)


class FamilyAccessError(RuntimeError):
    """Something the owner can act on (no key, Tailscale said no, Headscale)."""


def _state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("invites", {})
    return data


def _save(data: dict[str, Any]) -> None:
    atomic_write_json(STATE_FILE, data)


def _call(key: str, method: str, path: str, body: Any = None, opener: Opener | None = None) -> Any:
    """One Tailscale API call with the owner's key; FamilyAccessError with Tailscale's reason."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with (opener or _NO_REDIRECTS.open)(req, timeout=10) as resp:
            raw = resp.read(1 << 20)
    except urllib.error.HTTPError as e:
        reason = ""
        try:
            reason = str(json.loads(e.read(4096) or b"{}").get("message") or "")
        except (ValueError, OSError):
            reason = ""
        if e.code in (401, 403):
            raise FamilyAccessError(
                "Tailscale didn't accept the API key (expired, revoked, or not allowed to share this machine)."
            ) from None
        raise FamilyAccessError(f"Tailscale answered {e.code}: {reason or e.reason}") from None
    except (urllib.error.URLError, OSError) as e:
        raise FamilyAccessError(f"Tailscale's API didn't answer: {getattr(e, 'reason', e)}") from None
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        raise FamilyAccessError("Tailscale's API sent something that isn't JSON.") from None


def _tailscale() -> dict[str, Any]:
    from backend.services import public_links

    return public_links.tailscale_status()


def node_id(doc: dict[str, Any] | None = None) -> str:
    """This NAS in Tailscale's API (the stable node ID)."""
    me = (doc if doc is not None else _tailscale()).get("Self") or {}
    return str(me.get("ID") or "")


def _on_headscale() -> bool:
    from backend.hardware.net import tailscale

    server = tailscale.login_server() or ""
    return bool(server) and "tailscale.com" not in server


def _key(data: dict[str, Any]) -> str:
    sealed = str(data.get("api_key") or "")
    return secret_box.unseal(sealed) if sealed else ""


def _expiry(key: str, opener: Opener | None = None) -> str:
    """When the key runs out, read from Tailscale ("" when it can't say)."""
    m = _KEY.match(key)
    if not m:
        return ""
    try:
        info = _call(key, "GET", f"/tailnet/-/keys/{m.group(1)}", opener=opener)
    except FamilyAccessError:
        return ""
    return str((info or {}).get("expires") or "") if isinstance(info, dict) else ""


def days_left(expires: str, now: float | None = None) -> int | None:
    if not expires:
        return None
    try:
        when = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return int((when.timestamp() - (now if now is not None else time.time())) // 86400)


def save_key(key: str, actor: str = "", opener: Opener | None = None) -> dict[str, Any]:
    """Checks the key against this machine's invites, then keeps it sealed."""
    key = (key or "").strip()
    if not _KEY.match(key):
        raise FamilyAccessError("That isn't a Tailscale API access key (they start with tskey-api-).")
    nid = node_id()
    if not nid:
        raise FamilyAccessError("Tailscale isn't connected on this NAS.")
    _call(key, "GET", f"/device/{nid}/device-invites", opener=opener)
    expires = _expiry(key, opener)
    with _lock:
        data = _state()
        data["api_key"] = secret_box.seal(key)
        data["key_expires"] = expires
        _save(data)
    _audit("family_access.key", f"expires {expires or 'unknown'}", actor)
    return status()


def forget_key(actor: str = "") -> dict[str, Any]:
    with _lock:
        data = _state()
        data["api_key"] = ""
        data["key_expires"] = ""
        _save(data)
    _audit("family_access.key_removed", "", actor)
    return status()


def page_url(token: str) -> str:
    """The invite page from anywhere when public share links are on, else from home ("" without either)."""
    from backend.services import public_links

    base = public_links.base_url()
    return f"{base}{PAGE_PATH}/{token}" if base else ""


def invite(user_id: str, username: str, name: str, actor: str = "", opener: Opener | None = None) -> dict[str, Any]:
    """A new single-use share invite of this NAS for one Kiboto user (an older open one is withdrawn)."""
    if _on_headscale():
        raise FamilyAccessError(
            "This NAS signs in to your own Headscale server; share invites are a Tailscale service."
        )
    with _lock:
        data = _state()
        key = _key(data)
        if not key:
            raise FamilyAccessError("Add a Tailscale API access key first.")
        nid = node_id()
        if not nid:
            raise FamilyAccessError("Tailscale isn't connected on this NAS.")
        old = [t for t, i in data["invites"].items() if i.get("user_id") == user_id]
        for t in old:
            prev = data["invites"].pop(t)
            if not prev.get("accepted") and prev.get("invite_id"):
                _withdraw(key, str(prev["invite_id"]), opener)
        made = _call(
            key, "POST", f"/device/{nid}/device-invites", [{"multiUse": False, "allowExitNode": False}], opener
        )
        first = made[0] if isinstance(made, list) and made and isinstance(made[0], dict) else {}
        if not first.get("inviteUrl") or not first.get("id"):
            raise FamilyAccessError("Tailscale didn't send an invite back.")
        token = secrets.token_urlsafe(24)
        now = time.time()
        data["invites"][token] = {
            "user_id": user_id,
            "username": username,
            "name": name or username,
            "invite_id": str(first["id"]),
            "invite_url": str(first["inviteUrl"]),
            "created": now,
            "expires": now + INVITE_DAYS * 86400,
            "accepted": False,
            "login": "",
        }
        _save(data)
    _audit("family_access.invite", username, actor)
    return status()


def _withdraw(key: str, invite_id: str, opener: Opener | None) -> None:
    try:
        _call(key, "DELETE", f"/device-invites/{invite_id}", opener=opener)
    except FamilyAccessError as e:
        logger.info("[FamilyAccess] Could not withdraw invite %s: %s", invite_id, e)


def revoke(user_id: str, actor: str = "", opener: Opener | None = None) -> dict[str, Any]:
    """Withdraws an open invite; an accepted share is removed in Tailscale (the answer says where)."""
    with _lock:
        data = _state()
        key = _key(data)
        found = [t for t, i in data["invites"].items() if i.get("user_id") == user_id]
        if not found:
            raise KeyError(user_id)
        accepted = False
        for t in found:
            item = data["invites"].pop(t)
            accepted = accepted or bool(item.get("accepted"))
            if not item.get("accepted") and key and item.get("invite_id"):
                _withdraw(key, str(item["invite_id"]), opener)
        _save(data)
    _audit("family_access.revoke", user_id, actor)
    out = status()
    out["remove_share_at"] = MACHINES_PAGE if accepted else ""
    return out


def refresh(opener: Opener | None = None) -> None:
    """Asks Tailscale which open invites were accepted, and by whom (at most every REFRESH_EVERY seconds)."""
    with _lock:
        now = time.monotonic()
        if now - _asked["at"] < REFRESH_EVERY:
            return
        _asked["at"] = now
        data = _state()
        key = _key(data)
        if not key:
            return
        changed = False
        for item in data["invites"].values():
            if item.get("accepted") or not item.get("invite_id"):
                continue
            try:
                info = _call(key, "GET", f"/device-invites/{item['invite_id']}", opener=opener)
            except FamilyAccessError as e:
                logger.info("[FamilyAccess] %s", e)
                return
            if isinstance(info, dict) and info.get("accepted"):
                item["accepted"] = True
                item["login"] = str((info.get("acceptedBy") or {}).get("loginName") or "")
                changed = True
        if changed:
            _save(data)
            logger.info("[FamilyAccess] An invite was accepted")


def _online_logins(doc: dict[str, Any]) -> set[str]:
    """Login names of people with a device online that this NAS can see (shared-in peers)."""
    users = doc.get("User") or {}
    out: set[str] = set()
    for peer in (doc.get("Peer") or {}).values():
        if not peer.get("Online"):
            continue
        login = str((users.get(str(peer.get("UserID"))) or {}).get("LoginName") or "")
        if login:
            out.add(login.lower())
    return out


def _person(token: str, item: dict[str, Any], online: set[str], now: float) -> dict[str, Any]:
    if item.get("accepted"):
        state = "online" if str(item.get("login") or "").lower() in online else "joined"
    else:
        state = "expired" if now > float(item.get("expires") or 0) else "invited"
    return {
        "user_id": item.get("user_id"),
        "username": item.get("username"),
        "name": item.get("name"),
        "state": state,
        "login": item.get("login") or "",
        "page_url": page_url(token) if state == "invited" else "",
        "invite_url": item.get("invite_url") if state == "invited" else "",
        "expires": item.get("expires"),
    }


def status() -> dict[str, Any]:
    data = _state()
    doc = _tailscale()
    left = days_left(str(data.get("key_expires") or ""))
    now = time.time()
    online = _online_logins(doc)
    return {
        "tailscale": bool(node_id(doc)),
        "headscale": _on_headscale(),
        "has_key": bool(data.get("api_key")),
        "key_days_left": left,
        "key_expiring": left is not None and left <= KEY_WARN_DAYS,
        "keys_page": KEYS_PAGE,
        "public_page": bool(page_url("x")),
        "people": [_person(t, i, online, now) for t, i in data["invites"].items()],
    }


def page_info(token: str) -> dict[str, Any] | None:
    """What the public invite page shows; None for an unknown, used or expired link."""
    if not _TOKEN.match(token or ""):
        return None
    item = _state()["invites"].get(token)
    if not item or time.time() > float(item.get("expires") or 0):
        return None
    from backend.services import remote_access

    addr = (remote_access.status().get("addresses") or {}).get("kiboto") or ""
    return {
        "name": str(item.get("name") or ""),
        "accepted": bool(item.get("accepted")),
        "invite_url": "" if item.get("accepted") else str(item.get("invite_url") or ""),
        "kiboto_url": str(addr),
    }


def reseal() -> int:
    """After a key rotation: seal the API key again with the new key."""
    with _lock:
        data = _state()
        if not data.get("api_key"):
            return 0
        data["api_key"] = secret_box.seal(secret_box.unseal(data["api_key"]))
        _save(data)
    return 1


def _audit(event: str, detail: str, actor: str) -> None:
    from backend.users_db import log_security_event

    try:
        log_security_event(event, "success", actor_username=actor or None, details={"what": detail})
    except (OSError, ValueError, TypeError, sqlite3.Error):
        logger.debug("[FamilyAccess] could not write the security log", exc_info=True)
