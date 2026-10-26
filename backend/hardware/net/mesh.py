"""The mesh VPN overview: Tailscale and WireGuard together.

Part of backend/hardware/network.py, split out by ARC-5."""

from datetime import UTC
from typing import Any

from backend.config import logger
from backend.hardware.net import tailscale, wireguard


def get_mesh_vpn_status() -> dict[str, Any]:
    """
    Zero-Trust Mesh Hub detector:
    Queries Tailscale daemon status (via CLI, Docker container, or local socket) and WireGuard kernel interfaces.
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
        "ssh_enabled": False,
        "serve_enabled": False,
        "funnel_enabled": False,
        "serve_url": "",
        "taildrop_dir": "",
        "taildrop_files_count": 0,
        "taildrop_files": [],
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
            ts_info["taildrop_dir"] = tailscale.get_taildrop_dir()
            ts_info["detected_subnets"] = tailscale.detect_local_subnets()
            return {
                "tailscale": ts_info,
                "wireguard": wireguard._get_wireguard_status(),
            }

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
            ts_info["serve_url"] = f"https://{dns_name}" if dns_name else ""

            # Key Expiry
            key_exp = doc.get("Self", {}).get("KeyExpiry", "")
            ts_info["key_expiry"] = key_exp
            key_days = None
            if key_exp:
                try:
                    from datetime import datetime

                    exp_dt = datetime.fromisoformat(key_exp.replace("Z", "+00:00"))
                    now_dt = datetime.now(UTC)
                    delta = (exp_dt - now_dt).days
                    key_days = max(0, delta)
                except Exception:
                    logger.debug("backend.hardware.network.get_mesh_vpn_status: ignored error", exc_info=True)
            ts_info["key_expiry_days"] = key_days
            ts_info["key_expired"] = (key_days == 0) if key_days is not None else False

            # Check debug prefs for RunSSH and AdvertiseRoutes
            p_routes = []
            p_code, p_out = tailscale._run_tailscale_cmd(["debug", "prefs"], timeout=2.0)
            if p_code == 0 and p_out.strip().startswith("{"):
                try:
                    p_doc = json.loads(p_out.strip())
                    ts_info["ssh_enabled"] = bool(p_doc.get("RunSSH", False))
                    p_routes = p_doc.get("AdvertiseRoutes") or []
                except Exception:
                    logger.debug("backend.hardware.network.get_mesh_vpn_status: ignored error", exc_info=True)

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

            # Check serve / funnel status
            sv_code, sv_out = tailscale._run_tailscale_cmd(["serve", "status", "--json"], timeout=2.0)
            if sv_code == 0 and sv_out.strip().startswith("{") and len(sv_out.strip()) > 2:
                ts_info["serve_enabled"] = True
                fn_code, fn_out = tailscale._run_tailscale_cmd(["funnel", "status", "--json"], timeout=2.0)
                if fn_code == 0 and "AllowFunnel" in fn_out:
                    ts_info["funnel_enabled"] = True

            # Taildrop inbox files
            ts_info["taildrop_dir"] = tailscale.get_taildrop_dir()
            taildrop_files = tailscale.get_taildrop_inbox_files()
            ts_info["taildrop_files_count"] = len(taildrop_files)
            ts_info["taildrop_files"] = taildrop_files
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

    return {
        "tailscale": ts_info,
        "wireguard": wireguard._get_wireguard_status(),
    }
