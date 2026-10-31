"""The family calendar and address book (NFEAT-7): Nextcloud's Calendar and Contacts apps in the
office suite, so the phones sync a shared calendar and contacts kept at home.

New installs of the office suite add them as part of their set-up (catalog_templates, its
"after_start"); an office suite installed before can add them with one click (add_apps). The
phones reach them at Nextcloud's DAV address, signing in with their ZettNAS account.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from backend.config import logger

OCC = "php /var/www/html/occ"
STEPS = [
    {
        "label": "Adding the family calendar",
        "cmd": ["sh", "-c", f"{OCC} app:install calendar || {OCC} app:enable calendar"],
        "user": "www-data",
        "tries": 2,
        "every": 15,
        "timeout": 300,
    },
    {
        "label": "Adding the family address book",
        "cmd": ["sh", "-c", f"{OCC} app:install contacts || {OCC} app:enable contacts"],
        "user": "www-data",
        "tries": 2,
        "every": 15,
        "timeout": 300,
    },
]


def office_container() -> dict[str, Any] | None:
    """The office suite ZettNAS installed: its container name, whether it runs, its web port."""
    from backend.services import docker_client

    query = urllib.parse.quote(json.dumps({"label": ["com.zettnas.managed=1"]}))
    try:
        status, found = docker_client.request("GET", f"/containers/json?all=1&filters={query}")
    except (OSError, ValueError, docker_client.DockerUnavailable):
        logger.debug("family_dav: containers unknown", exc_info=True)
        return None
    if status != 200 or not isinstance(found, list):
        return None
    for c in found:
        if not str(c.get("Image") or "").startswith("nextcloud"):
            continue
        port = next(
            (p.get("PublicPort") for p in c.get("Ports") or [] if p.get("PrivatePort") == 80 and p.get("PublicPort")),
            None,
        )
        names = [n.lstrip("/") for n in c.get("Names") or []]
        return {
            "name": names[0] if names else c.get("Id", "")[:12],
            "running": c.get("State") == "running",
            "port": port,
        }
    return None


def addresses(host: str, port: int | None) -> dict[str, str]:
    """Where phones find the calendar and contacts (one DAV address serves both)."""
    base = f"{host}:{port}" if port else host
    dav = f"http://{base}/remote.php/dav"
    return {"server": base, "caldav": dav, "carddav": dav}


def status(host: str) -> dict[str, Any]:
    office = office_container()
    if not office:
        return {"installed": False}
    from backend.services.app_after_start import valid_host

    return {
        "installed": True,
        "running": office["running"],
        **addresses(valid_host(host) or "localhost", office["port"]),
    }


def add_apps() -> dict[str, Any]:
    """Adds Calendar and Contacts to an office suite installed before they were part of it."""
    from backend.services import app_after_start

    office = office_container()
    if not office or not office["running"]:
        raise ValueError("Start the office suite first, then add the calendar and contacts.")
    added, failed = [], []
    for step in STEPS:
        code, out = app_after_start.exec_in(office["name"], step["cmd"], step["user"], step["timeout"])
        (added if code == 0 else failed).append(step["label"])
        if code != 0:
            logger.warning("[family_dav] %s didn't finish: %s", step["label"], (out or "")[-300:])
    return {"added": added, "failed": failed}
