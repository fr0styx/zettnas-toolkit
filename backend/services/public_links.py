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
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

FUNNEL_PORT = 8443
PATH = "/api/fs/shared"
STATE_FILE = os.path.join(DATA_DIR, "public_links.json")
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


def live(dns: str) -> bool:
    """Whether Funnel serves the share links on FUNNEL_PORT right now."""
    code, out = _ts(["funnel", "status", "--json"], timeout=4.0)
    if code != 0 or not dns:
        return False
    try:
        doc = json.loads(out) or {}
    except ValueError:
        return False
    if not isinstance(doc, dict):
        return False
    host = f"{dns}:{FUNNEL_PORT}"
    handlers = ((doc.get("Web") or {}).get(host) or {}).get("Handlers") or {}
    return bool((doc.get("AllowFunnel") or {}).get(host)) and any(p.rstrip("/") == PATH for p in handlers)


def status() -> dict[str, Any]:
    st = _state()
    dns = _dns_name()
    on = bool(st.get("enabled"))
    return {
        "enabled": on,
        "live": live(dns) if on else False,
        "tailscale": bool(dns),
        "base_url": f"https://{dns}:{FUNNEL_PORT}" if dns else "",
        "approval_url": st.get("approval_url") or "",
        "error": st.get("error") or "",
    }


def enable(web_port: int) -> dict[str, Any]:
    """Publishes the share links' path; Tailscale may first want Funnel allowed (approval link)."""
    dns = _dns_name()
    if not dns:
        atomic_write_json(STATE_FILE, {"enabled": False, "error": "Tailscale isn't connected on this NAS."})
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
    _ts(["funnel", f"--https={FUNNEL_PORT}", f"--set-path={PATH}", "off"])
    atomic_write_json(STATE_FILE, {"enabled": False})
    return status()


def public_url(token: str) -> str:
    """The link's address from anywhere, when public links are on; "" otherwise."""
    st = _state()
    base = st.get("base_url") if st.get("enabled") and not st.get("approval_url") else ""
    return f"{base}{PATH}/{token}" if base else ""
