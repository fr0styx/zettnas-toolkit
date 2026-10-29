"""Use ZettNAS from anywhere (COMP-01), without opening a port on the router.

Tailscale (a free account) or a Headscale server of your own puts this NAS and your phone in
one private network. Then `tailscale serve` gives ZettNAS, and Immich when it is installed,
HTTPS addresses under the node's MagicDNS name, which the phone opens like any website:

    https://<name>.<tailnet>.ts.net/          ZettNAS
    https://<name>.<tailnet>.ts.net:8443/     Immich

Without HTTPS certificates (turned off in the tailnet, or a Headscale server) the addresses
are plain http on the tailnet name or address; the traffic is still encrypted by WireGuard.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from backend.hardware.net import tailscale, tailscale_setup

IMMICH_HTTPS_PORT = 8443
DEFAULT_APP_PORT = 8082


class RemoteAccessError(RuntimeError):
    pass


def _json(args: list[str]) -> tuple[int, dict[str, Any]]:
    code, out = tailscale.run_cli(args, timeout=4.0)
    text = (out or "").strip()
    if code != 0 or not text.startswith("{"):
        return code, {}
    try:
        doc = json.loads(text)
    except ValueError:
        return code, {}
    return code, doc if isinstance(doc, dict) else {}


def _served_ports() -> set[int]:
    """The HTTPS ports `tailscale serve` answers on."""
    _code, doc = _json(["serve", "status", "--json"])
    return {int(p) for p in (doc.get("TCP") or {}) if str(p).isdigit()}


def immich_port() -> int | None:
    """The host port Immich is published on, when it runs here."""
    from backend.services.immich_photos import detect

    port = urlsplit(detect()).port
    return int(port) if port else None


def _app_port() -> int:
    return int(tailscale.settings().get("app_port") or DEFAULT_APP_PORT)


def addresses(name: str, ips: list[str], https: bool, served: set[int]) -> dict[str, str]:
    """Where a phone in the tailnet opens ZettNAS and Immich."""
    host = name or (ips[0] if ips else "")
    if not host:
        return {}
    out = {
        "zettnas": f"https://{name}/" if https and 443 in served else f"http://{host}:{_app_port()}/",
    }
    port = immich_port()
    if port:
        out["immich"] = (
            f"https://{name}:{IMMICH_HTTPS_PORT}/"
            if https and IMMICH_HTTPS_PORT in served
            else f"http://{host}:{port}/"
        )
    return out


def status() -> dict[str, Any]:
    _code, doc = _json(["status", "--json"])
    state = str(doc.get("BackendState") or "")
    if not state:
        state = "Stopped" if tailscale.installed() else "NotInstalled"
    me = doc.get("Self") or {}
    name = str(me.get("DNSName") or "").rstrip(".")
    ips = [str(ip) for ip in me.get("TailscaleIPs") or [] if "." in str(ip)]
    running = state == "Running"
    https = running and bool(name) and bool(doc.get("CertDomains"))
    return {
        "state": state,
        "auth_url": str(doc.get("AuthURL") or "") if state == "NeedsLogin" else "",
        "login_server": tailscale.login_server(),
        "name": name,
        "ips": ips,
        "magic_dns": bool((doc.get("CurrentTailnet") or {}).get("MagicDNSEnabled")),
        "https": https,
        "addresses": addresses(name, ips, https, _served_ports() if running else set()) if running else {},
    }


def connect(login_server: str = "", auth_key: str = "") -> dict[str, Any]:
    """Joins the tailnet: puts Tailscale in a container when it isn't here yet, then signs in.
    Returns the status with the sign-in link to open (or scan) when one is needed."""
    tailscale.set_login_server(login_server)
    key = (auth_key or "").strip() or None
    if tailscale.installed():
        res = tailscale_setup.execute_tailscale_up(auth_key=key)
    else:
        res = tailscale_setup.deploy_tailscale_container(auth_key=key, hostname="zettnas")
    if res.get("status") == "error":
        raise RemoteAccessError(str(res.get("message") or res.get("output") or "Tailscale could not start."))
    now = status()
    if not now["auth_url"] and res.get("auth_url"):
        now["auth_url"] = str(res["auth_url"])
    return now


def publish(app_port: int | None = None) -> dict[str, Any]:
    """HTTPS addresses for ZettNAS (443) and Immich (8443) in the tailnet."""
    if app_port:
        tailscale.update_settings(app_port=int(app_port))
    now = status()
    if now["state"] != "Running":
        raise RemoteAccessError("Connect to Tailscale first.")
    if not now["https"]:
        return {**now, "approval_url": ""}  # the card says how to turn certificates on
    targets = [(443, _app_port())]
    port = immich_port()
    if port:
        targets.append((IMMICH_HTTPS_PORT, port))
    approval = ""
    for public, local in targets:
        code, out = tailscale.run_cli(
            ["serve", "--bg", "--yes", f"--https={public}", f"http://127.0.0.1:{local}"], timeout=10.0
        )
        m = re.search(r"https://login\.tailscale\.com/f/serve\S*", out or "")
        if m:
            approval = m.group(0)
            break
        if code != 0:
            raise RemoteAccessError((out or "tailscale serve failed").strip().splitlines()[-1][:300])
    return {**status(), "approval_url": approval}


def disconnect() -> dict[str, Any]:
    """Stops serving and leaves the tailnet; the node stays signed in for next time."""
    tailscale.run_cli(["serve", "reset"], timeout=5.0)
    tailscale_setup.execute_tailscale_down()
    return status()
