"""Each app Kiboto talks to by name gets a Docker network of its own with Kiboto (NSEC-10).

The office suite, Frigate and AdGuard Home used to join Kiboto's own network so Kiboto could
reach them by name without publishing a port. That network also holds Kiboto's model servers,
which answer without a sign-in, so a compromised app could reach them. Now each such app gets
"kiboto-app-<id>": a bridge with only that app and Kiboto on it. Names still resolve, the
apps still reach the internet, and an app sees neither the model servers nor the other apps.

An update recreates Kiboto's container on its main network only, so Kiboto rejoins every app
network when it starts. Apps installed before this keep the network they were installed on,
and one made before the rebrand keeps its zettnas-app- name.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.parse
from typing import Any

from backend import legacy_names, product
from backend.config import logger
from backend.services import docker_client

PREFIX = "kiboto-app-"
APP_LABEL = product.APP_LABEL


def network_name(app_id: str) -> str:
    """The app's own network: kiboto-app- and its id, lower case, in Docker's name characters."""
    clean = re.sub(r"[^a-z0-9_.-]+", "-", str(app_id or "app").lower()).strip("-.") or "app"
    return PREFIX + clean[:40]


def _me() -> dict[str, Any] | None:
    """Kiboto's own container, or None when it doesn't run in one (or Docker is out of reach)."""
    try:
        status, me = docker_client.request("GET", f"/containers/{socket.gethostname()}/json")
    except docker_client.DockerUnavailable:
        return None
    return me if status == 200 and isinstance(me, dict) else None


def _joined(me: dict[str, Any]) -> set[str]:
    return set(((me.get("NetworkSettings") or {}).get("Networks") or {}).keys())


def _join(me: dict[str, Any], name: str) -> bool:
    if name in _joined(me):
        return True
    status, _ = docker_client.request(
        "POST",
        f"/networks/{urllib.parse.quote(name)}/connect",
        # apps set up before the rebrand were given Kiboto's old container name (legacy_names)
        body={"Container": me.get("Id"), "EndpointConfig": {"Aliases": [legacy_names.OLD_APP_CONTAINER]}},
    )
    return status == 200


def private_network(app_id: str) -> str | None:
    """The app's own network with Kiboto on it, made when missing; None when Kiboto isn't in a
    container or Docker refuses (the app then installs on Docker's default network)."""
    me = _me()
    if not me:
        return None
    name = network_name(app_id)
    try:
        status, _ = docker_client.request("GET", f"/networks/{urllib.parse.quote(name)}")
        if status == 404:
            old = legacy_names.OLD_APP_NETWORK_PREFIX + name[len(PREFIX) :]  # the app's network made before
            old_status, _ = docker_client.request("GET", f"/networks/{urllib.parse.quote(old)}")
            if old_status == 200:
                return old if _join(me, old) else None
            labels = {**legacy_names.managed_labels(), APP_LABEL: str(app_id), legacy_names.OLD_APP_LABEL: str(app_id)}
            body = {"Name": name, "Driver": "bridge", "Labels": labels}
            status, _ = docker_client.request("POST", "/networks/create", body=body)
            if status not in (200, 201, 409):
                return None
        elif status != 200:
            return None
        return name if _join(me, name) else None
    except docker_client.DockerUnavailable:
        logger.warning("app_networks: Docker went away while making %s", name)
        return None


def rejoin() -> int:
    """Puts Kiboto back on every app network it left (after an update); how many it joined.
    Never raises: it runs in the background at start."""
    me = _me()
    if not me:
        return 0
    joined = 0
    try:
        nets: list = []
        for label in (APP_LABEL, legacy_names.OLD_APP_LABEL):  # networks made before carry the old one
            query = urllib.parse.quote(json.dumps({"label": [label]}))
            status, some = docker_client.request("GET", f"/networks?filters={query}")
            if status == 200 and isinstance(some, list):
                nets += some
        for name in sorted({str(n.get("Name") or "") for n in nets}):
            if (
                name.startswith((PREFIX, legacy_names.OLD_APP_NETWORK_PREFIX))
                and name not in _joined(me)
                and _join(me, name)
            ):
                joined += 1
    except (docker_client.DockerError, OSError, ValueError):
        logger.warning("app_networks: could not rejoin the app networks", exc_info=True)
    if joined:
        logger.info("app_networks: rejoined %d app network(s)", joined)
    return joined
