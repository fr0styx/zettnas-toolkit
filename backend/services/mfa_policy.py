"""Two-step sign-in required by role (an administrator's choice).

Someone in such a role who hasn't turned two-step sign-in on can still sign in, but until they set
it up, the API answers only what setting it up needs; the auth middleware refuses the rest.
Accounts that sign in through an identity provider (OpenID Connect) are left to that provider,
which asks for its own second step.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

POLICY_FILE = os.path.join(DATA_DIR, "mfa_policy.json")
CACHE_SECS = 10.0

_LOCK = threading.Lock()
_POLICY: dict[str, Any] = {"at": -1e9, "roles": frozenset()}
_ACCOUNTS: dict[str, tuple[float, bool]] = {}  # user id -> (when read, needs two-step sign-in set up)


def required_roles() -> frozenset[str]:
    """The roles whose people must use two-step sign-in."""
    now = time.monotonic()
    with _LOCK:
        if now - _POLICY["at"] < CACHE_SECS:
            return _POLICY["roles"]
    data = read_json(POLICY_FILE, default={}) or {}
    roles = frozenset(str(r) for r in data.get("required_roles") or [] if isinstance(r, str) and r)
    with _LOCK:
        _POLICY.update(at=now, roles=roles)
    return roles


def set_required_roles(roles: list[str]) -> list[str]:
    clean = sorted({str(r) for r in roles if isinstance(r, str) and r})
    atomic_write_json(POLICY_FILE, {"required_roles": clean})
    with _LOCK:
        _POLICY.update(at=-1e9)
        _ACCOUNTS.clear()
    return clean


def forget(user_id: str) -> None:
    """Called when someone turns two-step sign-in on or off, so the gate sees it at once."""
    with _LOCK:
        _ACCOUNTS.pop(str(user_id), None)


# Other second steps register a check here, each saying whether it protects an account (passkeys);
# this module sits below them and doesn't import them.
SECOND_STEPS: list[Callable[[dict[str, Any]], bool]] = []


def account_needs_setup(user: dict[str, Any] | None) -> bool:
    """A person in a role that requires two-step sign-in who hasn't turned it on (not a directory
    account signing in through OpenID Connect)."""
    if not user or user.get("role_id") not in required_roles():
        return False
    if user.get("idp_type") == "oidc" and not user.get("password_hash"):
        return False
    if user.get("mfa_enabled"):
        return False
    return not any(check(user) for check in SECOND_STEPS)  # a passkey, when that module is loaded (RES-3)


def setup_pending(sess: dict[str, Any] | None, lookup: Callable[[str], dict[str, Any] | None]) -> bool:
    """For a session: whether its person still has to set up two-step sign-in. lookup: the account by
    id (users_db.get_user_by_id, passed in so this module stays below the auth layer)."""
    if not sess or sess.get("is_system") or sess.get("is_proxy_sso"):
        return False
    if sess.get("role_id") not in required_roles():
        return False
    user_id = str(sess.get("user_id") or "")
    if not user_id:
        return False
    now = time.monotonic()
    with _LOCK:
        hit = _ACCOUNTS.get(user_id)
    if hit and now - hit[0] < CACHE_SECS:
        return hit[1]
    pending = account_needs_setup(lookup(user_id))
    with _LOCK:
        _ACCOUNTS[user_id] = (now, pending)
    return pending
