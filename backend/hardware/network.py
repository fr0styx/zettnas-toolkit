import os
import re
import socket
import struct
import time
from typing import Any, Dict, List, Optional

import httpx

from backend.config import HOST_PROC, HOST_SYS, logger
from backend.state import Z_STATE


def _find_sys_net_dir() -> Optional[str]:
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


def _find_proc_net_path(filename: str) -> Optional[str]:
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
        with open(path, "r", encoding="utf-8", errors="replace") as f:
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


def _format_speed(speed_val: Optional[int], is_up: bool = True) -> str:
    """Format speed in Mbps to human-readable network speed."""
    if not is_up or speed_val is None or speed_val <= 0:
        return "Disconnected" if not is_up else "Unknown"
    if speed_val >= 10000:
        return f"{speed_val // 1000} Gbps"
    elif speed_val >= 2500:
        return "2.5 Gbps"
    elif speed_val >= 1000:
        return f"{speed_val // 1000} Gbps"
    elif speed_val >= 100:
        return f"{speed_val} Mbps"
    return f"{speed_val} Mbps"


def _parse_routes() -> List[Dict[str, Any]]:
    """Parse host route table from /proc/net/route."""
    route_file = _find_proc_net_path("route")
    routes: List[Dict[str, Any]] = []
    if not route_file:
        return routes

    try:
        with open(route_file, "r", encoding="utf-8", errors="replace") as f:
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

                routes.append({
                    "iface": iface,
                    "destination": dest,
                    "gateway": gateway,
                    "mask": mask,
                    "cidr": cidr,
                    "metric": metric,
                    "flags": flags,
                    "is_default": is_default,
                })
    except Exception as e:
        logger.debug(f"Error parsing routes: {e}")

    return routes


def _get_dns_servers() -> List[str]:
    """Retrieve DNS nameservers from config or resolv.conf."""
    servers: List[str] = []
    candidates = [
        "/boot/config/network.cfg",
        "/host/etc/resolv.conf",
        "/etc/resolv.conf",
    ]
    for c in candidates:
        if os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        # Unraid network.cfg format
                        if "DNS_SERVER" in line and "=" in line:
                            val = line.split("=", 1)[1].strip('"\'; ')
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
                pass
        if servers:
            break
    return servers


def _get_docker_topology() -> List[Dict[str, Any]]:
    """Query Docker daemon for active bridge networks and attached container IPs."""
    docker_networks: List[Dict[str, Any]] = []
    docker_sock = "/var/run/docker.sock"
    if not os.path.exists(docker_sock):
        return docker_networks

    try:
        transport = httpx.HTTPTransport(uds=docker_sock)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=2.5) as client:
            net_res = client.get("/networks")
            if net_res.status_code != 200:
                return docker_networks
            raw_networks = net_res.json()

            # Also fetch containers to have full port mapping and IP data
            cnt_res = client.get("/containers/json")
            containers = cnt_res.json() if cnt_res.status_code == 200 else []

            # Map containers by network ID or network name
            containers_by_net: Dict[str, List[Dict[str, Any]]] = {}
            for c in containers:
                c_name = (c.get("Names") or [""])[0].lstrip("/")
                ports = []
                for p in c.get("Ports") or []:
                    pub = p.get("PublicPort")
                    priv = p.get("PrivatePort")
                    ptype = p.get("Type", "tcp")
                    if pub:
                        ports.append(f"{pub}:{priv}/{ptype}")
                    elif priv:
                        ports.append(f"{priv}/{ptype}")

                net_settings = c.get("NetworkSettings", {}).get("Networks", {})
                for n_name, n_info in net_settings.items():
                    c_record = {
                        "name": c_name,
                        "id": (c.get("Id") or "")[:12],
                        "ipv4": n_info.get("IPAddress", ""),
                        "mac": n_info.get("MacAddress", ""),
                        "ports": ports,
                        "state": c.get("State", "running"),
                    }
                    containers_by_net.setdefault(n_name, []).append(c_record)

            for net in raw_networks:
                net_name = net.get("Name", "")
                net_id = (net.get("Id") or "")[:12]
                driver = net.get("Driver", "bridge")
                ipam_configs = (net.get("IPAM") or {}).get("Config") or []
                subnet = ipam_configs[0].get("Subnet", "") if ipam_configs else ""
                gateway = ipam_configs[0].get("Gateway", "") if ipam_configs else ""

                # Find bridge device name (br-<id> or docker0)
                bridge_dev = ""
                if driver == "bridge":
                    if net_name == "bridge":
                        bridge_dev = "docker0"
                    else:
                        bridge_dev = f"br-{net_id}"

                # Attached containers
                attached = containers_by_net.get(net_name, [])

                docker_networks.append({
                    "id": net_id,
                    "name": net_name,
                    "driver": driver,
                    "subnet": subnet,
                    "gateway": gateway,
                    "bridge_device": bridge_dev,
                    "containers": attached,
                    "container_count": len(attached),
                })
    except Exception as e:
        logger.debug(f"Docker network topology query error: {e}")

    return docker_networks


def get_network_topology() -> Dict[str, Any]:
    """
    Expose complete host networking topology, physical NIC carrier states,
    link negotiation speeds (10GbE / 2.5GbE / 1GbE / 100M), duplex, MTU,
    bonding, bridges, and Docker bridge IP mappings.
    """
    sys_net_dir = _find_sys_net_dir()
    if not sys_net_dir:
        return {
            "status": "error",
            "message": "Sysfs net directory not found",
            "summary": {},
            "physical_interfaces": [],
            "bonds": [],
            "bridges": [],
            "docker_networks": [],
            "routes": [],
        }

    physical_interfaces: List[Dict[str, Any]] = []
    bonds: List[Dict[str, Any]] = []
    bridges: List[Dict[str, Any]] = []
    all_ifaces = os.listdir(sys_net_dir)

    routes = _parse_routes()
    dns_servers = _get_dns_servers()

    # Determine default gateway and primary interface
    non_shim_defaults = [r for r in routes if r.get("is_default") and not r.get("iface", "").startswith("shim-")]
    if non_shim_defaults:
        default_route = sorted(non_shim_defaults, key=lambda x: x.get("metric", 999))[0]
    else:
        default_route = next((r for r in sorted(routes, key=lambda x: x.get("metric", 999)) if r.get("is_default")), None)
    default_gw = default_route.get("gateway") if default_route else ""
    primary_iface = default_route.get("iface") if default_route else ""

    for iface in sorted(all_ifaces):
        if iface in ("lo", "bonding_masters"):
            continue

        iface_dir = os.path.join(sys_net_dir, iface)
        if not os.path.exists(iface_dir):
            continue

        # Check symlink target to distinguish physical from virtual
        link_target = ""
        try:
            link_target = os.readlink(iface_dir)
        except OSError:
            pass

        is_pci_or_platform = ("devices/pci" in link_target or "devices/platform" in link_target) and "devices/virtual" not in link_target
        is_virtual = "devices/virtual" in link_target or iface.startswith(("veth", "br-", "docker", "shim-", "tunl", "wg", "tailscale", "tap", "tun"))

        operstate = _read_file(os.path.join(iface_dir, "operstate"), "unknown").lower()
        carrier_str = _read_file(os.path.join(iface_dir, "carrier"), "0")
        carrier = 1 if carrier_str == "1" else 0
        is_up = operstate == "up" and carrier == 1

        raw_speed = _read_file(os.path.join(iface_dir, "speed"), "-1")
        try:
            speed_val = int(raw_speed) if raw_speed and raw_speed.lstrip("-").isdigit() else -1
            if speed_val < 0:
                speed_val = None
        except ValueError:
            speed_val = None

        duplex = _read_file(os.path.join(iface_dir, "duplex"), "unknown").lower()
        mtu = int(_read_file(os.path.join(iface_dir, "mtu"), "1500") or 1500)
        mac = _read_file(os.path.join(iface_dir, "address"), "").lower()

        # Master interface (e.g. bond0 or br0)
        master = None
        master_link = os.path.join(iface_dir, "master")
        if os.path.exists(master_link):
            try:
                master = os.path.basename(os.readlink(master_link))
            except OSError:
                pass

        # 1. Check for physical NICs
        if is_pci_or_platform or (not is_virtual and iface.startswith(("eth", "en", "wl"))):
            # Parse PCI uevent
            pci_slot = ""
            driver = ""
            pci_id = ""
            uevent_path = os.path.join(iface_dir, "device/uevent")
            if os.path.isfile(uevent_path):
                uevent_content = _read_file(uevent_path)
                for line in uevent_content.splitlines():
                    if line.startswith("PCI_SLOT_NAME="):
                        pci_slot = line.split("=", 1)[1]
                    elif line.startswith("DRIVER="):
                        driver = line.split("=", 1)[1]
                    elif line.startswith("PCI_ID="):
                        pci_id = line.split("=", 1)[1]

            physical_interfaces.append({
                "name": iface,
                "state": operstate,
                "carrier": carrier,
                "is_up": is_up,
                "speed_mbps": speed_val if is_up else None,
                "speed_human": _format_speed(speed_val, is_up),
                "duplex": duplex,
                "mtu": mtu,
                "mac": mac,
                "master": master,
                "pci_slot": pci_slot,
                "driver": driver,
                "pci_id": pci_id,
                "rx_bytes": _read_stat(iface_dir, "rx_bytes"),
                "tx_bytes": _read_stat(iface_dir, "tx_bytes"),
                "rx_packets": _read_stat(iface_dir, "rx_packets"),
                "tx_packets": _read_stat(iface_dir, "tx_packets"),
                "rx_errors": _read_stat(iface_dir, "rx_errors"),
                "tx_errors": _read_stat(iface_dir, "tx_errors"),
                "rx_dropped": _read_stat(iface_dir, "rx_dropped"),
                "tx_dropped": _read_stat(iface_dir, "tx_dropped"),
            })

        # 2. Check for Bonding interfaces
        elif os.path.isdir(os.path.join(iface_dir, "bonding")):
            mode = _read_file(os.path.join(iface_dir, "bonding/mode"), "")
            slaves = _read_file(os.path.join(iface_dir, "bonding/slaves"), "").split()
            active_slave = _read_file(os.path.join(iface_dir, "bonding/active_slave"), "")
            bonds.append({
                "name": iface,
                "mode": mode,
                "slaves": slaves,
                "active_slave": active_slave,
                "carrier": carrier,
                "is_up": is_up,
                "speed_mbps": speed_val if is_up else None,
                "speed_human": _format_speed(speed_val, is_up),
                "duplex": duplex,
                "mtu": mtu,
                "mac": mac,
                "master": master,
                "rx_bytes": _read_stat(iface_dir, "rx_bytes"),
                "tx_bytes": _read_stat(iface_dir, "tx_bytes"),
            })

        # 3. Check for Host Bridges (e.g. br0)
        elif os.path.isdir(os.path.join(iface_dir, "bridge")) and not iface.startswith(("br-", "docker0")):
            members = []
            brif_dir = os.path.join(iface_dir, "brif")
            if os.path.isdir(brif_dir):
                members = os.listdir(brif_dir)

            # Match IP address from routes or state
            bridge_ip = ""
            for r in routes:
                if r.get("iface") == iface and r.get("destination") != "0.0.0.0":
                    bridge_ip = f"{r.get('destination')}/{r.get('cidr')}"
                    break

            bridges.append({
                "name": iface,
                "interfaces": sorted(members),
                "carrier": carrier,
                "is_up": is_up,
                "mtu": mtu,
                "mac": mac,
                "ip_address": bridge_ip,
                "rx_bytes": _read_stat(iface_dir, "rx_bytes"),
                "tx_bytes": _read_stat(iface_dir, "tx_bytes"),
            })

    # Docker network inspection
    docker_networks = _get_docker_topology()
    total_containers = sum(len(n.get("containers") or []) for n in docker_networks)

    # Calculate max speed across active physical NICs
    active_speeds = [p["speed_mbps"] for p in physical_interfaces if p["is_up"] and p["speed_mbps"]]
    max_speed_mbps = max(active_speeds) if active_speeds else 0
    max_speed_str = _format_speed(max_speed_mbps, is_up=bool(max_speed_mbps))

    primary_ip = read_ip()

    summary = {
        "primary_ip": primary_ip,
        "default_gateway": default_gw,
        "dns_servers": dns_servers,
        "primary_interface": primary_iface or ("br0" if bridges else "eth0"),
        "total_physical": len(physical_interfaces),
        "active_physical": sum(1 for p in physical_interfaces if p["is_up"]),
        "max_speed": max_speed_str,
        "docker_networks_count": len(docker_networks),
        "docker_containers_count": total_containers,
    }

    return {
        "status": "ok",
        "summary": summary,
        "physical_interfaces": physical_interfaces,
        "bonds": bonds,
        "bridges": bridges,
        "docker_networks": docker_networks,
        "routes": routes,
    }


def read_network_rates():
    now = time.time()
    rx_bytes = 0
    tx_bytes = 0
    chosen_iface = "bond0"

    dev_path = _find_proc_net_path("dev")
    ifaces = {}
    if dev_path:
        try:
            with open(dev_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if ":" in line:
                        iface, data = line.split(":", 1)
                        iface = iface.strip()
                        fields = data.split()
                        if len(fields) >= 9:
                            ifaces[iface] = (int(fields[0]), int(fields[8]))
        except Exception as e:
            logger.debug(f"Silenced exception reading net/dev: {e}")

    # Interface selection hierarchy:
    env_iface = os.environ.get("HOST_NET_IFACE", "").strip()
    if env_iface and env_iface in ifaces:
        chosen_iface = env_iface
        rx_bytes, tx_bytes = ifaces[env_iface]
    elif "bond0" in ifaces:
        chosen_iface = "bond0"
        rx_bytes, tx_bytes = ifaces["bond0"]
    else:
        bond_candidates = [i for i in ifaces if i.startswith("bond")]
        if bond_candidates:
            chosen_iface = bond_candidates[0]
            rx_bytes, tx_bytes = ifaces[chosen_iface]
        elif "br0" in ifaces:
            chosen_iface = "br0"
            rx_bytes, tx_bytes = ifaces["br0"]
        elif "eth0" in ifaces and (ifaces["eth0"][0] > 0 or ifaces["eth0"][1] > 0):
            chosen_iface = "eth0"
            rx_bytes, tx_bytes = ifaces["eth0"]
        else:
            active_phys = [i for i in ifaces if i.startswith(("eth", "en")) and (ifaces[i][0] > 0 or ifaces[i][1] > 0)]
            if active_phys:
                chosen_iface = active_phys[0]
                rx_bytes, tx_bytes = ifaces[chosen_iface]
            elif ifaces:
                chosen_iface = "all"
                for i, (r, t) in ifaces.items():
                    if i in ("lo",) or i.startswith(("veth", "br-", "docker", "shim-", "tunl")):
                        continue
                    rx_bytes += r
                    tx_bytes += t

    prev = getattr(Z_STATE, "prev_net", None)
    if not isinstance(prev, dict):
        prev = {"time": 0.0, "rx": 0, "tx": 0, "iface": chosen_iface}

    if prev.get("iface") != chosen_iface:
        prev = {"time": 0.0, "rx": rx_bytes, "tx": tx_bytes, "iface": chosen_iface}

    prev_time = prev.get("time", 0.0)
    dt = max(0.1, now - prev_time)
    rx_rate = 0.0
    tx_rate = 0.0

    if prev_time > 0 and rx_bytes >= prev.get("rx", 0) and tx_bytes >= prev.get("tx", 0):
        rx_rate = max(0.0, (rx_bytes - prev.get("rx", 0)) / dt)
        tx_rate = max(0.0, (tx_bytes - prev.get("tx", 0)) / dt)

    Z_STATE.prev_net = {"time": now, "rx": rx_bytes, "tx": tx_bytes, "iface": chosen_iface}

    def fmt_speed(b):
        if b >= 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024 * 1024):.1f} GB/s"
        elif b >= 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MB/s"
        elif b >= 1024:
            return f"{b / 1024:.0f} KB/s"
        return f"{b:.0f} B/s"

    return {
        "rx": fmt_speed(rx_rate),
        "tx": fmt_speed(tx_rate),
        "rx_bytes": rx_bytes,
        "tx_bytes": tx_bytes,
        "rx_rate": round(rx_rate, 1),
        "tx_rate": round(tx_rate, 1),
        "iface": chosen_iface,
    }


def read_ip():
    env_ip = os.environ.get("HOST_IP", "").strip()
    if env_ip:
        return env_ip

    if getattr(Z_STATE, "discovered_host_ip", None):
        return Z_STATE.discovered_host_ip

    # 1. Check known network configs
    for p in ["/boot/config/network.cfg", "/host/etc/network/interfaces"]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                ip_match = re.search(r'IPADDR(?:.*?)="?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"?', content)
                if not ip_match:
                    ip_match = re.search(r"address\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", content)

                if ip_match:
                    Z_STATE.discovered_host_ip = ip_match.group(1)
                    return Z_STATE.discovered_host_ip

                matches = re.findall(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", content)
                for ip in matches:
                    if not (ip.startswith("127.") or ip.startswith("172.") or ip.endswith(".255") or ip == "0.0.0.0"):
                        Z_STATE.discovered_host_ip = ip
                        return ip
            except Exception as e:
                logger.debug(f"Silenced exception: {e}")

    # 2. Check /proc/net/fib_trie for local host IPs
    fib_path = _find_proc_net_path("fib_trie")
    if fib_path:
        try:
            with open(fib_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if "/32 host LOCAL" in line and i > 0:
                    prev_line = lines[i - 1].strip()
                    m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", prev_line)
                    if m:
                        candidate_ip = m.group(1)
                        if not (candidate_ip.startswith("127.") or candidate_ip.startswith("172.") or candidate_ip.endswith(".255") or candidate_ip == "0.0.0.0"):
                            Z_STATE.discovered_host_ip = candidate_ip
                            return candidate_ip
        except Exception:
            pass

    return "?"
