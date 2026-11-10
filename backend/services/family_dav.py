"""The family calendar and address book (NFEAT-7): Nextcloud's Calendar and Contacts apps in the
office suite, so the phones sync a shared calendar and contacts kept at home.

New installs of the office suite add them as part of their set-up (catalog_templates, its
"after_start"); an office suite installed before can add them with one click (add_apps). The
phones reach them at Nextcloud's DAV address, signing in with their Kiboto account.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from backend import legacy_names
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
    """The office suite Kiboto installed: its container name, whether it runs, its web port."""
    from backend.services import docker_client

    found: list = []
    for label in legacy_names.managed_labels():  # made before the rebrand: only the old label
        query = urllib.parse.quote(json.dumps({"label": [f"{label}=1"]}))
        try:
            status, some = docker_client.request("GET", f"/containers/json?all=1&filters={query}")
        except (OSError, ValueError, docker_client.DockerUnavailable):
            logger.debug("family_dav: containers unknown", exc_info=True)
            return None
        if status == 200 and isinstance(some, list):
            found += [c for c in some if c.get("Id") not in {f.get("Id") for f in found}]
    if not found:
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


_SHARED_CALENDAR = re.compile(r"/remote\.php/dav/public-calendars/([A-Za-z0-9]{8,64})/?")


def family_calendar_url(url: str) -> str | None:
    """The address Kiboto reads a family calendar from, for the office suite's own subscription link.

    In the office suite's Calendar, Share → Copy subscription link gives
    webcal://<this NAS>:<its port>/remote.php/dav/public-calendars/<token>?export. That is a
    home address, which calendar feeds may not use; this link alone may, and only on the port
    the office suite answers on (NFEAT-7). Anything else gives None.
    """
    try:
        parts = urllib.parse.urlsplit(str(url or "").strip())
        port = parts.port
    except ValueError:
        return None
    found = _SHARED_CALENDAR.fullmatch(parts.path)
    if parts.scheme not in ("webcal", "http", "https") or not parts.hostname or not found or not port:
        return None
    office = office_container()
    if not office or office.get("port") != port:
        return None
    return f"http://{parts.hostname}:{port}/remote.php/dav/public-calendars/{found.group(1)}?export"


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


def ios_profile(host: str, port: int | None) -> bytes:
    """A configuration profile that adds the family calendar and contacts to an iPhone or iPad
    (NFEAT-7): a CalDAV and a CardDAV account at the office suite. It holds no name or password;
    the phone asks for the person's Kiboto name and password, so one profile serves everyone."""
    import plistlib
    import uuid

    ident = f"zettnas.family.{host}"

    def account(kind: str, prefix: str, label: str) -> dict[str, Any]:
        return {
            "PayloadType": f"com.apple.{kind}.account",
            "PayloadIdentifier": f"{ident}.{kind}",
            "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ident}.{kind}")).upper(),
            "PayloadVersion": 1,
            "PayloadDisplayName": label,
            f"{prefix}AccountDescription": label,
            f"{prefix}HostName": host,
            f"{prefix}Port": int(port or 80),
            f"{prefix}PrincipalURL": "/remote.php/dav",
            f"{prefix}UseSSL": False,
        }

    return plistlib.dumps(
        {
            "PayloadType": "Configuration",
            "PayloadVersion": 1,
            "PayloadIdentifier": ident,
            "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_URL, ident)).upper(),
            "PayloadDisplayName": "Kiboto family calendar and contacts",
            "PayloadDescription": "Adds the family calendar and contacts kept on Kiboto.",
            "PayloadContent": [
                account("caldav", "CalDAV", "Family calendar"),
                account("carddav", "CardDAV", "Family contacts"),
            ],
        }
    )


def ios_profile_for(host: str) -> bytes | None:
    """The profile for the office suite on this server, None when it isn't installed."""
    office = office_container()
    if not office:
        return None
    from backend.services.app_after_start import valid_host

    return ios_profile(valid_host(host) or "localhost", office["port"])


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
