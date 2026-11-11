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
from backend.ignored_errors import ignored

logger = logging.getLogger("Kiboto")

TOKEN_TTL_SECS = 120
_MAX_PENDING = 1000

# action -> what the user is asked (target is filled in from path parameters)
ACTIONS: dict[str, str] = {
    "fs.trash.empty": "Permanently delete everything in the trash",
    "storage.pool.create": "Create a storage pool, erasing the selected disks",
    "storage.pool.delete": "Delete storage pool {target}",
    "storage.snapshot.delete": "Delete snapshot {target}",
    "share.delete": "Delete share {target}",
    "users.delete": "Delete user {target}",
    "users.erase_data": "Erase the chats, Kib log and search data of user {target}",
    "users.export_data": "Download the chats, Kib log and search data of user {target}. They are told",
    "docker.container.delete": "Delete container {target}",
    "vm.delete": "Delete virtual machine {target}",
    "backup.delete": "Delete backup {target}",
    "system.restore": "Restore system settings from a backup, replacing the current ones",
    "offsite.restore_all": "Put every folder of backup {target} back where it was. Files that are already there stay as they are",
    "system.reboot": "Reboot the server",
    "system.shutdown": "Shut down the server",
    "updates.apply": "Update Kiboto and restart it",
    "updates.revert": "Revert Kiboto to the previous version and its data",
    "ai.index.forget": "Delete what the AI index learned from a folder",
    "webdav.config": "Change who can reach files over WebDAV and which folder it shares",
    "security.rotate_key": "Replace the install's secret key; everyone signs in to WebDAV and two-factor again",
    "docker.container.recreate.elevated": "Recreate container {target} with access to the host system",
    "ai.read_sleeping": "Let Kib read folders on sleeping drives. They spin up for it, and for every later reading while this is on",
    "disk.wake": "Wake sleeping drive {target}. It spins up now and goes back to sleep on its own later",
    "folder.wake": "Open {target}: its disk is asleep and spins up to show it, then goes back to sleep on its own later",
    "snapshot.rollback": "Put the whole share back as it was in snapshot {target}. How it is now is kept as a snapshot first",
    "share.make_subvolume": "Make share {target} snapshot-ready: its files move into a btrfs subvolume of the same name. Close files on it first; changes saved while it runs may be lost",
    "pool.scrub_schedule": "Check pool {target} for errors once a month. Its disks spin up for the check",
    "security.advisor_fix": "Apply the Security Advisor fix '{target}'. People may lose access they had before",
    "network.public_links": "Let anyone who has a share link open it from the internet, through Tailscale Funnel on port {target}. Only share links are reachable that way; the rest of the NAS stays private",
    "network.public_links_move_immich": "Publish share links, and move Immich to {target}. Share links need the port Immich's secure address uses now, and a port on the internet must carry nothing else. Phones and browsers that open Immich at the old address need the new one",
    "network.tailscale_install": "Start Tailscale in {target}, a container on this NAS's own network that may change its network settings. Tailscale needs that to connect your devices; nothing is opened on your router",
    "security.malware_scan": "Start ClamAV in {target} to scan files that arrive from outside. It needs about 1.5 GB of memory, briefly up to 3 GB, and downloads its signatures first",
    "security.malware_restore": "Put {target} back where it came from although ClamAV flagged it as malware",
    "security.malware_delete": "Delete {target} from quarantine for good",
    "users.family_signin": "Start Pocket ID in {target}, give it an https address in your tailnet and an account for each Kiboto user, so the family can sign in to apps with a passkey",
    "users.family_signin_app": "Let the family sign in to {target} with Pocket ID; a client secret for it is shown once",
    "fleet.pair": "Pair with the Kiboto box at {target}. Each box then sees the other's name, version, free space and backups",
    "fleet.offer_space": "Let {target} back up to this box. Its backups are append-only and encrypted with its own key; they use space here",
    "network.family_invite": "Invite {target} to reach this NAS from anywhere through their own Tailscale account. They see only this NAS and still sign in to Kiboto",
    "network.publish_app": "Put {target} on the internet through Tailscale Funnel. Anyone with its address reaches its own sign-in page; Kiboto's page stays private",
    "hardware.helper": "Move the fan and button hardware access into {target}, a small container with no network that alone opens /dev/mem. The next update takes that access away from Kiboto itself",
    "network.nas_name": "Let the NAS answer to {target} on the home network. A small helper on the host's network does it and only answers name lookups",
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
        ignored("backend.confirmations.confirm_or_raise")


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
