"""The mesh VPN overview: Tailscale (WireGuard was removed, decision D3).

Part of backend/hardware/network.py, split out by ARC-5."""

import copy
import threading
import time
from datetime import UTC
from typing import Any

from backend.config import logger
from backend.hardware.net import tailscale
from backend.ignored_errors import ignored


def _key_days_left(key_exp: str) -> int | None:
    """Whole days until the node key expires (0 once it has), or None when unknown."""
    if not key_exp:
        return None
    try:
        from datetime import datetime

        exp_dt = datetime.fromisoformat(key_exp.replace("Z", "+00:00"))
        return max(0, (exp_dt - datetime.now(UTC)).days)
    except (ValueError, TypeError):
        return None


def get_mesh_vpn_status() -> dict[str, Any]:
    """
    Zero-Trust Mesh Hub detector:
    Queries Tailscale daemon status (via CLI, Docker container, or local socket).
    """
    import json

    ts_info = {
        "installed": False,
        "active": False,
        "backend_state": "Stopped",
        "ipv4": "",
        "tailnet": "",
        "hostname": "",
        "dns_name": "",
        "peers_count": 0,
        "peers": [],
        "auth_url": "",
        "container_mode": False,
        "container_id": "",
        "key_expiry": "",
        "key_expiry_days": None,
        "key_expired": False,
        "detected_subnets": [],
        "advertised_routes": [],
        "is_subnet_router": False,
        "advertise_exit_node": False,
        "exit_node_approved": False,
        "is_exit_node": False,
        "admin_console_url": "https://login.tailscale.com/admin/machines",
    }

    ts_bin = tailscale._find_tailscale_bin()
    c_info = tailscale._get_tailscale_container_info()
    if c_info.get("exists"):
        ts_info["container_mode"] = True
        ts_info["container_id"] = c_info.get("id", "")
        ts_info["installed"] = True
        if not c_info.get("running"):
            ts_info["active"] = False
            ts_info["backend_state"] = "Stopped"
            ts_info["detected_subnets"] = tailscale.detect_local_subnets()
            return {"tailscale": ts_info}

    code, out = tailscale._run_tailscale_cmd(["status", "--json"], timeout=4.0)
    out_stripped = out.strip()
    if code == 0 and out_stripped.startswith("{"):
        try:
            doc = json.loads(out_stripped)
            ts_info["installed"] = True
            status_str = doc.get("BackendState", "")
            ts_info["backend_state"] = status_str
            ts_info["active"] = status_str == "Running"
            ts_info["hostname"] = doc.get("Self", {}).get("HostName", "")
            ips = doc.get("Self", {}).get("TailscaleIPs", [])
            ts_info["ipv4"] = ips[0] if ips else ""
            ts_info["tailnet"] = doc.get("MagicDNSSuffix", "")
            dns_name = doc.get("Self", {}).get("DNSName", "").rstrip(".")
            ts_info["dns_name"] = dns_name

            # Key Expiry
            key_exp = doc.get("Self", {}).get("KeyExpiry", "")
            ts_info["key_expiry"] = key_exp
            ts_info["key_expiry_days"] = key_days = _key_days_left(key_exp)
            ts_info["key_expired"] = (key_days == 0) if key_days is not None else False

            # Check debug prefs for accepted and advertised routes
            p_routes = []
            p_code, p_out = tailscale._run_tailscale_cmd(["debug", "prefs"], timeout=2.0)
            if p_code == 0 and p_out.strip().startswith("{"):
                try:
                    p_doc = json.loads(p_out.strip())
                    ts_info["accept_routes"] = bool(p_doc.get("RouteAll", False))
                    p_routes = p_doc.get("AdvertiseRoutes") or []
                except Exception:
                    ignored("backend.hardware.network.get_mesh_vpn_status")

            # Exit Node Gateway options
            has_exit_route = any(r in ("0.0.0.0/0", "::/0") for r in p_routes)
            exit_node_approved = bool(doc.get("Self", {}).get("ExitNodeOption", False))
            ts_info["advertise_exit_node"] = has_exit_route or exit_node_approved
            ts_info["exit_node_approved"] = exit_node_approved
            ts_info["is_exit_node"] = bool(doc.get("Self", {}).get("ExitNode", False))

            # Subnet Router options (LAN routes only, excluding 0.0.0.0/0, ::/0, and tailscale overlay IPs)
            candidate_routes = p_routes if p_routes else doc.get("Self", {}).get("AllowedIPs", [])
            lan_routes = [
                r
                for r in candidate_routes
                if r not in ("0.0.0.0/0", "::/0") and not r.startswith("100.") and not r.startswith("fd7a:")
            ]
            ts_info["advertised_routes"] = lan_routes
            ts_info["is_subnet_router"] = len(lan_routes) > 0
            ts_info["detected_subnets"] = tailscale.detect_local_subnets()
            # routes over the NAS's own network; the scheduler turns accepting them off (guard_routes_now)
            ts_info["route_conflicts"] = tailscale.lan_route_conflicts(doc)

            # Parse Peers
            peers_dict = doc.get("Peer", {})
            peers_list = []
            if isinstance(peers_dict, dict):
                for p_key, p_val in peers_dict.items():
                    p_ips = p_val.get("TailscaleIPs", [])
                    p_ip = p_ips[0] if p_ips else ""
                    cur_addr = p_val.get("CurAddr", "")
                    relay = p_val.get("Relay", "")
                    conn_type = "Direct P2P" if cur_addr else (f"DERP ({relay})" if relay else "Offline")
                    peers_list.append(
                        {
                            "id": p_key,
                            "name": p_val.get("HostName", "Unknown"),
                            "hostname": p_val.get("HostName", "Unknown"),
                            "dns_name": p_val.get("DNSName", "").rstrip("."),
                            "os": p_val.get("OS", "unknown"),
                            "ip": p_ip,
                            "online": p_val.get("Online", False),
                            "relay": relay,
                            "cur_addr": cur_addr,
                            "connection_type": conn_type,
                            "exit_node_option": p_val.get("ExitNodeOption", False),
                            "last_seen": p_val.get("LastSeen", ""),
                        }
                    )
            peers_list.sort(key=lambda x: (not x["online"], x["name"].lower()))
            ts_info["peers"] = peers_list
            ts_info["peers_count"] = len(peers_list)
            ts_info["auth_url"] = doc.get("AuthURL") or ""

        except Exception as e:
            logger.debug(f"[Network] Tailscale status json parse error: {e}")
    elif c_info.get("running") or ts_bin and "failed to connect to local tailscaled" not in out.lower():
        ts_info["installed"] = True
        out_lower = out.lower()
        if "logged out" in out_lower or "needslogin" in out_lower:
            ts_info["backend_state"] = "NeedsLogin"
        else:
            ts_info["backend_state"] = "Stopped"
    elif c_info.get("exists"):
        ts_info["installed"] = True
        ts_info["backend_state"] = "Stopped"
    else:
        ts_info["installed"] = False

    return {"tailscale": ts_info}


CACHE_S = 5.0  # the page asks twice when it opens and again on every Refresh (network report C1)
_cache: dict[str, Any] = {"at": 0.0, "changes": -1, "doc": None}
_cache_lock = threading.Lock()


def cached_mesh_vpn_status() -> dict[str, Any]:
    """get_mesh_vpn_status at most once every few seconds, read again at once after anything that
    may have changed Tailscale (tailscale.changed). Each caller gets its own copy."""
    now = time.monotonic()
    with _cache_lock:
        fresh = _cache["changes"] == tailscale.changes() and now - _cache["at"] < CACHE_S
        if fresh and _cache["doc"] is not None:
            return copy.deepcopy(_cache["doc"])
        seen = tailscale.changes()
    doc = get_mesh_vpn_status()
    with _cache_lock:
        _cache.update(at=time.monotonic(), changes=seen, doc=doc)
    return copy.deepcopy(doc)


def forget_cached_status() -> None:
    with _cache_lock:
        _cache.update(at=0.0, changes=-1, doc=None)
