"""
Destructive-action standard: server-issued confirm tokens plus an audit entry.

Endpoints that delete, format, wipe, restore over, power off or update declare
`Depends(require_confirmation("<action>"))`. A request without a valid
X-Confirm-Token header gets 428 `confirmation_required` with a summary; the
web UI asks the user, fetches a token from POST /api/confirmations and repeats
the request. A token is single use, lasts 2 minutes, and is bound to the user,
the action and its target (the route's path parameters). Every confirmed
action is written to the security audit log.

Scripts using API tokens follow the same two steps, which keeps one stray
request (or an AI tool call) from wiping data on its own.
"""

import logging
import secrets
import threading
import time
from typing import Any, Optional

from fastapi import Depends, Request

from backend.auth import AuthenticatedPrincipal, get_current_principal

logger = logging.getLogger("ZettNAS")

TOKEN_TTL_SECS = 120
_MAX_PENDING = 1000

# action -> what the user is asked (target is filled in from path parameters)
ACTIONS: dict[str, str] = {
    "fs.trash.empty": "Permanently delete everything in the trash",
    "storage.pool.create": "Create a storage pool, erasing the selected disks",
    "storage.pool.delete": "Delete storage pool {target}",
    "storage.snapshot.delete": "Delete snapshot {target}",
    "storage.snapshot.restore": "Roll the pool back to snapshot {target}; newer changes are lost",
    "share.delete": "Delete share {target}",
    "users.delete": "Delete user {target}",
    "users.erase_data": "Erase the chats, Zetty log and search data of user {target}",
    "docker.container.delete": "Delete container {target}",
    "vm.delete": "Delete virtual machine {target}",
    "backup.delete": "Delete backup {target}",
    "system.restore": "Restore system settings from a backup, replacing the current ones",
    "system.reboot": "Reboot the server",
    "system.shutdown": "Shut down the server",
    "updates.apply": "Update ZettNAS and restart it",
    "updates.revert": "Revert ZettNAS to the previous version and its data",
    "ai.index.forget": "Delete what the AI index learned from a folder",
    "webdav.config": "Change who can reach files over WebDAV and which folder it shares",
    "security.rotate_key": "Replace the install's secret key; everyone signs in to WebDAV and two-factor again",
    "docker.container.recreate.elevated": "Recreate container {target} with access to the host system",
    "disk.wake": "Wake sleeping drive {target}. It spins up now and goes back to sleep on its own later",
}

_pending: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


class ConfirmationRequired(Exception):
    def __init__(self, action: str, target: str, reason: str = "missing"):
        self.action = action
        self.target = target
        self.reason = reason
        super().__init__(action)

    @property
    def summary(self) -> str:
        return ACTIONS.get(self.action, self.action).format(target=self.target or "").strip()


def _owner(principal: Any) -> str:
    return str(getattr(principal, "user_id", "") or getattr(principal, "username", "") or "")


def issue(principal: Any, action: str, target: str = "") -> str:
    if action not in ACTIONS:
        raise ValueError(f"Unknown action '{action}'")
    owner = _owner(principal)
    if not owner:
        raise ValueError("Not signed in")
    now = time.time()
    token = "zcf_" + secrets.token_urlsafe(24)
    with _lock:
        for k in [k for k, v in _pending.items() if v["expires_at"] < now]:
            del _pending[k]
        if len(_pending) >= _MAX_PENDING:
            del _pending[min(_pending, key=lambda k: _pending[k]["expires_at"])]
        _pending[token] = {"owner": owner, "action": action, "target": target, "expires_at": now + TOKEN_TTL_SECS}
    return token


def consume(token: str | None, principal: Any, action: str, target: str = "") -> bool:
    if not token:
        return False
    with _lock:
        entry = _pending.pop(token, None)
    return bool(
        entry
        and entry["expires_at"] >= time.time()
        and entry["owner"] == _owner(principal)
        and entry["action"] == action
        and entry["target"] == target
    )


def target_of(request: Request) -> str:
    params = dict(request.path_params or {})
    return "/".join(str(params[k]) for k in sorted(params)) if params else ""


def require_confirmation(action: str):
    """FastAPI dependency: the request must carry a confirm token for this action and target."""
    if action not in ACTIONS:
        raise ValueError(f"Unknown action '{action}'")

    async def _dep(request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> None:
        confirm_or_raise(request, principal, action, target_of(request))

    return _dep


def confirm_or_raise(request: Request, principal: Any, action: str, target: str = "") -> None:
    """The same check for a route that needs confirming only sometimes (a drive that is asleep):
    raises ConfirmationRequired (428) unless the request carries a valid token, and audits it."""
    token = request.headers.get("x-confirm-token")
    if not consume(token, principal, action, target):
        raise ConfirmationRequired(action, target, "invalid" if token else "missing")
    try:
        from backend.users_db import log_security_event

        log_security_event(
            f"confirm.{action}",
            "success",
            actor_id=getattr(principal, "user_id", None),
            actor_username=getattr(principal, "username", None),
            actor_ip=request.client.host if request.client else "",
            details={"target": target, "path": request.url.path},
        )
    except Exception:
        logger.debug("backend.confirmations.confirm_or_raise: ignored error", exc_info=True)


async def confirmation_required_handler(request: Request, exc: ConfirmationRequired):
    from backend.errors import error_response

    return error_response(
        428,
        exc.summary + ". Confirm to continue.",
        error="confirmation_required",
        action=exc.action,
        target=exc.target,
        summary=exc.summary,
    )
