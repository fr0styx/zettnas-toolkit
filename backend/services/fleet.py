"""Kiboto boxes that know each other (RES-9, COMP-14): pairing over the tailnet, a read-only view of
each paired box, and backup space on each other's box (services/fleet_buddy.py).

Pairing: on box A the owner asks for a pairing code (10 minutes, single use) and types it, with A's
address, into box B. B calls A once with the code; each box hands the other a token of its own, so
from then on each can ask the other two things only: a summary (name, version, storage, backups),
and backup space when the other box's owner allowed it. Tokens are kept sealed (the one sent) or
hashed (the one accepted); they are no user's sign-in and reach nothing else. Unpairing on either
side tells the other box, which then forgets too.

Addresses are Tailscale addresses (a *.ts.net name or a 100.x address): the tunnel encrypts the
traffic, and a box on the internet can't be paired with.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from backend import __version__, secret_box
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

STATE_FILE = os.path.join(DATA_DIR, "fleet.json")
CODE_SECONDS = 600
CODE_TRIES = 5
SUMMARY_CACHE = 60.0
PEER_PATH = "/api/fleet/peer"
TOKEN_PREFIX = "kbpeer-"
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_TS6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
_ID = re.compile(r"^[a-f0-9]{16}$")
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

Opener = Callable[..., Any]


class FleetError(RuntimeError):
    """Something the owner can act on: a wrong code, an address off the tailnet, a box that didn't answer."""


class _Refuse(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the peer token on to another address."""

    def redirect_request(self, *args, **kwargs):
        return None


_NO_REDIRECTS = urllib.request.build_opener(_Refuse)


def _state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    if not isinstance(data, dict):
        data = {}
    if not _ID.match(str(data.get("box_id") or "")):
        data["box_id"] = secrets.token_hex(8)
    data.setdefault("peers", {})
    return data


def _save(data: dict[str, Any]) -> None:
    atomic_write_json(STATE_FILE, data)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def on_tailnet(address: str) -> bool:
    """http(s)://<name>.ts.net[:port] or a Tailscale address (100.64/10, fd7a:115c:a1e0::/48)."""
    try:
        parts = urlsplit(address)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host or parts.path not in ("", "/") or parts.query:
        return False
    if host.endswith(".ts.net"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip in _CGNAT or ip in _TS6


def _clean(address: str) -> str:
    address = (address or "").strip().rstrip("/")
    if not on_tailnet(address):
        raise FleetError(
            "Use the other box's Tailscale address (https://<name>.<tailnet>.ts.net or http://100.x.y.z:port)."
        )
    return address


def my_address() -> str:
    from backend.services import remote_access

    return str((remote_access.status().get("addresses") or {}).get("kiboto") or "").rstrip("/")


def my_name() -> str:
    from backend.services import nas_name

    try:
        return str(nas_name.config().get("name") or "") or "Kiboto"
    except (OSError, ValueError):
        return "Kiboto"


def _call(url: str, method: str = "GET", body: Any = None, token: str = "", opener: Opener | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {TOKEN_PREFIX}{token}")
    try:
        with (opener or _NO_REDIRECTS.open)(req, timeout=10) as resp:
            raw = resp.read(1 << 20)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = str(json.loads(e.read(4096) or b"{}").get("detail") or "")
        except (ValueError, OSError):
            detail = ""
        raise FleetError(detail or f"The other box answered {e.code}.") from None
    except (urllib.error.URLError, OSError) as e:
        raise FleetError(f"The other box didn't answer: {getattr(e, 'reason', e)}") from None
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        raise FleetError("The other box sent something that isn't JSON.") from None


# ---- pairing -------------------------------------------------------------------------------


def new_code(actor: str = "") -> dict[str, Any]:
    """A pairing code for another box to type in, with this box's address."""
    address = my_address()
    if not address:
        raise FleetError("Connect Tailscale first: the other box reaches this one over the tailnet.")
    raw = base64.b32encode(secrets.token_bytes(10)).decode().rstrip("=")
    code = "-".join(raw[i : i + 4] for i in range(0, 16, 4))
    with _lock:
        data = _state()
        data["pairing"] = {"hash": _hash(code), "expires": time.time() + CODE_SECONDS, "tries": 0}
        _save(data)
    audit("fleet.pairing_code", "", actor)
    return {"code": code, "address": address, "expires_in": CODE_SECONDS}


def _norm_code(code: str) -> str:
    return re.sub(r"[^A-Z2-7]", "", (code or "").upper())


def accept_pairing(code: str, box_id: str, name: str, address: str, their_token: str) -> dict[str, Any]:
    """The other box's side of pairing (called over the tailnet with the code): keeps it, answers with a token."""
    if not _ID.match(box_id or "") or not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", their_token or ""):
        raise FleetError("That isn't a pairing request.")
    address = _clean(address)
    with _lock:
        data = _state()
        pairing = data.get("pairing") or {}
        if (
            not pairing
            or time.time() > float(pairing.get("expires") or 0)
            or int(pairing.get("tries") or 0) >= CODE_TRIES
        ):
            data.pop("pairing", None)
            _save(data)
            raise FleetError("No pairing code is waiting on this box (or it ran out). Make a new one.")
        given = _norm_code(code)
        if not hmac.compare_digest(_hash("-".join(given[i : i + 4] for i in range(0, 16, 4))), str(pairing["hash"])):
            pairing["tries"] = int(pairing.get("tries") or 0) + 1
            _save(data)
            raise FleetError("That pairing code is wrong.")
        if box_id == data["box_id"]:
            raise FleetError("A box can't pair with itself.")
        mine = secrets.token_urlsafe(32)
        data["peers"][box_id] = {
            "name": (name or "Kiboto")[:64],
            "address": address,
            "send": secret_box.seal(their_token),
            "accept": _hash(mine),
            "paired_at": time.time(),
            "offer_space": False,
        }
        data.pop("pairing", None)
        _save(data)
    audit("fleet.paired", name, "")
    return {"box_id": data["box_id"], "name": my_name(), "token": mine}


def pair_with(address: str, code: str, actor: str = "", opener: Opener | None = None) -> dict[str, Any]:
    """This box's side: sends the code to the other box and keeps what it answers."""
    address = _clean(address)
    me = my_address()
    if not me:
        raise FleetError("Connect Tailscale first: the other box reaches this one over the tailnet.")
    data = _state()
    _save(data)  # the box id exists before it is sent
    theirs = secrets.token_urlsafe(32)
    reply = _call(
        f"{address}{PEER_PATH}/pair",
        "POST",
        {"code": code, "box_id": data["box_id"], "name": my_name(), "address": me, "token": theirs},
        opener=opener,
    )
    if not isinstance(reply, dict) or not _ID.match(str(reply.get("box_id") or "")) or not reply.get("token"):
        raise FleetError("The other box didn't pair.")
    with _lock:
        data = _state()
        data["peers"][reply["box_id"]] = {
            "name": str(reply.get("name") or "Kiboto")[:64],
            "address": address,
            "send": secret_box.seal(str(reply["token"])),
            "accept": _hash(theirs),
            "paired_at": time.time(),
            "offer_space": False,
        }
        _save(data)
    audit("fleet.paired", str(reply.get("name") or ""), actor)
    return status()


def peer_for_token(header: str) -> str:
    """The paired box a request's bearer token belongs to ("" when none)."""
    token = (header or "").removeprefix("Bearer ").strip()
    if not token.startswith(TOKEN_PREFIX):
        return ""
    h = _hash(token[len(TOKEN_PREFIX) :])
    for box_id, peer in _state()["peers"].items():
        if hmac.compare_digest(h, str(peer.get("accept") or "")):
            return box_id
    return ""


def peer(box_id: str) -> dict[str, Any]:
    p = _state()["peers"].get(box_id)
    if not p:
        raise KeyError(box_id)
    return p


def call_peer(box_id: str, path: str, method: str = "GET", body: Any = None, opener: Opener | None = None) -> Any:
    p = peer(box_id)
    return _call(f"{p['address']}{PEER_PATH}/{path}", method, body, secret_box.unseal(p["send"]), opener)


def forget(box_id: str, actor: str = "", tell: bool = True, opener: Opener | None = None) -> dict[str, Any]:
    """Unpairs; the other box is told so it forgets this one too (best effort)."""
    if tell:
        try:
            call_peer(box_id, "unpair", "POST", {}, opener)
        except (FleetError, KeyError) as e:
            logger.info("[Fleet] The other box wasn't told: %s", e)
    with _lock:
        data = _state()
        gone = data["peers"].pop(box_id, None)
        _save(data)
    if gone is None:
        raise KeyError(box_id)
    _cache.pop(box_id, None)
    audit("fleet.unpaired", str(gone.get("name") or ""), actor)
    return status()


def set_offer(box_id: str, enabled: bool, actor: str = "") -> dict[str, Any]:
    """Whether that box may ask this one for backup space."""
    with _lock:
        data = _state()
        if box_id not in data["peers"]:
            raise KeyError(box_id)
        data["peers"][box_id]["offer_space"] = bool(enabled)
        _save(data)
    audit("fleet.offer_space", f"{data['peers'][box_id]['name']}: {'on' if enabled else 'off'}", actor)
    return status()


def set_backup(box_id: str, repo_id: str) -> None:
    with _lock:
        data = _state()
        if box_id in data["peers"]:
            data["peers"][box_id]["backup_repo"] = repo_id
            _save(data)


# ---- what a box tells its peers ---------------------------------------------------------------


def _storage() -> list[dict[str, Any]]:
    """Size and free space of the storage folders, one entry per filesystem (statvfs wakes no disk)."""
    from backend.services.path_access import ALLOWED_BROWSE_ROOTS

    seen: set[int] = set()
    out = []
    for root in list(ALLOWED_BROWSE_ROOTS)[:8]:
        try:
            dev = os.stat(root).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        out.append({"path": root, "total": usage.total, "used": usage.used, "free": usage.free})
    return out


def _uptime() -> float | None:
    try:
        with open("/proc/uptime", encoding="ascii") as fh:
            return float(fh.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def summary() -> dict[str, Any]:
    """What a paired box may see: no file names, users or addresses besides this box's own."""
    from backend.services import offsite_backup

    backups = [
        {"name": r.get("name"), "last_backup": r.get("last_backup"), "last_result": r.get("last_result") or ""}
        for r in offsite_backup.list_repos()
    ]
    return {
        "name": my_name(),
        "version": __version__,
        "uptime": _uptime(),
        "storage": _storage(),
        "backups": backups,
        "address": my_address(),
        "at": time.time(),
    }


def peer_summary(box_id: str, opener: Opener | None = None) -> dict[str, Any]:
    """A paired box's summary, asked at most once a minute ({"error": …} when it doesn't answer)."""
    hit = _cache.get(box_id)
    if hit and time.monotonic() - hit[0] < SUMMARY_CACHE:
        return hit[1]
    try:
        got = call_peer(box_id, "summary", opener=opener)
        result = got if isinstance(got, dict) else {"error": "The box sent no summary."}
    except FleetError as e:
        result = {"error": str(e)}
    _cache[box_id] = (time.monotonic(), result)
    return result


def status(with_summaries: bool = False) -> dict[str, Any]:
    data = _state()
    pairing = data.get("pairing") or {}
    waiting = bool(pairing) and time.time() < float(pairing.get("expires") or 0)
    peers = []
    for box_id, p in data["peers"].items():
        item = {
            "id": box_id,
            "name": p.get("name"),
            "address": p.get("address"),
            "paired_at": p.get("paired_at"),
            "offer_space": bool(p.get("offer_space")),
            "backup_repo": p.get("backup_repo") or "",
        }
        if with_summaries:
            item["summary"] = peer_summary(box_id)
        peers.append(item)
    return {"name": my_name(), "address": my_address(), "pairing_waiting": waiting, "peers": peers}


def reseal() -> int:
    """After a key rotation: seal the tokens sent to peers again."""
    with _lock:
        data = _state()
        for p in data["peers"].values():
            p["send"] = secret_box.seal(secret_box.unseal(p["send"]))
        if data["peers"]:
            _save(data)
    return len(data["peers"])


def audit(event: str, detail: str, actor: str) -> None:
    from backend.users_db import log_security_event

    try:
        log_security_event(event, "success", actor_username=actor or None, details={"what": detail})
    except (OSError, ValueError, TypeError, sqlite3.Error):
        logger.debug("[Fleet] could not write the security log", exc_info=True)
