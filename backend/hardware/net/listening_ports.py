"""Listening TCP and UDP ports, with the services and containers behind them.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
from typing import Any

from backend.config import logger
from backend.hardware.net import common


def get_active_listening_ports() -> list[dict[str, Any]]:
    """
    Inspects active listening TCP and UDP ports on the host system.
    Correlates ports with well-known services and active Docker containers.
    """
    import socket

    known_services = {
        21: "FTP",
        22: "SSH",
        53: "DNS",
        80: "HTTP",
        137: "NetBIOS Name",
        138: "NetBIOS Datagram",
        139: "NetBIOS Session / SMB",
        443: "HTTPS",
        445: "SMB / CIFS",
        2049: "NFS",
        3000: "App Dashboard",
        3493: "NUT UPS Daemon",
        5353: "mDNS / Bonjour",
        5355: "LLMNR",
        8080: "Web Proxy",
        8082: "ZettNAS Web Desktop",
        8084: "ZettNAS Terminal Proxy",
        8096: "Jellyfin Media Server",
        8888: "Jupyter / Web Service",
        32400: "Plex Media Server",
        51820: "WireGuard VPN",
    }

    def _parse_hex_ip(h: str) -> str:
        try:
            if len(h) == 8:
                return socket.inet_ntoa(bytes.fromhex(h)[::-1])
            elif len(h) == 32:
                if h == "0" * 32:
                    return "::"
                parts = [h[i : i + 8] for i in range(0, 32, 8)]
                raw_bytes = b"".join(bytes.fromhex(p)[::-1] for p in parts)
                return socket.inet_ntop(socket.AF_INET6, raw_bytes)
        except Exception:
            logger.debug(
                "backend.hardware.network.get_active_listening_ports._parse_hex_ip: ignored error", exc_info=True
            )
        return "0.0.0.0"

    container_map = {}
    try:
        from backend.hardware.docker_stats import read_docker_containers

        containers = read_docker_containers()
        for c in containers:
            c_name = c.get("name", "")
            for p in c.get("ports", []):
                hp = p.get("host_port")
                proto = p.get("proto", "tcp").lower()
                if hp:
                    container_map[(hp, proto)] = {
                        "container": c_name,
                        "container_id": c.get("id", "")[:12],
                    }
    except Exception:
        logger.debug("backend.hardware.network.get_active_listening_ports: ignored error", exc_info=True)

    proc_bases = [common.HOST_PROC, "/proc"]
    results = []
    seen = set()

    for proto, filename in [
        ("tcp", "tcp"),
        ("tcp6", "tcp6"),
        ("udp", "udp"),
        ("udp6", "udp6"),
    ]:
        is_udp = "udp" in proto
        is_ipv6 = "6" in proto
        target_state = "07" if is_udp else "0A"

        for base in proc_bases:
            p_file = os.path.join(base, "net", filename)
            if os.path.exists(p_file):
                try:
                    with open(p_file) as f:
                        lines = f.readlines()
                    for line in lines[1:]:
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            local_addr = parts[1]
                            state = parts[3]
                            if is_udp or state == target_state:
                                if ":" in local_addr:
                                    hex_ip, hex_port = local_addr.split(":", 1)
                                    try:
                                        port = int(hex_port, 16)
                                        ip = _parse_hex_ip(hex_ip)
                                    except ValueError:
                                        continue

                                    normalized_proto = "udp" if is_udp else "tcp"
                                    dedup_key = (port, normalized_proto, ip)
                                    if dedup_key in seen:
                                        continue
                                    seen.add(dedup_key)

                                    c_info = container_map.get(
                                        (port, normalized_proto), container_map.get((port, "tcp"), {})
                                    )
                                    service_name = known_services.get(port, c_info.get("container", "Unknown"))

                                    results.append(
                                        {
                                            "port": port,
                                            "protocol": normalized_proto,
                                            "bind_address": ip,
                                            "state": "LISTEN" if not is_udp else "ACTIVE",
                                            "service": service_name,
                                            "container": c_info.get("container", ""),
                                            "container_id": c_info.get("container_id", ""),
                                            "ipv6": is_ipv6,
                                        }
                                    )
                    break
                except Exception as e:
                    logger.debug(f"[Network] Error parsing {p_file}: {e}")

    results.sort(key=lambda x: (x["port"], x["protocol"]))
    return results
