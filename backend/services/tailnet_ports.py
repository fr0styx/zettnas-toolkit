"""Which feature owns which HTTPS port on the NAS's Tailscale name, and what Funnel puts on the
internet right now (SET-16 stage 3, network report B and A1).

`tailscale serve` (the tailnet only) and `tailscale funnel` (the internet) share one setting per
port, and Funnel opens a whole port, never one path: whatever else is served on a published port is
public too. So each port has one owner, and this table is the only place that says which:

    443        Kiboto in the tailnet (remote access); a public app only when Kiboto isn't there
    8443       share links on the internet (Funnel); Immich in the tailnet until share links move it
    10000      one chosen app on the internet
    p + 10000  each app with a web page on host port p, in the tailnet (Immich too, once moved)

Funnel allows only 443, 8443 and 10000.
"""

from __future__ import annotations

import json
from typing import Any

KIBOTO = 443
SHARE_LINKS = 8443
IMMICH_BEFORE_MOVE = 8443  # the share links move Immich off it (SET-02, decision D6)
PUBLIC_APP = 10000
APP_OFFSET = 10000  # an app on host port 8096 is served at https://<name>:18096/
FUNNEL_ALLOWS = (KIBOTO, SHARE_LINKS, PUBLIC_APP)
PUBLIC_APP_PORTS = (PUBLIC_APP, KIBOTO)  # 443 only when remote access doesn't serve Kiboto there
SHARE_PATH = "/api/fs/shared"


def owner(port: int) -> str:
    """kiboto, share_links, public_app, app (an app in the tailnet) or other."""
    named = {KIBOTO: "kiboto", SHARE_LINKS: "share_links", PUBLIC_APP: "public_app"}
    if port in named:
        return named[port]
    return "app" if port > APP_OFFSET else "other"


def parse_funnel_status(out: str) -> dict[str, Any] | None:
    """`tailscale funnel status --json` as a dict, or None when it can't be read."""
    try:
        doc = json.loads(out) or {}
    except (ValueError, TypeError):
        return None
    return doc if isinstance(doc, dict) else None


def published(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per port Funnel publishes: its owner, the paths served there and where they lead."""
    rows = []
    for host, on in (doc.get("AllowFunnel") or {}).items():
        port = str(host).rsplit(":", 1)[-1]
        if not on or not port.isdigit():
            continue
        handlers = ((doc.get("Web") or {}).get(host) or {}).get("Handlers") or {}
        targets = {str((h or {}).get("Proxy") or "") for h in handlers.values()} - {""}
        rows.append(
            {"port": int(port), "owner": owner(int(port)), "paths": sorted(handlers), "targets": sorted(targets)}
        )
    return sorted(rows, key=lambda r: r["port"])


def public_now() -> list[dict[str, Any]] | None:
    """What is on the internet through Funnel right now, from one read of Tailscale's settings; None
    when Tailscale can't be asked (not the same as nothing public)."""
    from backend.hardware.net import tailscale

    code, out = tailscale.run_tailscale_cmd(["funnel", "status", "--json"], timeout=4.0)
    doc = parse_funnel_status(out) if code == 0 else None
    return None if doc is None else published(doc)
