"""Backup space on a paired box (RES-9): "buddy backups", append-only and encrypted.

The box giving space runs the catalog's restic REST server (append-only, private repositories,
FEAT-08). When its owner lets a paired box back up there, that box can ask for space: the giving
box makes it a REST account of its own (a random password, the folder named after the account) and
answers with the address. The asking box then keeps an off-site backup there like any other
(Backup → Off-site), encrypted with its own key, which the giving box never sees. Append-only: the
asking box can add versions but never delete any, so ransomware on it can't wipe the copies.
"""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlsplit

from backend.config import logger
from backend.services import fleet

REST_IMAGE = "restic/rest-server"
REST_PORT = "8000/tcp"


class BuddyError(fleet.FleetError):
    """No space to give, or the backup couldn't be set up."""


def _rest_server() -> tuple[str, int]:
    """The running REST server container and its host port; BuddyError when there is none."""
    from backend.services import docker_client

    try:
        code, found = docker_client.request("GET", "/containers/json")
    except (OSError, ValueError, RuntimeError, docker_client.DockerUnavailable):
        code, found = 0, None
    if code != 200 or not isinstance(found, list):
        raise BuddyError("Docker didn't answer on the box giving space.")
    for c in found:
        if not str(c.get("Image") or "").startswith(REST_IMAGE):
            continue
        for port in c.get("Ports") or []:
            if port.get("PrivatePort") == 8000 and port.get("PublicPort"):
                return str((c.get("Names") or ["/rest-server"])[0]).lstrip("/"), int(port["PublicPort"])
    raise BuddyError(
        "The box giving space needs the Backup target (restic REST server) app from the App Catalog, running."
    )


def account_for(box_id: str) -> str:
    return f"kb-{box_id[:12]}"


def give_space(box_id: str) -> dict[str, Any]:
    """On the giving box, for a paired box that asked: a REST account and where to find it."""
    peer = fleet.peer(box_id)
    if not peer.get("offer_space"):
        raise BuddyError("The owner of that box hasn't allowed backups from this one yet.")
    container, port = _rest_server()
    host = urlsplit(fleet.my_address()).hostname or ""
    if not host:
        raise BuddyError("The box giving space isn't connected to Tailscale.")
    from backend.services.app_after_start import exec_in

    user = account_for(box_id)
    password = secrets.token_urlsafe(24)
    code, out = exec_in(container, ["create_user", user, password], timeout=30)
    if code != 0:
        logger.warning("[Fleet] create_user failed for %s: %s", user, out[:200])
        raise BuddyError("The REST server didn't make the account.")
    fleet.audit("fleet.space_given", str(peer.get("name") or ""), "")
    return {"location": f"rest:http://{host}:{port}/{user}/", "user": user, "password": password}


def back_up_to(box_id: str, paths: list[str], actor: str = "") -> dict[str, Any]:
    """On the asking box: asks the paired box for space and sets up an off-site backup there."""
    from backend.services import offsite_backup

    peer = fleet.peer(box_id)
    got = fleet.call_peer(box_id, "buddy", "POST", {})
    if not isinstance(got, dict) or not str(got.get("location") or "").startswith("rest:http"):
        raise BuddyError("The other box didn't give space.")
    repo_id = f"buddy-{box_id[:8]}"
    try:
        offsite_backup.save_repo(
            repo_id,
            f"Buddy: {peer.get('name') or 'Kiboto'}",
            str(got["location"]),
            paths,
            rest_user=str(got.get("user") or ""),
            rest_password=str(got.get("password") or ""),
        )
    except ValueError as e:
        raise BuddyError(str(e)) from None
    try:
        offsite_backup.init(repo_id)
    except (offsite_backup.ResticError, OSError) as e:
        logger.warning("[Fleet] The buddy backup couldn't start its repository: %s", e)
    fleet.set_backup(box_id, repo_id)
    fleet.audit("fleet.buddy_backup", str(peer.get("name") or ""), actor)
    return fleet.status()
