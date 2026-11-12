"""Use Kiboto from anywhere (COMP-01), without opening a port on the router.

Tailscale (a free account) or a Headscale server of your own puts this NAS and your phone in
one private network. Then `tailscale serve` gives Kiboto, and Immich when it is installed,
HTTPS addresses under the node's MagicDNS name, which the phone opens like any website:

    https://<name>.<tailnet>.ts.net/          Kiboto
    https://<name>.<tailnet>.ts.net:8443/     Immich
    https://<name>.<tailnet>.ts.net:18096/    any other app with a web page, here on port 8096 (NFEAT-5)

Without HTTPS certificates (turned off in the tailnet, or a Headscale server) the addresses
are plain http on the tailnet name or address; the traffic is still encrypted by WireGuard.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from backend.hardware.net import tailscale, tailscale_setup
from backend.services import tailnet_ports

IMMICH_HTTPS_PORT = tailnet_ports.IMMICH_BEFORE_MOVE
DEFAULT_APP_PORT = 8082
APP_HTTPS_OFFSET = tailnet_ports.APP_OFFSET


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


def immich_https_port() -> int:
    """The port of Immich's HTTPS address in the tailnet: 8443, or its own port once it was moved
    out of the share links' way (SET-02)."""
    return int(tailscale.settings().get("immich_https_port") or IMMICH_HTTPS_PORT)


def move_immich() -> int | None:
    """Moves Immich's HTTPS address off the share links' port to a port of its own (its host port
    plus 10000, like every other app). The port it leaves is free for the share links; phones and
    browsers need the new address. Returns the new port, or None when Immich isn't here."""
    port = immich_port()
    if not port:
        return None
    new = port + APP_HTTPS_OFFSET
    tailscale.run_cli(["serve", f"--https={IMMICH_HTTPS_PORT}", "off"], timeout=10.0)
    tailscale.update_settings(immich_https_port=new)
    code, out = tailscale.run_cli(
        ["serve", "--bg", "--yes", f"--https={new}", f"http://127.0.0.1:{port}"], timeout=10.0
    )
    if code != 0:
        raise RemoteAccessError((out or "tailscale serve failed").strip().splitlines()[-1][:300])
    return new


def _app_port() -> int:
    return int(tailscale.settings().get("app_port") or DEFAULT_APP_PORT)


def web_apps() -> list[dict[str, Any]]:
    """The other running apps with a plain-http web page on a host port, as {name, port}.

    Kiboto itself and Immich have their own HTTPS ports; an app that already speaks https,
    or whose port would land past 65535 once moved up, is left out.
    """
    from backend.hardware.docker_stats import read_docker_containers

    try:
        containers = read_docker_containers()
    except (OSError, ValueError, RuntimeError):
        return []
    skip = {_app_port(), immich_port()}
    found: dict[int, str] = {}
    for c in containers:
        port = c.get("primary_port")
        if c.get("state") != "running" or not str(c.get("webui_url") or "").startswith("http://"):
            continue
        if isinstance(port, int) and port not in skip and port + APP_HTTPS_OFFSET <= 65535:
            found.setdefault(port, str(c.get("name") or port))
    return [{"name": name, "port": port} for port, name in sorted(found.items())]


def _app_addresses(name: str, host: str, https: bool, served: set[int]) -> list[dict[str, str]]:
    out = []
    for app in web_apps():
        public = app["port"] + APP_HTTPS_OFFSET
        url = f"https://{name}:{public}/" if https and public in served else f"http://{host}:{app['port']}/"
        out.append({"name": app["name"], "url": url})
    return out


def addresses(name: str, ips: list[str], https: bool, served: set[int]) -> dict[str, Any]:
    """Where a phone in the tailnet opens Kiboto, Immich and the other apps."""
    host = name or (ips[0] if ips else "")
    if not host:
        return {}
    out: dict[str, Any] = {
        "kiboto": f"https://{name}/" if https and 443 in served else f"http://{host}:{_app_port()}/",
        "zettnas": f"https://{name}/" if https and 443 in served else f"http://{host}:{_app_port()}/",  # until 2.2
    }
    port = immich_port()
    if port:
        secure = immich_https_port()
        out["immich"] = f"https://{name}:{secure}/" if https and secure in served else f"http://{host}:{port}/"
    apps = _app_addresses(name, host, https, served)
    if apps:
        out["apps"] = apps
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
        res = tailscale_setup.deploy_tailscale_container(auth_key=key, hostname="kiboto")
    if res.get("status") == "error":
        raise RemoteAccessError(str(res.get("message") or res.get("output") or "Tailscale could not start."))
    now = status()
    if not now["auth_url"] and res.get("auth_url"):
        now["auth_url"] = str(res["auth_url"])
    return now


def publish(app_port: int | None = None) -> dict[str, Any]:
    """HTTPS addresses in the tailnet for Kiboto (443), Immich (8443) and every other app
    with a web page (its port + 10000); an app's address goes when the app does."""
    if app_port and _is_local_port(int(app_port)):
        tailscale.update_settings(app_port=int(app_port))
    now = status()
    if now["state"] != "Running":
        raise RemoteAccessError("Connect to Tailscale first.")
    if not now["https"]:
        return {**now, "approval_url": ""}  # the card says how to turn certificates on
    targets = [(443, _app_port())]
    port = immich_port()
    if port:
        targets.append((immich_https_port(), port))
    targets += [(app["port"] + APP_HTTPS_OFFSET, app["port"]) for app in web_apps()]
    _drop_gone_apps({public for public, _local in targets})
    approval = ""
    on_internet = _public_ports()
    for public, local in targets:
        if public in on_internet:
            # Funnel publishes this port (share links, or an app): serving this here as well would
            # put it on the internet with them, or take the port off the internet (SET-02)
            continue
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


def _is_local_port(port: int) -> bool:
    """Whether a port named by the page can be the one Kiboto is reached on at home. 443 is the
    port of the HTTPS address itself: from that page it used to be saved as Kiboto's port, and the
    address away from home then pointed at the wrong local port (SET-02)."""
    from backend import settings

    return port != 443 or int(settings.current("port") or DEFAULT_APP_PORT) == 443


def _public_ports() -> set[int]:
    """The ports Funnel publishes to the internet right now."""
    _code, doc = _json(["funnel", "status", "--json"])
    return {row["port"] for row in tailnet_ports.published(doc)}


def _drop_gone_apps(wanted: set[int]) -> None:
    """Stops serving the HTTPS ports of apps that are no longer here."""
    for public in _served_ports():
        if public > APP_HTTPS_OFFSET and public not in wanted:
            tailscale.run_cli(["serve", f"--https={public}", "off"], timeout=10.0)


def disconnect() -> dict[str, Any]:
    """Leaves the tailnet; the node stays signed in, and its HTTPS addresses stay set up for next
    time (SET-16: Disconnect no longer wipes them; nothing is reachable while it is down)."""
    tailscale_setup.execute_tailscale_down()
    return status()
