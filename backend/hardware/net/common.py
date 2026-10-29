"""Where the host's network files are, small parsers (addresses, masks, speeds, routes, DNS) and the saved network settings.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import re
import socket
import struct
from typing import Any

from backend.config import (
    HOST_PROC,
    HOST_SYS,
    NETWORK_CONFIG_FILE,
    docker_sock,  # noqa: F401  (the other modules read it as common.docker_sock)
    logger,
)
from backend.config import docker_sock as _docker_sock_path  # noqa: F401  (likewise)
from backend.fsutil import atomic_write_json, read_json
from backend.ignored_errors import ignored

# Host files read or written here (module constants so tests can point them elsewhere)
UNRAID_NETWORK_CFG = ("/boot/config/network.cfg", "/host/boot/config/network.cfg")
DNS_SOURCES = ("/boot/config/network.cfg", "/host/etc/resolv.conf", "/etc/resolv.conf")
HOST_IP_SOURCES = ("/boot/config/network.cfg", "/host/etc/network/interfaces")
IP_FORWARD_PATHS = ("/proc/sys/net/ipv4/ip_forward", os.path.join(HOST_PROC, "sys/net/ipv4/ip_forward"))


def _find_sys_net_dir() -> str | None:
    """Find the sysfs class/net directory on host or container."""
    candidates = [
        os.path.join(HOST_SYS, "class/net"),
        "/host/sys/class/net",
        "/sys/class/net",
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return None


def _find_proc_net_path(filename: str) -> str | None:
    """Find a /proc/net path on host (preferred) or container."""
    candidates = [
        os.path.join(HOST_PROC, "1/net", filename),
        os.path.join(HOST_PROC, "net", filename),
        f"/proc/1/net/{filename}",
        f"/proc/net/{filename}",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _read_file(path: str, default: str = "") -> str:
    """Safely read stripped contents of a single-line file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except Exception:
        return default


def _read_stat(iface_dir: str, stat_name: str) -> int:
    """Read a metric counter from statistics/."""
    val = _read_file(os.path.join(iface_dir, "statistics", stat_name), "0")
    try:
        return int(val)
    except ValueError:
        return 0


def _hex_to_ip(hex_str: str) -> str:
    """Convert 8-char little-endian hex to IPv4 dotted quad."""
    try:
        return socket.inet_ntoa(struct.pack("<L", int(hex_str, 16)))
    except Exception:
        return hex_str


def _mask_to_cidr(mask_ip: str) -> int:
    """Convert IPv4 netmask to CIDR prefix integer."""
    try:
        return sum(bin(int(x)).count("1") for x in mask_ip.split("."))
    except Exception:
        return 24


def _format_speed(speed_val: int | None, is_up: bool = True) -> str:
    """Format speed in Mbps to human-readable network speed."""
    if not is_up or speed_val is None or speed_val <= 0:
        return "Disconnected" if not is_up else "Unknown"
    if speed_val >= 10000:
        if speed_val % 1000 == 0:
            return f"{speed_val // 1000} Gbps"
        return f"{speed_val / 1000:.1f} Gbps"
    elif speed_val >= 5000:
        return "5 Gbps"
    elif speed_val >= 2500:
        return "2.5 Gbps"
    elif speed_val >= 1000:
        return f"{speed_val // 1000} Gbps"
    elif speed_val >= 100:
        return f"{speed_val} Mbps"
    return f"{speed_val} Mbps"


def _parse_routes() -> list[dict[str, Any]]:
    """Parse host route table from /proc/net/route."""
    route_file = _find_proc_net_path("route")
    routes: list[dict[str, Any]] = []
    if not route_file:
        return routes

    try:
        with open(route_file, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for line in lines[1:]:
            parts = line.strip().split()
            if len(parts) >= 8:
                iface = parts[0]
                dest = _hex_to_ip(parts[1])
                gateway = _hex_to_ip(parts[2])
                flags = int(parts[3], 16) if parts[3].isalnum() else 0
                metric = int(parts[6]) if parts[6].isdigit() else 0
                mask = _hex_to_ip(parts[7])
                cidr = _mask_to_cidr(mask)
                is_default = dest == "0.0.0.0" and flags & 0x0002 != 0

                routes.append(
                    {
                        "iface": iface,
                        "destination": dest,
                        "gateway": gateway,
                        "mask": mask,
                        "cidr": cidr,
                        "metric": metric,
                        "flags": flags,
                        "is_default": is_default,
                    }
                )
    except Exception as e:
        logger.debug(f"Error parsing routes: {e}")

    return routes


def _get_dns_servers() -> list[str]:
    """Retrieve DNS nameservers from config or resolv.conf."""
    servers: list[str] = []
    for c in DNS_SOURCES:
        if os.path.isfile(c):
            try:
                with open(c, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        # Unraid network.cfg format
                        if "DNS_SERVER" in line and "=" in line:
                            val = line.split("=", 1)[1].strip("\"'; ")
                            if val and val not in servers:
                                servers.append(val)
                        # Standard resolv.conf
                        elif line.startswith("nameserver"):
                            parts = line.split()
                            if len(parts) >= 2:
                                ns = parts[1]
                                # Skip docker internal resolver 127.0.0.11 unless nothing else
                                if ns != "127.0.0.11" and ns not in servers:
                                    servers.append(ns)
                        elif "ExtServers: [host(" in line:
                            # Docker comment containing actual host resolver
                            match = re.search(r"ExtServers:\s*\[host\((.*?)\)\]", line)
                            if match and match.group(1) not in servers:
                                servers.append(match.group(1))
            except Exception:
                ignored("backend.hardware.network._get_dns_servers")
        if servers:
            break
    return servers


def load_network_config() -> dict[str, Any]:
    """Load persistent network configuration (aliases and port settings)."""
    cfg = read_json(NETWORK_CONFIG_FILE, None)
    if not isinstance(cfg, dict):
        cfg = {"aliases": {}, "ports": {}}
    if "aliases" not in cfg:
        cfg["aliases"] = {}
    if "ports" not in cfg:
        cfg["ports"] = {}
    return cfg


def save_network_config(cfg: dict[str, Any]) -> None:
    """Save persistent network configuration atomically."""
    atomic_write_json(NETWORK_CONFIG_FILE, cfg)


def _get_unraid_descriptions() -> dict[str, str]:
    """Parse descriptions from /boot/config/network.cfg if on Unraid."""
    desc_map: dict[str, str] = {}
    for c in UNRAID_NETWORK_CFG:
        if os.path.isfile(c):
            try:
                with open(c, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    if line.startswith("DESCRIPTION[") and "=" in line:
                        m = re.match(r'DESCRIPTION\[(\d+)\]="?(.*?)"?$', line)
                        if m:
                            idx = m.group(1)
                            desc = m.group(2)
                            desc_map[idx] = desc
                            if idx == "0":
                                desc_map["eth0"] = desc
                                desc_map["br0"] = desc
                                desc_map["bond0"] = desc
            except Exception:
                ignored("backend.hardware.network._get_unraid_descriptions")
            break
    return desc_map


BONDING_MODES: dict[str, dict[str, Any]] = {
    "0": {
        "code": "0",
        "name": "balance-rr",
        "title": "Round-Robin",
        "description": "Transmit packets in sequential order from first available slave to last. Provides link load balancing and fault tolerance.",
    },
    "1": {
        "code": "1",
        "name": "active-backup",
        "title": "Active-Backup (Failover)",
        "description": "Only one slave in the bond is active. A different slave becomes active if and only if the active slave fails. Recommended for unmanaged switches.",
    },
    "2": {
        "code": "2",
        "name": "balance-xor",
        "title": "Balance-XOR",
        "description": "Transmit based on the selected transmit hash policy (MAC / IP). Provides load balancing and fault tolerance.",
    },
    "4": {
        "code": "4",
        "name": "802.3ad",
        "title": "IEEE 802.3ad LACP (Dynamic Link Aggregation)",
        "description": "IEEE 802.3ad Dynamic Link Aggregation. Requires an 802.3ad LACP-capable switch with matching LAG/trunk configured.",
    },
    "6": {
        "code": "6",
        "name": "balance-alb",
        "title": "Adaptive Load Balancing (ALB)",
        "description": "Includes balance-tlb plus receive load balancing (RLB) for IPv4 traffic. Does not require special switch configuration.",
    },
}
