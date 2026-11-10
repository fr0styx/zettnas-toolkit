"""Passkeys (RES-3): sign in with a phone, a laptop's fingerprint reader or a security key (WebAuthn).

A passkey works as the second step after the password, in place of the six-digit code, or on its own:
it proves both what you hold and, with the device's PIN or fingerprint (user verification, required
here), who you are. Verification is Yubico's fido2 library.

Browsers offer passkeys only on a secure page with a name: https://<name> (a Tailscale address, a
reverse proxy) or http://localhost, never http://<an IP address>. The name a passkey is made on is
its relying party id; it works only there. The challenges wait here, server side, for five minutes
and are used once.
"""

from __future__ import annotations

import base64
import ipaddress
import secrets
import threading
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from fido2.server import Fido2Server
from fido2.webauthn import (
    AttestedCredentialData,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from backend.config import logger
from backend.services import mfa_policy

RP_NAME = "Kiboto"
TICKET_SECONDS = 300
MAX_PER_USER = 20
_TICKETS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


class PasskeyError(ValueError):
    """A passkey step that can't go on (the message says why)."""


def _db():
    from backend.users_db import users_db_session

    return users_db_session()


def rp_id_for(host: str) -> str:
    """The relying party id for the address the browser is on (the Host header, without the port)."""
    name = urlsplit(f"//{host or ''}").hostname or ""
    try:
        ipaddress.ip_address(name)
        is_ip = True
    except ValueError:
        is_ip = False
    if not name or is_ip:
        raise PasskeyError(
            "Passkeys need Kiboto's address with a name over https (for example its Tailscale address), "
            "not an IP address."
        )
    return name.lower()


def _server(rp_id: str) -> Fido2Server:
    def origin_ok(origin: str) -> bool:
        parts = urlsplit(origin)
        secure = parts.scheme == "https" or (parts.scheme == "http" and parts.hostname == "localhost")
        return secure and (parts.hostname or "").lower() == rp_id

    return Fido2Server(PublicKeyCredentialRpEntity(id=rp_id, name=RP_NAME), verify_origin=origin_ok)


def _put(kind: str, state: Any, rp_id: str, user_id: str = "", extra: dict[str, Any] | None = None) -> str:
    ticket = secrets.token_urlsafe(24)
    now = time.time()
    with _LOCK:
        for k in [k for k, v in _TICKETS.items() if v["expires"] < now]:
            _TICKETS.pop(k, None)
        _TICKETS[ticket] = {
            "kind": kind,
            "state": state,
            "rp_id": rp_id,
            "user_id": user_id,
            "expires": now + TICKET_SECONDS,
            **(extra or {}),
        }
    return ticket


def _take(ticket: str, kind: str) -> dict[str, Any]:
    with _LOCK:
        entry = _TICKETS.pop(ticket or "", None)
    if not entry or entry["kind"] != kind or entry["expires"] < time.time():
        raise PasskeyError("This passkey request expired. Try again.")
    return entry


def _rows(user_id: str, rp_id: str | None = None) -> list[Any]:
    with _db() as conn:
        if rp_id is None:
            return conn.execute("SELECT * FROM passkeys WHERE user_id = ? ORDER BY created_at", (user_id,)).fetchall()
        return conn.execute(
            "SELECT * FROM passkeys WHERE user_id = ? AND rp_id = ? ORDER BY created_at", (user_id, rp_id)
        ).fetchall()


def list_for(user_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "rp_id": r["rp_id"],
            "created_at": r["created_at"],
            "last_used_at": r["last_used_at"],
        }
        for r in _rows(user_id)
    ]


def has_passkeys(user_id: str) -> bool:
    with _db() as conn:
        return conn.execute("SELECT 1 FROM passkeys WHERE user_id = ? LIMIT 1", (user_id,)).fetchone() is not None


def users_with_passkeys() -> set[str]:
    """Everyone who has at least one passkey (for the "without two-step sign-in" counts)."""
    with _db() as conn:
        return {r[0] for r in conn.execute("SELECT DISTINCT user_id FROM passkeys").fetchall()}


def count_for(user_id: str) -> int:
    with _db() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM passkeys WHERE user_id = ?", (user_id,)).fetchone()[0])


def register_options(user: dict[str, Any], host: str) -> dict[str, Any]:
    rp_id = rp_id_for(host)
    existing = [AttestedCredentialData(r["credential"]) for r in _rows(user["id"], rp_id)]
    if len(_rows(user["id"])) >= MAX_PER_USER:
        raise PasskeyError(f"You have {MAX_PER_USER} passkeys; remove one to add another.")
    options, state = _server(rp_id).register_begin(
        PublicKeyCredentialUserEntity(
            id=user["id"].encode(),
            name=user["username"],
            display_name=user.get("display_name") or user["username"],
        ),
        existing,
        resident_key_requirement=ResidentKeyRequirement.REQUIRED,  # usable without typing a name
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return {"ticket": _put("register", state, rp_id, user["id"]), "options": dict(options)}


def register_finish(user: dict[str, Any], ticket: str, response: dict[str, Any], name: str = "") -> dict[str, Any]:
    entry = _take(ticket, "register")
    if entry["user_id"] != user["id"]:
        raise PasskeyError("This passkey request belongs to someone else.")
    try:
        auth_data = _server(entry["rp_id"]).register_complete(entry["state"], response)
    except (ValueError, KeyError, TypeError) as e:
        raise PasskeyError(f"The passkey could not be checked: {e}") from e
    cred = auth_data.credential_data
    if cred is None:
        raise PasskeyError("The device sent no passkey.")
    clean = (name or "").strip()[:60] or "Passkey"
    pk_id = uuid.uuid4().hex
    with _db() as conn:
        if conn.execute("SELECT 1 FROM passkeys WHERE credential_id = ?", (bytes(cred.credential_id),)).fetchone():
            raise PasskeyError("This passkey is already added.")
        conn.execute(
            "INSERT INTO passkeys (id, user_id, credential_id, credential, rp_id, name, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pk_id, user["id"], bytes(cred.credential_id), bytes(cred), entry["rp_id"], clean, time.time()),
        )
    logger.info("[Passkeys] %s added a passkey (%s) for %s", user["username"], clean, entry["rp_id"])
    return {"id": pk_id, "name": clean}


def login_options(host: str, user_id: str = "", extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Options for signing in: the person's own passkeys when user_id is given (the second step after
    the password), else any passkey on this address (sign-in with the passkey alone)."""
    rp_id = rp_id_for(host)
    creds = [AttestedCredentialData(r["credential"]) for r in _rows(user_id, rp_id)] if user_id else None
    if user_id and not creds:
        raise PasskeyError("You have no passkey for this address.")
    options, state = _server(rp_id).authenticate_begin(creds, user_verification=UserVerificationRequirement.REQUIRED)
    return {"ticket": _put("login", state, rp_id, user_id, extra), "options": dict(options)}


def _b64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def login_finish(ticket: str, response: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Checks a signed challenge; returns the person's id and what the ticket carried."""
    entry = _take(ticket, "login")
    try:
        raw_id = _b64(str(response.get("rawId") or response.get("id") or ""))
    except (ValueError, TypeError) as e:
        raise PasskeyError("The device sent a damaged answer.") from e
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM passkeys WHERE credential_id = ? AND rp_id = ?", (raw_id, entry["rp_id"])
        ).fetchone()
    if not row or (entry["user_id"] and row["user_id"] != entry["user_id"]):
        raise PasskeyError("This passkey isn't known here.")
    try:
        _server(entry["rp_id"]).authenticate_complete(
            entry["state"], [AttestedCredentialData(row["credential"])], response
        )
    except (ValueError, KeyError, TypeError) as e:
        raise PasskeyError("The passkey's signature did not check out.") from e
    with _db() as conn:
        conn.execute("UPDATE passkeys SET last_used_at = ? WHERE id = ?", (time.time(), row["id"]))
    extra = {k: v for k, v in entry.items() if k not in ("kind", "state", "rp_id", "user_id", "expires")}
    return row["user_id"], extra


def rename(user_id: str, pk_id: str, name: str) -> bool:
    clean = (name or "").strip()[:60]
    if not clean:
        raise PasskeyError("Give the passkey a name.")
    with _db() as conn:
        return (
            conn.execute("UPDATE passkeys SET name = ? WHERE id = ? AND user_id = ?", (clean, pk_id, user_id)).rowcount
            > 0
        )


def delete(user_id: str, pk_id: str) -> bool:
    with _db() as conn:
        return conn.execute("DELETE FROM passkeys WHERE id = ? AND user_id = ?", (pk_id, user_id)).rowcount > 0


def forget_user(user_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM passkeys WHERE user_id = ?", (user_id,))


def _protects(user: dict[str, Any]) -> bool:
    return bool(user.get("id")) and has_passkeys(user["id"])


# a passkey is a second step too: the role rule asks here (mfa_policy sits below and can't import us)
mfa_policy.SECOND_STEPS.append(_protects)
