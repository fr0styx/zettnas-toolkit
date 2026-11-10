"""Each app Kiboto talks to by name gets a Docker network of its own with Kiboto (NSEC-10).

The office suite, Frigate and AdGuard Home used to join Kiboto's own network so Kiboto could
reach them by name without publishing a port. That network also holds Kiboto's model servers,
which answer without a sign-in, so a compromised app could reach them. Now each such app gets
"zettnas-app-<id>": a bridge with only that app and Kiboto on it. Names still resolve, the
apps still reach the internet, and an app sees neither the model servers nor the other apps.

An update recreates Kiboto's container on its main network only, so Kiboto rejoins every app
network when it starts. Apps installed before this keep the network they were installed on.
"""

from __future__ import annotations

import json
import re
import socket
import urllib.parse
from typing import Any

from backend.config import logger
from backend.services import docker_client

PREFIX = "zettnas-app-"
APP_LABEL = "com.zettnas.app"


def network_name(app_id: str) -> str:
    """The app's own network: zettnas-app- and its id, lower case, in Docker's name characters."""
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
        "POST", f"/networks/{urllib.parse.quote(name)}/connect", body={"Container": me.get("Id")}
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
            body = {"Name": name, "Driver": "bridge", "Labels": {"com.zettnas.managed": "1", APP_LABEL: str(app_id)}}
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
        query = urllib.parse.quote(json.dumps({"label": [APP_LABEL]}))
        status, nets = docker_client.request("GET", f"/networks?filters={query}")
        if status != 200 or not isinstance(nets, list):
            return 0
        for net in nets:
            name = str(net.get("Name") or "")
            if name.startswith(PREFIX) and name not in _joined(me) and _join(me, name):
                joined += 1
    except (docker_client.DockerError, OSError, ValueError):
        logger.warning("app_networks: could not rejoin the app networks", exc_info=True)
    if joined:
        logger.info("app_networks: rejoined %d app network(s)", joined)
    return joined
