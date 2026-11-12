"""What reaches this NAS from outside, in one answer (SET-24, network report "Status").

Read from the live settings, never from Kiboto's own record alone: Tailscale's state and what Funnel
publishes (tailnet_ports.public_now), NetBird's state, and what Kiboto recorded turning on. The page
says it in one sentence:

    off      Through Kiboto, nothing reaches this NAS from outside.
    private  Only devices in your Tailscale (or NetBird) network.
    public   On the internet: share links, 2 apps…

The tone is neutral; amber when Tailscale needs a sign-in or its key runs out within 14 days; red when
something is public that Kiboto did not turn on (its record says off, the live state says public).
Kiboto cannot see a port opened on the router, a reverse proxy or IPv6, and the page says so.
"""

from __future__ import annotations

from typing import Any

KEY_WARN_DAYS = 14


def _netbird_on() -> bool:
    from backend.services import netbird

    try:
        return netbird.status().get("state") == "Connected"
    except netbird.NetbirdError:
        return False


def _key_days() -> int | None:
    from backend.hardware.net import mesh

    days = (mesh.cached_mesh_vpn_status().get("tailscale") or {}).get("key_expiry_days")
    return days if isinstance(days, int) else None


def judge(
    state: str,
    netbird_on: bool,
    rows: list[dict[str, Any]] | None,
    links_on: bool,
    app_ports: set[int],
    key_days: int | None,
) -> dict[str, Any]:
    """The summary from its facts (pure, so every case is tested)."""
    rows = rows or []
    links = any(r["owner"] == "share_links" for r in rows)
    apps = [r["port"] for r in rows if r["port"] in app_ports]
    unexpected = sorted(
        r["port"] for r in rows if not ((r["owner"] == "share_links" and links_on) or r["port"] in app_ports)
    )
    via = [name for name, on in (("tailscale", state == "Running"), ("netbird", netbird_on)) if on]
    level = "public" if rows else ("private" if via else "off")
    reason = ""
    if unexpected:
        reason = "unexpected_public"
    elif state == "NeedsLogin":
        reason = "sign_in"
    elif state == "Running" and key_days is not None and key_days <= KEY_WARN_DAYS:
        reason = "key_expiring"
    tone = {"unexpected_public": "red", "sign_in": "amber", "key_expiring": "amber"}.get(reason, "neutral")
    return {
        "level": level,
        "tone": tone,
        "reason": reason,
        "via": via,
        "share_links": links,
        "apps": len(apps),
        "unexpected": unexpected,
        "key_days": key_days if state == "Running" else None,
    }


def summary() -> dict[str, Any]:
    from backend.services import public_apps, public_links, remote_access, tailnet_ports

    state = remote_access.status()["state"]
    running = state == "Running"
    rows = tailnet_ports.public_now() if running else []
    out = judge(
        state,
        _netbird_on(),
        rows,
        public_links.recorded_on(),
        public_apps.recorded_ports(),
        _key_days() if running else None,
    )
    out["checked"] = rows is not None  # False: Tailscale runs but could not say what is public
    return out
