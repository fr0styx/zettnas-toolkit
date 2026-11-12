"""Chosen apps on the internet through Tailscale Funnel (RES-6), never Kiboto's own page.

Funnel publishes at most three ports (443, 8443 and 10000) with Tailscale's HTTPS certificate, and
it shares its port settings with `tailscale serve`: remote access serves Kiboto on 443 and Immich on
8443 inside the tailnet, and share links use 8443. An app therefore gets a port nothing serves yet
(10000, or 443 when remote access doesn't use it), so it is served from its root, as it expects.
Kiboto's Tailscale runs on the host's network, so Funnel reaches an app at
127.0.0.1:<the port it publishes on the host>.

Refused: Kiboto itself (its container, its sidecars, its web port), apps without a published TCP
port, and a port Tailscale already serves for anything. Apps that control the server (a Docker
manager, a log viewer with shell, a web terminal) are allowed only with their own warning, since
whoever gets past their sign-in owns the box. Turning one on is confirmed in the app and logged.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from typing import Any

from backend import legacy_names
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, locked_json, read_json
from backend.services import public_links, tailnet_ports

APP_PORTS = tailnet_ports.PUBLIC_APP_PORTS  # who owns which port: tailnet_ports
STATE_FILE = os.path.join(DATA_DIR, "public_apps.json")
PENDING_FILE = os.path.join(DATA_DIR, "public_apps_pending.json")  # one request waiting for the owner's steps
_CONTROL = re.compile(
    r"portainer|dockge|dockhand|dozzle|yacht|cockpit|webmin|ttyd|wetty|shellinabox|filebrowser|code-server|"
    r"guacamole|unraid|komodo|cosmos",
    re.I,
)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class PublishError(ValueError):
    """The app can't be published (the message says why)."""


def _docker(path: str) -> Any:
    from backend.services.container_mutator import docker_request

    try:
        code, body = docker_request("GET", path)
    except (OSError, RuntimeError):
        return None
    return body if code == 200 else None


def _own_port() -> int:
    from backend import settings

    return int(settings.current("port") or 8082)


def _is_kiboto(name: str, image: str) -> bool:
    n = name.lstrip("/").lower()
    return (
        legacy_names.is_app_container(n)
        or n.startswith(("kiboto", legacy_names.OLD_NAS_NAME))
        or "fr0styx/kiboto" in image
        or legacy_names.OLD_IMAGE_REPO in image
    )


def apps() -> list[dict[str, Any]]:
    """Running apps that publish a TCP port on the host, with whether each may go public."""
    own = _own_port()
    out = []
    for c in _docker("/containers/json") or []:
        name = ((c.get("Names") or ["/"])[0]).lstrip("/")
        image = str(c.get("Image") or "")
        ports = sorted(
            {
                int(p["PublicPort"])
                for p in c.get("Ports") or []
                if p.get("Type") == "tcp" and p.get("PublicPort") and p.get("IP") in (None, "", "0.0.0.0", "::")
            }
        )
        if not ports or _is_kiboto(name, image):
            continue
        out.append(
            {
                "name": name,
                "image": image,
                "ports": [p for p in ports if p != own],
                "controls_server": bool(_CONTROL.search(f"{name} {image}")),
            }
        )
    return sorted((a for a in out if a["ports"]), key=lambda a: a["name"].lower())


def _state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def recorded_ports() -> set[int]:
    """The Funnel ports Kiboto published an app on (its record)."""
    return {int(p) for p in _state() if str(p).isdigit()}


def _serve_config() -> tuple[dict[str, Any], dict[str, Any]]:
    """Every host:port Tailscale serves (tailnet or public) and which of them Funnel opens."""
    code, out = public_links._ts(["funnel", "status", "--json"], timeout=4.0)
    doc = tailnet_ports.parse_funnel_status(out) if code == 0 else None
    if doc is None:
        return {}, {}
    return doc.get("Web") or {}, doc.get("AllowFunnel") or {}


def _pending() -> dict[str, Any]:
    p = read_json(PENDING_FILE, {})
    if not isinstance(p, dict) or not p.get("name"):
        return {}
    if time.time() - float(p.get("since") or 0) > public_links.PENDING_SECONDS:
        return {}
    return p


# ports whose app was not found at the last look: an app is withdrawn only when it is missing twice
# in a row, so an update that recreates the container in between does not take it off the internet
_MISSING: set[str] = set()


def withdraw_gone() -> list[str]:
    """Takes an app off the internet when it is gone, or no longer publishes the port (SET-02).

    The public address belongs to a host port, not to the app: after the app was removed or its
    port changed, the next app to use that port was on the internet without anyone choosing it.
    Called once a minute; costs nothing while no app is published. A stopped app keeps its address."""
    state = _state()
    if not state:
        _MISSING.clear()
        return []
    containers = _docker("/containers/json?all=1")
    if containers is None:
        return []  # Docker did not answer: not the moment to decide
    by_name = {((c.get("Names") or ["/"])[0]).lstrip("/"): c for c in containers}
    withdrawn = []
    for port, entry in sorted(state.items()):
        c = by_name.get(str(entry.get("name")))
        ports = {int(p["PublicPort"]) for p in (c or {}).get("Ports") or [] if p.get("PublicPort")}
        running = bool(c) and str(c.get("State") or "running") == "running"
        still_there = bool(c) and (not running or int(entry.get("host_port") or 0) in ports)
        if still_there:
            _MISSING.discard(port)
        elif port not in _MISSING:
            _MISSING.add(port)
        else:
            _MISSING.discard(port)
            try:
                unpublish(int(port), actor="")
            except KeyError:
                continue
            _audit("public_app.withdrawn", f"{entry.get('name')} gone from :{entry.get('host_port')}, off :{port}", "")
            logger.warning("[PublicApps] %s is gone: its address on :%s is off the internet", entry.get("name"), port)
            withdrawn.append(str(entry.get("name")))
    return withdrawn


def status(finish_pending: bool = False) -> dict[str, Any]:
    """`finish_pending`: a request that waited for the tailnet owner's steps is carried out now.
    Only for someone who may change settings: reading the card must never publish anything (SET-02)."""
    ready = public_links.funnel_readiness()
    waiting = _pending()
    if finish_pending and waiting and ready["ready"]:
        atomic_write_json(PENDING_FILE, {})
        logger.info("[PublicApps] Funnel is allowed now: publishing %s", waiting["name"])
        try:
            return publish(
                waiting["name"], int(waiting["host_port"]), int(waiting["funnel_port"]), waiting.get("actor", "")
            )
        except PublishError as e:
            logger.warning("[PublicApps] the waiting request could not be finished: %s", e)
            waiting = {}
    dns = public_links._dns_name()
    web, allowed = _serve_config() if dns else ({}, {})
    published = []
    for port, entry in sorted(_state().items()):
        host = f"{dns}:{port}"
        handlers = (web.get(host) or {}).get("Handlers") or {} if allowed.get(host) else {}
        published.append(
            {
                **entry,
                "funnel_port": int(port),
                "url": f"https://{dns}" + ("" if int(port) == 443 else f":{port}") if dns else "",
                "live": "/" in handlers,
            }
        )
    taken = {int(p) for p in _state()} | {p for p in APP_PORTS if f"{dns}:{p}" in web}
    return {
        "tailscale": bool(dns),
        "funnel": ready,
        "pending": {"name": waiting["name"], "funnel_port": waiting["funnel_port"]} if waiting else None,
        "published": published,
        "free_ports": [p for p in APP_PORTS if p not in taken and (not ready["ports"] or p in ready["ports"])],
        "apps": apps() if dns else [],
    }


def publish(name: str, host_port: int, funnel_port: int, actor: str = "") -> dict[str, Any]:
    """Serves one app's port on a Funnel port of its own."""
    if not _NAME.match(name or ""):
        raise PublishError("Pick an app.")
    if funnel_port not in APP_PORTS:
        raise PublishError(f"Apps go on port {APP_PORTS[0]} or {APP_PORTS[1]}.")
    if host_port == _own_port():
        raise PublishError("That is Kiboto's own page; it never goes on the internet.")
    app = next((a for a in apps() if a["name"] == name), None)
    if not app:
        raise PublishError(f"{name} is not a running app with a published port.")
    if host_port not in app["ports"]:
        raise PublishError(f"{name} does not publish port {host_port}.")
    dns = public_links._dns_name()
    if not dns:
        raise PublishError("Tailscale isn't connected on this NAS.")
    if not public_links.funnel_readiness()["ready"]:
        # the owner's steps aren't done yet: keep the request; status() finishes it once they are
        atomic_write_json(
            PENDING_FILE,
            {"name": name, "host_port": host_port, "funnel_port": funnel_port, "actor": actor, "since": time.time()},
        )
        _audit("public_app.pending", f"{name}:{host_port} on :{funnel_port}", actor)
        return status()
    with locked_json(STATE_FILE):
        state = _state()
        if str(funnel_port) in state:
            raise PublishError(f"Port {funnel_port} already serves {state[str(funnel_port)]['name']}.")
        if f"{dns}:{funnel_port}" in _serve_config()[0]:  # remote access, Immich or share links use it
            raise PublishError(f"Tailscale already serves something on port {funnel_port}; pick another.")
        code, out = public_links._ts(
            ["funnel", "--bg", "--yes", f"--https={funnel_port}", f"http://127.0.0.1:{host_port}"], timeout=15.0
        )
        approval = public_links._APPROVAL.search(out or "")
        if code != 0 and not approval:
            raise PublishError((out or "Tailscale refused.").strip()[:300])
        state[str(funnel_port)] = {
            "name": name,
            "host_port": host_port,
            "controls_server": app["controls_server"],
            "since": time.time(),
            "approval_url": approval.group(0) if approval else "",
        }
        atomic_write_json(STATE_FILE, state)
    _audit("public_app.publish", f"{name}:{host_port} on :{funnel_port}", actor)
    logger.warning("[PublicApps] %s (port %s) is on the internet at :%s", name, host_port, funnel_port)
    return status()


def unpublish(funnel_port: int, actor: str = "") -> dict[str, Any]:
    if _pending().get("funnel_port") == funnel_port:  # a waiting request is withdrawn the same way
        atomic_write_json(PENDING_FILE, {})
        return status()
    with locked_json(STATE_FILE):
        state = _state()
        entry = state.pop(str(funnel_port), None)
        if entry is None:
            raise KeyError("Nothing is published on that port.")
        public_links._ts(["funnel", f"--https={funnel_port}", "off"], timeout=15.0)
        atomic_write_json(STATE_FILE, state)
    _audit("public_app.unpublish", f"{entry['name']} off :{funnel_port}", actor)
    return status()


def _audit(event: str, detail: str, actor: str) -> None:
    from backend.users_db import log_security_event

    try:
        log_security_event(event, "success", actor_username=actor or None, details={"what": detail})
    except (OSError, ValueError, TypeError, sqlite3.Error):
        logger.debug("[PublicApps] could not write the security log", exc_info=True)
