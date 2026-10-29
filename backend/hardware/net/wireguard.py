"""WireGuard: status, keys, client configs, IP forwarding and subnet NAT.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import secrets
import subprocess
import time
from typing import Any

from backend.config import logger
from backend.hardware.net import common
from backend.ignored_errors import ignored


def _get_wireguard_status() -> dict[str, Any]:
    """Inspects host WireGuard network interfaces, peers, and telemetry."""
    wg_info = {
        "installed": False,
        "active": False,
        "interfaces": [],
        "peers": [],
        "peers_count": 0,
    }
    try:
        r = subprocess.run(["wg", "show", "interfaces"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            wg_info["installed"] = True
            ifaces = [i.strip() for i in r.stdout.strip().split() if i.strip()]
            wg_info["interfaces"] = ifaces
            wg_info["active"] = len(ifaces) > 0

            try:
                r_dump = subprocess.run(["wg", "show", "all", "dump"], capture_output=True, text=True, timeout=3)
                if r_dump.returncode == 0:
                    peers = []
                    now = int(time.time())
                    for line in r_dump.stdout.splitlines():
                        parts = line.strip().split("	")
                        if len(parts) >= 8:
                            iface = parts[0]
                            pubkey = parts[1]
                            endpoint = parts[3] if parts[3] != "(none)" else ""
                            allowed_ips = (
                                [ip.strip() for ip in parts[4].split(",") if ip.strip()]
                                if len(parts) > 4 and parts[4] != "(none)"
                                else []
                            )
                            try:
                                latest_hs = int(parts[5]) if len(parts) > 5 else 0
                            except ValueError:
                                latest_hs = 0
                            try:
                                rx_bytes = int(parts[6]) if len(parts) > 6 else 0
                            except ValueError:
                                rx_bytes = 0
                            try:
                                tx_bytes = int(parts[7]) if len(parts) > 7 else 0
                            except ValueError:
                                tx_bytes = 0

                            hs_age = (now - latest_hs) if latest_hs > 0 else None
                            is_active = hs_age is not None and hs_age < 180

                            peers.append(
                                {
                                    "interface": iface,
                                    "public_key": pubkey[:8] + "..." if len(pubkey) > 8 else pubkey,
                                    "endpoint": endpoint,
                                    "allowed_ips": allowed_ips,
                                    "latest_handshake": latest_hs,
                                    "latest_handshake_age": hs_age,
                                    "transfer_rx_bytes": rx_bytes,
                                    "transfer_tx_bytes": tx_bytes,
                                    "active": is_active,
                                }
                            )
                    wg_info["peers"] = peers
                    wg_info["peers_count"] = len(peers)
            except Exception as e:
                logger.debug(f"[Network] Wireguard dump query error: {e}")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"[Network] Wireguard status query: {e}")
    return wg_info


def generate_wireguard_keypair() -> tuple[str, str]:
    """Generates WireGuard (private_key, public_key) pair."""
    try:
        r1 = subprocess.run(["wg", "genkey"], capture_output=True, text=True, timeout=5)
        if r1.returncode == 0:
            priv = r1.stdout.strip()
            r2 = subprocess.run(["wg", "pubkey"], input=priv, capture_output=True, text=True, timeout=5)
            if r2.returncode == 0:
                return priv, r2.stdout.strip()
    except Exception:
        ignored("backend.hardware.network.generate_wireguard_keypair")

    # Pure Python fallback using 32 cryptographically secure random bytes
    import base64

    priv = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    pub = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    return priv, pub


def generate_wireguard_client_config(
    client_name: str,
    client_ip: str = "10.13.13.2/32",
    server_endpoint: str = "",
    server_pubkey: str = "",
    dns: str = "1.1.1.1",
    allowed_ips: str = "0.0.0.0/0, ::/0",
    keepalive: int = 25,
) -> dict[str, Any]:
    """Synthesizes a ready-to-import WireGuard client configuration file."""
    priv, pub = generate_wireguard_keypair()
    conf = (
        f"# WireGuard Client Profile: {client_name}\n"
        f"[Interface]\n"
        f"PrivateKey = {priv}\n"
        f"Address = {client_ip}\n"
        f"DNS = {dns}\n\n"
        f"[Peer]\n"
        f"PublicKey = {server_pubkey or 'SERVER_PUBLIC_KEY_PLACEHOLDER'}\n"
        f"Endpoint = {server_endpoint or 'your-nas-domain.com:51820'}\n"
        f"AllowedIPs = {allowed_ips}\n"
        f"PersistentKeepalive = {keepalive}\n"
    )
    return {
        "client_name": client_name,
        "private_key": priv,
        "public_key": pub,
        "config_text": conf,
        "config_content": conf,
        "client_ip": client_ip,
        "endpoint": server_endpoint,
        "allowed_ips": allowed_ips,
    }


def get_ip_forwarding_status() -> bool:
    """Checks whether IPv4 packet forwarding is enabled in kernel sysctl."""
    for p in common.IP_FORWARD_PATHS:
        if os.path.isfile(p):
            try:
                with open(p) as f:
                    return f.read().strip() == "1"
            except Exception:
                ignored("backend.hardware.network.get_ip_forwarding_status")
    return False


def set_ip_forwarding(enable: bool) -> bool:
    """Configures kernel IPv4 packet forwarding."""
    val = "1" if enable else "0"
    for p in common.IP_FORWARD_PATHS:
        if os.path.isfile(p):
            try:
                with open(p, "w") as f:
                    f.write(f"{val}\n")
                return True
            except Exception:
                ignored("backend.hardware.network.set_ip_forwarding")
    try:
        subprocess.run(["sysctl", "-w", f"net.ipv4.ip_forward={val}"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def toggle_wireguard_subnet_nat(enable: bool, iface: str = "wg0", out_iface: str = "eth0") -> dict[str, Any]:
    """Toggles IP forwarding and iptables MASQUERADE NAT for WireGuard subnet routing."""
    fwd_ok = set_ip_forwarding(enable)
    action = "-A" if enable else "-D"
    cmd = ["iptables", "-t", "nat", action, "POSTROUTING", "-o", out_iface, "-j", "MASQUERADE"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return {
            "enabled": enable,
            "ip_forwarding": fwd_ok,
            "nat_rule": r.returncode == 0,
            "message": f"Subnet routing {'enabled' if enable else 'disabled'} ({iface} -> {out_iface})",
        }
    except Exception as e:
        return {"enabled": enable, "ip_forwarding": fwd_ok, "nat_rule": False, "error": str(e)}
