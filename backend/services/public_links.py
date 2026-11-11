"""Share links that work from anywhere, through Tailscale Funnel (NFEAT-2, D13).

Funnel publishes one path of the NAS to the internet on its own port, FUNNEL_PORT (one of the three
Funnel allows), with Tailscale's HTTPS certificate: only /api/fs/shared, where share links live
(the downloads, their password page and the "send me files" page). Nothing else of Kiboto is
reachable that way; the web interface stays on the home network and the tailnet. No router change
is needed and it works behind the internet provider's shared address (CGNAT).

The address has the NAS's Tailscale name in it (https://<name>.<tailnet>.ts.net:8443/...): pick a
name of the family's own for the device, not the product's, so a rebrand doesn't break links
already sent. Funnel traffic goes through Tailscale's relays, so big downloads are slower than at
home. Turning it on is confirmed in the app, and the first time Tailscale may ask the tailnet's
owner to allow Funnel (the approval link is shown).
"""

import json
import os
import re
import time
from typing import Any
from urllib.parse import quote

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

FUNNEL_PORT = 8443
PATH = "/api/fs/shared"
STATE_FILE = os.path.join(DATA_DIR, "public_links.json")
DNS_URL = "https://login.tailscale.com/admin/dns"  # where the owner turns on HTTPS certificates
PENDING_SECONDS = 3600  # a request made before Funnel was allowed is finished within this time
_NODE_ID = re.compile(r"^[A-Za-z0-9]{6,40}$")
_PORTS_CAP = "https://tailscale.com/cap/funnel-ports"
_APPROVAL = re.compile(r"https://login\.tailscale\.com/f/funnel\S*")


def _ts(args: list[str], timeout: float = 8.0) -> tuple[int, str]:
    from backend.hardware.net import tailscale

    return tailscale.run_tailscale_cmd(args, timeout=timeout)


def _state() -> dict[str, Any]:
    data = read_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def _dns_name() -> str:
    code, out = _ts(["status", "--json"], timeout=4.0)
    if code != 0:
        return ""
    try:
        return str(((json.loads(out) or {}).get("Self") or {}).get("DNSName") or "").rstrip(".")
    except ValueError:
        return ""


def _status_doc() -> dict[str, Any]:
    code, out = _ts(["status", "--json"], timeout=4.0)
    if code != 0:
        return {}
    try:
        doc = json.loads(out) or {}
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def funnel_readiness(doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """What Funnel needs that only the tailnet's owner can switch on, read from Tailscale's own status:
    HTTPS certificates for the tailnet (CertDomains) and Funnel allowed for this device (its funnel
    capability, with the ports it may use). Links to both steps; the approval link is built from the
    device's id, so no command has to wait for it."""
    from backend.hardware.net import tailscale

    doc = _status_doc() if doc is None else doc
    me = doc.get("Self") or {}
    caps = me.get("CapMap") or {}
    ports: list[int] = []
    for key in caps:
        if key.startswith(_PORTS_CAP):
            m = re.search(r"ports=([\d,]+)", key)
            ports = sorted({int(p) for p in (m.group(1) if m else "").split(",") if p.isdigit()})
    node = str(me.get("ID") or "")
    connected = bool(me.get("DNSName"))
    headscale = bool(tailscale.login_server())
    https = bool(doc.get("CertDomains"))
    allowed = "funnel" in caps or any(k.startswith(_PORTS_CAP) for k in caps)
    return {
        "connected": connected,
        "headscale": headscale,
        "https": https,
        "funnel": allowed,
        "ports": ports,
        "dns_url": DNS_URL,
        "approve_url": f"https://login.tailscale.com/f/funnel?node={quote(node)}" if _NODE_ID.match(node) else "",
        "ready": connected and https and allowed and not headscale,
    }


OTHERS_ON_PORT = (
    f"Tailscale already serves something else on port {FUNNEL_PORT} of this NAS (Immich, for example). "
    "Turning share links on would put that on the internet too. Move it to another port first."
)
NOT_OFF = "Tailscale did not confirm that the share links are off the internet. Try again."


def _port_state(dns: str) -> tuple[dict[str, Any], bool, bool]:
    """What Tailscale serves on the share links' port, by path; whether Funnel publishes the port;
    and whether the answer could be read at all. Funnel opens a whole port, never one path
    (SET-02): everything served on a published port is on the internet."""
    code, out = _ts(["funnel", "status", "--json"], timeout=4.0)
    if code != 0 or not dns:
        return {}, False, False
    try:
        doc = json.loads(out) or {}
    except ValueError:
        return {}, False, False
    if not isinstance(doc, dict):
        return {}, False, False
    host = f"{dns}:{FUNNEL_PORT}"
    handlers = ((doc.get("Web") or {}).get(host) or {}).get("Handlers") or {}
    return handlers, bool((doc.get("AllowFunnel") or {}).get(host)), True


def own_page_ports(dns: str) -> list[int]:
    """The ports on which Kiboto's own page is on the internet. No card publishes it; an older
    switch did (SET-02), and a live setting is shown so it can be taken off."""
    from urllib.parse import urlsplit

    from backend.services import public_apps

    code, out = _ts(["funnel", "status", "--json"], timeout=4.0)
    if code != 0 or not dns:
        return []
    try:
        doc = json.loads(out) or {}
    except ValueError:
        return []
    if not isinstance(doc, dict):
        return []
    own = public_apps._own_port()
    ports = []
    for host, on in (doc.get("AllowFunnel") or {}).items():
        port = str(host).rsplit(":", 1)[-1]
        if not on or not port.isdigit():
            continue
        for path, handler in (((doc.get("Web") or {}).get(host) or {}).get("Handlers") or {}).items():
            target = urlsplit(str((handler or {}).get("Proxy") or ""))
            whole_page = target.path.rstrip("/") == "" and path.rstrip("/") != PATH
            if whole_page and target.port == own and target.hostname in ("127.0.0.1", "localhost"):
                ports.append(int(port))
    return sorted(set(ports))


def immich_to_move(dns: str | None = None) -> str:
    """Immich's new address, when its HTTPS address is the only other thing on the share links'
    port and so stands in their way; "" when nothing has to move (SET-02, the owner's decision S7:
    Immich moves only when someone turns share links on, after a question that shows this address)."""
    from urllib.parse import urlsplit

    from backend.services import remote_access

    dns = _dns_name() if dns is None else dns
    handlers, _public, _read = _port_state(dns)
    others = _others(handlers)
    port = remote_access.immich_port()
    if not others or not port:
        return ""
    for path in others:
        target = urlsplit(str((handlers[path] or {}).get("Proxy") or ""))
        if target.port != port or target.hostname not in ("127.0.0.1", "localhost"):
            return ""  # something else is there too: that is not Kiboto's to move
    return f"https://{dns}:{port + remote_access.APP_HTTPS_OFFSET}/"


def _links_served(handlers: dict[str, Any]) -> bool:
    return any(p.rstrip("/") == PATH for p in handlers)


def _others(handlers: dict[str, Any]) -> list[str]:
    """The paths on the port that are not the share links'."""
    return sorted(p for p in handlers if p.rstrip("/") != PATH)


def live(dns: str) -> bool:
    """Whether Funnel serves the share links on FUNNEL_PORT right now."""
    handlers, public, _read = _port_state(dns)
    return public and _links_served(handlers)


def status(finish_pending: bool = False) -> dict[str, Any]:
    """`finish_pending`: a request that waited for the tailnet owner's steps is carried out now.
    Only for someone who may change settings: reading the card must never publish anything."""
    st = _state()
    ready = funnel_readiness()
    pending = st.get("pending") or {}
    waiting = bool(pending) and time.time() - float(pending.get("since") or 0) < PENDING_SECONDS
    if finish_pending and waiting and ready["ready"]:
        logger.info("[PublicLinks] Funnel is allowed now: finishing the waiting request")
        return enable(int(pending.get("web_port") or 8082), bool(pending.get("move_immich")))
    dns = _dns_name()
    on = bool(st.get("enabled"))
    handlers, public, _read = _port_state(dns)
    return {
        "funnel": ready,
        "pending": waiting,
        "enabled": on,
        "live": on and public and _links_served(handlers),
        # the port is on the internet, and what else it carries there besides the share links
        "port_public": public,
        "also_public": _others(handlers) if public else [],
        "own_page_public": own_page_ports(dns),
        "tailscale": bool(dns),
        "base_url": f"https://{dns}:{FUNNEL_PORT}" if dns else "",
        "approval_url": st.get("approval_url") or "",
        "error": st.get("error") or "",
    }


def enable(web_port: int, move_immich: bool = False) -> dict[str, Any]:
    """Publishes the share links' path; Tailscale may first want Funnel allowed (approval link).
    `move_immich`: the person agreed that Immich's HTTPS address leaves this port first."""
    dns = _dns_name()
    if not dns:
        atomic_write_json(STATE_FILE, {"enabled": False, "error": "Tailscale isn't connected on this NAS."})
        return status()
    if not funnel_readiness()["ready"]:
        # the owner's steps aren't done: remember the request; status() finishes it once they are
        waiting = {"web_port": web_port, "since": time.time(), "move_immich": bool(move_immich)}
        atomic_write_json(STATE_FILE, {"enabled": False, "pending": waiting})
        return status()
    handlers, _public, _read = _port_state(dns)
    if move_immich and immich_to_move(dns):
        from backend.services import remote_access

        try:
            remote_access.move_immich()
        except remote_access.RemoteAccessError as e:
            atomic_write_json(STATE_FILE, {"enabled": False, "error": f"Immich could not be moved: {e}"})
            return status()
        handlers, _public, _read = _port_state(dns)
    if _others(handlers):
        atomic_write_json(STATE_FILE, {"enabled": False, "error": OTHERS_ON_PORT})
        logger.warning("[PublicLinks] not published: port %s also serves %s", FUNNEL_PORT, _others(handlers))
        return status()
    target = f"http://127.0.0.1:{web_port}{PATH}"
    code, out = _ts(["funnel", "--bg", "--yes", f"--https={FUNNEL_PORT}", f"--set-path={PATH}", target])
    approval = _APPROVAL.search(out or "")
    error = "" if code == 0 or approval else (out or "").strip()[:300]
    atomic_write_json(
        STATE_FILE,
        {
            "enabled": not error,
            "base_url": f"https://{dns}:{FUNNEL_PORT}",
            "approval_url": approval.group(0) if approval else "",
            "error": error,
        },
    )
    logger.info("[PublicLinks] Funnel on %s:%s for %s: %s", dns, FUNNEL_PORT, PATH, error or "ok")
    return status()


def disable() -> dict[str, Any]:
    """Takes the share links off the internet, and says "off" only once Tailscale shows it."""
    dns = _dns_name()
    _ts(["funnel", f"--https={FUNNEL_PORT}", f"--set-path={PATH}", "off"])
    handlers, public, read = _port_state(dns)
    if dns and (not read or (public and _links_served(handlers))):
        atomic_write_json(STATE_FILE, {**_state(), "enabled": True, "error": NOT_OFF})
        logger.warning("[PublicLinks] turning off was not confirmed by Tailscale")
    else:
        atomic_write_json(STATE_FILE, {"enabled": False})
    return status()


def close_port(actor: str = "", port: int = FUNNEL_PORT) -> dict[str, Any]:
    """Takes a whole port off the internet (SET-02): the share links' port with whatever else it
    carried there, or a port that publishes Kiboto's own page. Nothing else can be named. What was
    served for the tailnet only can be turned on again afterwards."""
    dns = _dns_name()
    if port != FUNNEL_PORT and port not in own_page_ports(dns):
        raise ValueError(f"Port {port} is not one Kiboto can take off the internet here.")
    _ts(["funnel", f"--https={port}", "off"], timeout=15.0)
    if port == FUNNEL_PORT:
        _handlers, public, read = _port_state(dns)
        if dns and (not read or public):
            atomic_write_json(STATE_FILE, {**_state(), "error": NOT_OFF})
        else:
            atomic_write_json(STATE_FILE, {"enabled": False})
    try:
        from backend.users_db import log_security_event

        log_security_event("public_links.close_port", "success", actor_username=actor or None, details={"port": port})
    except (ImportError, OSError, ValueError):
        logger.debug("[PublicLinks] could not write the security log", exc_info=True)
    return status()


def tailscale_status() -> dict[str, Any]:
    """`tailscale status --json` as a dict ({} when Tailscale doesn't answer)."""
    return _status_doc()


def base_url() -> str:
    """https://<name>:8443 while public share links work from anywhere; "" otherwise."""
    st = _state()
    return str(st.get("base_url") or "") if st.get("enabled") and not st.get("approval_url") else ""


def public_url(token: str) -> str:
    """The link's address from anywhere, when public links are on; "" otherwise."""
    st = _state()
    base = st.get("base_url") if st.get("enabled") and not st.get("approval_url") else ""
    return f"{base}{PATH}/{token}" if base else ""
