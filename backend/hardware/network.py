import ipaddress
import os
import re
import secrets
import socket
import struct
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from backend.config import HOST_PROC, HOST_SYS, NETWORK_CONFIG_FILE, logger
from backend.fsutil import atomic_write_json, read_json
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

                docker_networks.append(
                    {
                        "id": net_id,
                        "name": net_name,
                        "driver": driver,
                        "subnet": subnet,
                        "gateway": gateway,
                        "bridge_device": bridge_dev,
                        "containers": attached,
                        "container_count": len(attached),
                        "is_custom": net_name not in ("bridge", "host", "none"),
                    }
                )
    except Exception as e:
        logger.debug(f"Docker network topology query error: {e}")

    return docker_networks


def load_network_config() -> Dict[str, Any]:
    """Load persistent network configuration (aliases and port settings)."""
    cfg = read_json(NETWORK_CONFIG_FILE, None)
    if not isinstance(cfg, dict):
        cfg = {"aliases": {}, "ports": {}}
    if "aliases" not in cfg:
        cfg["aliases"] = {}
    if "ports" not in cfg:
        cfg["ports"] = {}
    return cfg


def save_network_config(cfg: Dict[str, Any]) -> None:
    """Save persistent network configuration atomically."""
    atomic_write_json(NETWORK_CONFIG_FILE, cfg)


class CanaryWatchdog:
    """
    60-second self-lockout prevention watchdog for host network reconfiguration.
    Automatically rolls back host IP, gateway, and DNS settings if the client fails
    to confirm connectivity within the timeout window.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.is_active = False
        self.canary_id = ""
        self.started_at = 0.0
        self.deadline = 0.0
        self.target_ip = ""
        self.target_config: Dict[str, Any] = {}
        self.original_config: Dict[str, Any] = {}
        self._timer: Optional[threading.Timer] = None

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            rem = max(0, int(self.deadline - now)) if self.is_active else 0
            return {
                "is_active": self.is_active,
                "expires_in": rem,
                "target_ip": self.target_ip if self.is_active else None,
                "canary_id": self.canary_id if self.is_active else None,
            }

    def arm(
        self,
        target_config: Dict[str, Any],
        original_config: Dict[str, Any],
        timeout_sec: int = 60,
    ) -> str:
        with self._lock:
            if self._timer:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None

            canary_id = secrets.token_hex(8)
            now = time.time()
            self.is_active = True
            self.canary_id = canary_id
            self.started_at = now
            self.deadline = now + timeout_sec
            self.target_config = dict(target_config)
            self.original_config = dict(original_config)
            self.target_ip = target_config.get("ip_address") or ""

            # Launch atomic background rollback watchdog
            self._timer = threading.Timer(float(timeout_sec), self._on_timeout, args=[canary_id])
            self._timer.daemon = True
            self._timer.start()
            return canary_id

    def confirm(self, canary_id: Optional[str] = None) -> bool:
        with self._lock:
            if not self.is_active:
                return False
            if canary_id and canary_id != self.canary_id:
                return False
            if self._timer:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None
            self.is_active = False
            return True

    def revert(self, canary_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self.is_active:
                return None
            if canary_id and canary_id != self.canary_id:
                return None
            if self._timer:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None
            orig = dict(self.original_config)
            self.is_active = False
            return orig

    def _on_timeout(self, canary_id: str):
        orig = None
        with self._lock:
            if not self.is_active or self.canary_id != canary_id:
                return
            orig = dict(self.original_config)
            self.is_active = False
            self._timer = None

        logger.warning(
            f"[Network Canary] 60s Watchdog expired for canary {canary_id}! Auto-reverting host network to prevent self-lockout."
        )
        if orig:
            _execute_revert(orig)
            try:
                from backend.state import add_event

                add_event(
                    "error",
                    "Network Canary Expired",
                    "Canary rollback watchdog expired after 60s without confirmation! Host network automatically restored to prevent lockout.",
                )
            except Exception:
                pass


_CANARY_WATCHDOG = CanaryWatchdog()


def get_canary_watchdog() -> CanaryWatchdog:
    return _CANARY_WATCHDOG


def _parse_unraid_network_cfg() -> Dict[str, str]:
    """Parse key-values from Unraid /boot/config/network.cfg if present."""
    cfg: Dict[str, str] = {}
    candidates = ["/boot/config/network.cfg", "/host/boot/config/network.cfg"]
    for c in candidates:
        if os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            cfg[k.strip()] = v.strip().strip('"').strip("'")
                return cfg
            except Exception as e:
                logger.debug(f"Error parsing unraid network cfg: {e}")
    return cfg


def _write_unraid_network_cfg(updates: Dict[str, str]) -> bool:
    """Update Unraid /boot/config/network.cfg preserving order and unmanaged keys."""
    candidates = ["/boot/config/network.cfg", "/host/boot/config/network.cfg"]
    for c in candidates:
        if os.path.isfile(c):
            try:
                lines = []
                with open(c, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                updated_keys = set()
                new_lines = []
                for line in lines:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        k = stripped.split("=", 1)[0].strip()
                        if k in updates:
                            new_lines.append(f'{k}="{updates[k]}"\n')
                            updated_keys.add(k)
                            continue
                    new_lines.append(line)
                for k, v in updates.items():
                    if k not in updated_keys:
                        new_lines.append(f'{k}="{v}"\n')
                tmp_c = f"{c}.tmp.{os.getpid()}"
                with open(tmp_c, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                os.replace(tmp_c, c)
                return True
            except Exception as e:
                logger.warning(f"Error writing unraid network cfg: {e}")
    return False


def _execute_revert(orig: Dict[str, Any]) -> None:
    """Restores original network settings on the host."""
    cfg = load_network_config()
    cfg.pop("host_ip_staged", None)
    save_network_config(cfg)

    # Revert Unraid /boot/config/network.cfg if on Unraid
    unraid_updates = {}
    orig_mode = orig.get("mode", "static")
    if orig_mode == "dhcp":
        unraid_updates["USE_DHCP[0]"] = "yes"
    else:
        unraid_updates["USE_DHCP[0]"] = "no"
        if orig.get("ip_address"):
            unraid_updates["IPADDR[0]"] = orig["ip_address"]
        if orig.get("netmask"):
            unraid_updates["NETMASK[0]"] = orig["netmask"]
        if orig.get("gateway"):
            unraid_updates["GATEWAY[0]"] = orig["gateway"]
        if orig.get("dns1"):
            unraid_updates["DNS_SERVER1"] = orig["dns1"]
        if "dns2" in orig:
            unraid_updates["DNS_SERVER2"] = orig["dns2"]

    if unraid_updates:
        _write_unraid_network_cfg(unraid_updates)


def _validate_ipv4(val: str, field_name: str) -> str:
    val = (val or "").strip()
    if not val:
        raise ValueError(f"{field_name} is required")
    try:
        ip = ipaddress.IPv4Address(val)
    except ValueError:
        raise ValueError(f"Invalid IPv4 address for {field_name}: {val}")
    if ip.is_loopback:
        raise ValueError(f"{field_name} cannot be a loopback address (127.0.0.0/8)")
    if ip.is_multicast:
        raise ValueError(f"{field_name} cannot be a multicast address")
    if ip.is_unspecified:
        raise ValueError(f"{field_name} cannot be 0.0.0.0")
    if str(ip) == "255.255.255.255":
        raise ValueError(f"{field_name} cannot be broadcast address")
    return str(ip)


def _validate_netmask(val: str) -> str:
    val = (val or "").strip()
    if not val:
        return "255.255.255.0"
    if val.startswith("/"):
        val = val[1:]
    if val.isdigit():
        prefix = int(val)
        if 1 <= prefix <= 32:
            return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
        raise ValueError(f"Invalid CIDR prefix: /{prefix}")
    try:
        net = ipaddress.IPv4Network(f"0.0.0.0/{val}")
        return str(net.netmask)
    except Exception:
        raise ValueError(f"Invalid netmask: {val}")


def get_host_ip_config() -> Dict[str, Any]:
    """Retrieve current host IP, netmask, gateway, DNS, and canary watchdog status."""
    topo = get_network_topology()
    summary = topo.get("summary", {})
    routes = topo.get("routes", [])

    phys_names = [p["name"] for p in topo.get("physical_interfaces", [])]
    br_names = [b["name"] for b in topo.get("bridges", [])]
    bond_names = [b["name"] for b in topo.get("bonds", [])]
    available_ifaces = list(dict.fromkeys(br_names + bond_names + phys_names)) or ["eth0"]

    primary_iface = summary.get("primary_interface") or available_ifaces[0]
    unraid_cfg = _parse_unraid_network_cfg()
    saved_cfg = load_network_config()
    persisted_host = saved_cfg.get("host_ip_config", {})

    # Mode determination
    if "mode" in persisted_host:
        mode = persisted_host["mode"]
    elif "USE_DHCP[0]" in unraid_cfg:
        mode = "dhcp" if unraid_cfg["USE_DHCP[0]"].lower() == "yes" else "static"
    else:
        mode = "static" if summary.get("primary_ip") and summary["primary_ip"] != "?" else "dhcp"

    # Current IP
    current_ip = (
        persisted_host.get("ip_address") or unraid_cfg.get("IPADDR[0]") or summary.get("primary_ip") or read_ip()
    )
    if current_ip == "?":
        current_ip = ""

    # Netmask & CIDR
    netmask = persisted_host.get("netmask") or unraid_cfg.get("NETMASK[0]")
    if not netmask:
        for r in routes:
            if r.get("iface") == primary_iface and r.get("mask") and r["mask"] != "0.0.0.0":
                netmask = r["mask"]
                break
    if not netmask:
        netmask = "255.255.255.0"
    cidr = _mask_to_cidr(netmask)

    # Gateway
    gateway = persisted_host.get("gateway") or unraid_cfg.get("GATEWAY[0]") or summary.get("default_gateway") or ""

    # DNS
    dns_servers = list(summary.get("dns_servers") or [])
    if unraid_cfg.get("DNS_SERVER1") and unraid_cfg["DNS_SERVER1"] not in dns_servers:
        dns_servers.insert(0, unraid_cfg["DNS_SERVER1"])
    if unraid_cfg.get("DNS_SERVER2") and unraid_cfg["DNS_SERVER2"] not in dns_servers:
        dns_servers.append(unraid_cfg["DNS_SERVER2"])

    dns1 = persisted_host.get("dns1") or (dns_servers[0] if len(dns_servers) > 0 else "")
    dns2 = persisted_host.get("dns2") or (dns_servers[1] if len(dns_servers) > 1 else "")

    canary_status = get_canary_watchdog().get_status()

    return {
        "status": "ok",
        "mode": mode,
        "interface": primary_iface,
        "available_interfaces": available_ifaces,
        "ip_address": current_ip,
        "netmask": netmask,
        "cidr": cidr,
        "gateway": gateway,
        "dns1": dns1,
        "dns2": dns2,
        "dns_servers": dns_servers,
        "canary": canary_status,
    }


def apply_host_ip_config_canary(updates: Dict[str, Any], timeout_sec: int = 60) -> Dict[str, Any]:
    """
    Arm 60-second Canary watchdog, snapshot existing network state,
    and stage / apply new Host IP and DNS configuration.
    """
    mode = str(updates.get("mode", "static")).lower().strip()
    if mode not in ("dhcp", "static"):
        raise ValueError("Mode must be 'dhcp' or 'static'")

    interface = str(updates.get("interface", "br0")).strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", interface):
        raise ValueError("Invalid interface name")

    target_cfg: Dict[str, Any] = {
        "mode": mode,
        "interface": interface,
        "updated_at": time.time(),
    }

    if mode == "static":
        ip_addr = _validate_ipv4(updates.get("ip_address", ""), "IPv4 Address")
        netmask = _validate_netmask(updates.get("netmask", "255.255.255.0"))
        gateway = updates.get("gateway", "").strip()
        if gateway:
            gateway = _validate_ipv4(gateway, "Default Gateway")
        dns1 = updates.get("dns1", "").strip()
        if dns1:
            dns1 = _validate_ipv4(dns1, "Primary DNS")
        dns2 = updates.get("dns2", "").strip()
        if dns2:
            dns2 = _validate_ipv4(dns2, "Secondary DNS")

        target_cfg.update(
            {
                "ip_address": ip_addr,
                "netmask": netmask,
                "cidr": _mask_to_cidr(netmask),
                "gateway": gateway,
                "dns1": dns1,
                "dns2": dns2,
            }
        )
    else:
        # DHCP
        dns1 = updates.get("dns1", "").strip()
        if dns1:
            dns1 = _validate_ipv4(dns1, "Primary DNS")
        dns2 = updates.get("dns2", "").strip()
        if dns2:
            dns2 = _validate_ipv4(dns2, "Secondary DNS")
        target_cfg.update(
            {
                "ip_address": "",
                "netmask": "",
                "cidr": 0,
                "gateway": "",
                "dns1": dns1,
                "dns2": dns2,
            }
        )

    # Snapshot current state
    original_cfg = get_host_ip_config()

    # Arm watchdog timer
    timeout_sec = max(10, min(300, int(timeout_sec)))
    canary_id = get_canary_watchdog().arm(target_cfg, original_cfg, timeout_sec=timeout_sec)

    # Stage in network_config.json
    cfg = load_network_config()
    cfg["host_ip_staged"] = {
        "canary_id": canary_id,
        "target": target_cfg,
        "original": original_cfg,
        "deadline": time.time() + timeout_sec,
    }
    save_network_config(cfg)

    # Write Unraid network.cfg if present
    unraid_updates = {}
    if mode == "dhcp":
        unraid_updates["USE_DHCP[0]"] = "yes"
    else:
        unraid_updates["USE_DHCP[0]"] = "no"
        unraid_updates["IPADDR[0]"] = target_cfg["ip_address"]
        unraid_updates["NETMASK[0]"] = target_cfg["netmask"]
        if target_cfg["gateway"]:
            unraid_updates["GATEWAY[0]"] = target_cfg["gateway"]
    if target_cfg.get("dns1"):
        unraid_updates["DNS_SERVER1"] = target_cfg["dns1"]
    if target_cfg.get("dns2"):
        unraid_updates["DNS_SERVER2"] = target_cfg["dns2"]

    if unraid_updates:
        _write_unraid_network_cfg(unraid_updates)

    # Add audit log
    try:
        from backend.state import add_event

        target_display = target_cfg.get("ip_address") or "DHCP Auto"
        add_event(
            "warning",
            "Network Canary Armed",
            f"Testing new host network settings ({target_display}). Rollback watchdog active for {timeout_sec}s.",
        )
    except Exception:
        pass

    target_ip = target_cfg.get("ip_address") or original_cfg.get("ip_address") or ""
    return {
        "status": "testing",
        "canary_id": canary_id,
        "expires_in": timeout_sec,
        "target_ip": target_ip,
        "target_url": f"http://{target_ip}:8082" if target_ip else None,
        "original_ip": original_cfg.get("ip_address"),
        "message": f"Network Canary armed. Please confirm within {timeout_sec}s to keep settings permanently.",
    }


def confirm_host_ip_config(canary_id: Optional[str] = None) -> Dict[str, Any]:
    """Confirms current canary test and commits host IP settings permanently."""
    watchdog = get_canary_watchdog()
    if not watchdog.is_active:
        return {"status": "ok", "message": "No active canary test to confirm"}

    target_cfg = dict(watchdog.target_config)
    success = watchdog.confirm(canary_id=canary_id)
    if not success:
        return {"status": "error", "message": "Invalid or expired canary ID"}

    # Commit permanently in network_config.json
    cfg = load_network_config()
    cfg["host_ip_config"] = target_cfg
    cfg.pop("host_ip_staged", None)
    save_network_config(cfg)

    # Add audit log
    try:
        from backend.state import add_event

        add_event(
            "success",
            "Network Confirmed",
            f"Host network settings confirmed permanently: {target_cfg.get('mode', 'static').upper()} {target_cfg.get('ip_address', '')}",
        )
    except Exception:
        pass

    return {
        "status": "confirmed",
        "config": target_cfg,
        "message": "Host network configuration successfully committed.",
    }


def revert_host_ip_config(canary_id: Optional[str] = None) -> Dict[str, Any]:
    """Manually aborts canary test and immediately restores original network settings."""
    watchdog = get_canary_watchdog()
    if not watchdog.is_active:
        return {"status": "error", "message": "No active canary test to revert"}

    orig = watchdog.revert(canary_id=canary_id)
    if not orig:
        return {"status": "error", "message": "Invalid or expired canary ID"}

    _execute_revert(orig)

    try:
        from backend.state import add_event

        add_event(
            "warning",
            "Network Reverted",
            f"Host network configuration manually reverted to {orig.get('ip_address', 'original')}.",
        )
    except Exception:
        pass

    return {
        "status": "reverted",
        "restored_ip": orig.get("ip_address"),
        "message": "Host network configuration reverted to previous state.",
    }


def _get_unraid_descriptions() -> Dict[str, str]:
    """Parse descriptions from /boot/config/network.cfg if on Unraid."""
    desc_map: Dict[str, str] = {}
    candidates = ["/boot/config/network.cfg", "/host/boot/config/network.cfg"]
    for c in candidates:
        if os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8", errors="replace") as f:
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
                pass
            break
    return desc_map


def _query_ethtool(iface: str) -> str:
    """Query ethtool for an interface safely, checking host namespace if needed."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", iface):
        return ""
    try:
        res = subprocess.run(["ethtool", iface], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 or "Settings for" in res.stdout:
            return res.stdout
    except Exception:
        pass

    if os.path.exists("/host/proc/1/ns/net"):
        try:
            res = subprocess.run(
                ["nsenter", "--net=/host/proc/1/ns/net", "ethtool", iface],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0 or "Settings for" in res.stdout:
                return res.stdout
        except Exception:
            pass

    return ""


def _apply_mtu(iface: str, mtu_val: int) -> bool:
    """Apply MTU via ip link directly or in host netns."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", iface):
        return False
    try:
        res = subprocess.run(
            ["ip", "link", "set", "dev", iface, "mtu", str(mtu_val)],
            capture_output=True,
            timeout=3,
        )
        if res.returncode == 0:
            return True
    except Exception:
        pass

    if os.path.exists("/host/proc/1/ns/net"):
        try:
            res = subprocess.run(
                ["nsenter", "--net=/host/proc/1/ns/net", "ip", "link", "set", "dev", iface, "mtu", str(mtu_val)],
                capture_output=True,
                timeout=3,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

    for sys_base in [HOST_SYS, "/host/sys", "/sys"]:
        mtu_path = os.path.join(sys_base, "class/net", iface, "mtu")
        if os.path.isfile(mtu_path):
            try:
                with open(mtu_path, "w") as f:
                    f.write(str(mtu_val))
                return True
            except Exception:
                pass
    return False


def _apply_wol(iface: str, enabled: bool) -> bool:
    """Apply Wake-on-LAN mode via ethtool."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", iface):
        return False
    wol_arg = "g" if enabled else "d"
    try:
        res = subprocess.run(["ethtool", "-s", iface, "wol", wol_arg], capture_output=True, timeout=3)
        if res.returncode == 0:
            return True
    except Exception:
        pass

    if os.path.exists("/host/proc/1/ns/net"):
        try:
            res = subprocess.run(
                ["nsenter", "--net=/host/proc/1/ns/net", "ethtool", "-s", iface, "wol", wol_arg],
                capture_output=True,
                timeout=3,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass
    return False


def _apply_negotiation(iface: str, autoneg: bool, speed: Optional[int] = None, duplex: str = "full") -> bool:
    """Apply speed/duplex negotiation via ethtool."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", iface):
        return False
    cmd_args = ["-s", iface]
    if autoneg or speed is None:
        cmd_args.extend(["autoneg", "on"])
    else:
        cmd_args.extend(["speed", str(speed), "duplex", duplex, "autoneg", "off"])

    try:
        res = subprocess.run(["ethtool"] + cmd_args, capture_output=True, timeout=3)
        if res.returncode == 0:
            return True
    except Exception:
        pass

    if os.path.exists("/host/proc/1/ns/net"):
        try:
            res = subprocess.run(
                ["nsenter", "--net=/host/proc/1/ns/net", "ethtool"] + cmd_args,
                capture_output=True,
                timeout=3,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass
    return False


def get_port_config(iface_name: str) -> Dict[str, Any]:
    """Retrieve full configuration, hardware capabilities, and alias for a port."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", iface_name):
        return {"status": "error", "message": "Invalid interface name"}

    topo = get_network_topology()
    nic = next((p for p in topo.get("physical_interfaces", []) if p["name"] == iface_name), None)
    if not nic:
        nic = next((b for b in topo.get("bonds", []) + topo.get("bridges", []) if b["name"] == iface_name), None)
    if not nic:
        return {"status": "error", "message": f"Interface '{iface_name}' not found"}

    cfg = load_network_config()
    alias = cfg.get("aliases", {}).get(iface_name, "")
    if not alias:
        unraid_descs = _get_unraid_descriptions()
        alias = unraid_descs.get(iface_name, "")

    ethtool_out = _query_ethtool(iface_name)
    wol_supported = False
    wol_enabled = False
    autoneg = True
    for line in ethtool_out.splitlines():
        line = line.strip()
        if line.startswith("Supports Wake-on:"):
            val = line.split(":", 1)[1].strip()
            wol_supported = any(c in val for c in ["g", "p", "u", "m", "b"])
        elif line.startswith("Wake-on:"):
            val = line.split(":", 1)[1].strip()
            wol_enabled = "g" in val
        elif line.startswith("Auto-negotiation:"):
            val = line.split(":", 1)[1].strip().lower()
            autoneg = val == "on"

    supported_speeds = [10000, 5000, 2500, 1000, 100]

    return {
        "status": "ok",
        "interface": nic,
        "alias": alias,
        "mtu": nic.get("mtu", 1500),
        "wol_supported": wol_supported,
        "wol_enabled": wol_enabled,
        "autoneg": autoneg,
        "supported_speeds": supported_speeds,
    }


def update_port_config(iface_name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update port configuration: friendly alias, MTU, WOL, speed/duplex."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", iface_name):
        return {"status": "error", "message": "Invalid interface name"}

    cfg = load_network_config()
    aliases = cfg.setdefault("aliases", {})
    ports = cfg.setdefault("ports", {})
    port_meta = ports.setdefault(iface_name, {})

    # 1. Alias update
    if "alias" in updates:
        alias = str(updates["alias"]).strip()
        aliases[iface_name] = alias
        port_meta["alias"] = alias

    # 2. MTU update
    if "mtu" in updates and updates["mtu"] is not None:
        try:
            mtu_val = int(updates["mtu"])
            if 68 <= mtu_val <= 9216:
                port_meta["mtu"] = mtu_val
                _apply_mtu(iface_name, mtu_val)
        except (ValueError, TypeError):
            pass

    # 3. Wake-on-LAN update
    if "wol_enabled" in updates:
        wol_en = bool(updates["wol_enabled"])
        port_meta["wol_enabled"] = wol_en
        _apply_wol(iface_name, wol_en)

    # 4. Link Negotiation update
    if "autoneg" in updates or "speed" in updates:
        autoneg = bool(updates.get("autoneg", True))
        speed = updates.get("speed")
        duplex = updates.get("duplex", "full")
        port_meta["autoneg"] = autoneg
        port_meta["speed"] = speed
        port_meta["duplex"] = duplex
        _apply_negotiation(iface_name, autoneg, speed, duplex)

    save_network_config(cfg)
    return {"status": "ok", "message": f"Port configuration saved for {iface_name}", "config": port_meta}


def create_docker_network(name: str, driver: str = "bridge", subnet: str = "", gateway: str = "") -> Dict[str, Any]:
    """Create a new Docker network via Docker engine API."""
    docker_sock = "/var/run/docker.sock"
    if not os.path.exists(docker_sock):
        return {"status": "error", "message": "Docker socket not accessible"}

    if not name or not re.match(r"^[a-zA-Z0-9_\-\.]+$", name):
        return {"status": "error", "message": "Invalid network name"}

    body: Dict[str, Any] = {
        "Name": name,
        "Driver": driver or "bridge",
        "CheckDuplicate": True,
    }

    if subnet:
        ipam_cfg: Dict[str, str] = {"Subnet": subnet}
        if gateway:
            ipam_cfg["Gateway"] = gateway
        body["IPAM"] = {"Config": [ipam_cfg]}

    try:
        transport = httpx.HTTPTransport(uds=docker_sock)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=10.0) as client:
            res = client.post("/networks/create", json=body)
            if res.status_code in (200, 201):
                data = res.json()
                return {"status": "ok", "id": data.get("Id", "")[:12], "message": f"Network '{name}' created"}
            else:
                err_detail = ""
                try:
                    err_detail = res.json().get("message", "")
                except Exception:
                    err_detail = res.text
                return {"status": "error", "message": err_detail or f"Docker API returned {res.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_docker_network(net_id_or_name: str) -> Dict[str, Any]:
    """Delete a custom Docker network via Docker engine API."""
    docker_sock = "/var/run/docker.sock"
    if not os.path.exists(docker_sock):
        return {"status": "error", "message": "Docker socket not accessible"}

    if net_id_or_name in ("bridge", "host", "none"):
        return {"status": "error", "message": f"Cannot delete default system network '{net_id_or_name}'"}

    try:
        transport = httpx.HTTPTransport(uds=docker_sock)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=10.0) as client:
            res = client.delete(f"/networks/{net_id_or_name}")
            if res.status_code in (200, 204):
                return {"status": "ok", "message": f"Network '{net_id_or_name}' deleted"}
            else:
                err_detail = ""
                try:
                    err_detail = res.json().get("message", "")
                except Exception:
                    err_detail = res.text
                return {"status": "error", "message": err_detail or f"Docker API returned {res.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
    saved_cfg = load_network_config()
    saved_aliases = saved_cfg.get("aliases", {})
    unraid_descs = _get_unraid_descriptions()

    # Determine default gateway and primary interface
    non_shim_defaults = [r for r in routes if r.get("is_default") and not r.get("iface", "").startswith("shim-")]
    if non_shim_defaults:
        default_route = sorted(non_shim_defaults, key=lambda x: x.get("metric", 999))[0]
    else:
        default_route = next(
            (r for r in sorted(routes, key=lambda x: x.get("metric", 999)) if r.get("is_default")), None
        )
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

        is_pci_or_platform = (
            "devices/pci" in link_target or "devices/platform" in link_target
        ) and "devices/virtual" not in link_target
        is_virtual = "devices/virtual" in link_target or iface.startswith(
            ("veth", "br-", "docker", "shim-", "tunl", "wg", "tailscale", "tap", "tun")
        )

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

        alias = saved_aliases.get(iface) or unraid_descs.get(iface) or ""

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

            physical_interfaces.append(
                {
                    "name": iface,
                    "alias": alias,
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
                }
            )

        # 2. Check for Bonding interfaces
        elif os.path.isdir(os.path.join(iface_dir, "bonding")):
            mode = _read_file(os.path.join(iface_dir, "bonding/mode"), "")
            slaves = _read_file(os.path.join(iface_dir, "bonding/slaves"), "").split()
            active_slave = _read_file(os.path.join(iface_dir, "bonding/active_slave"), "")
            bonds.append(
                {
                    "name": iface,
                    "alias": alias,
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
                }
            )

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

            bridges.append(
                {
                    "name": iface,
                    "alias": alias,
                    "interfaces": sorted(members),
                    "carrier": carrier,
                    "is_up": is_up,
                    "mtu": mtu,
                    "mac": mac,
                    "ip_address": bridge_ip,
                    "rx_bytes": _read_stat(iface_dir, "rx_bytes"),
                    "tx_bytes": _read_stat(iface_dir, "tx_bytes"),
                }
            )

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
        "canary": get_canary_watchdog().get_status(),
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
                        if not (
                            candidate_ip.startswith("127.")
                            or candidate_ip.startswith("172.")
                            or candidate_ip.endswith(".255")
                            or candidate_ip == "0.0.0.0"
                        ):
                            Z_STATE.discovered_host_ip = candidate_ip
                            return candidate_ip
        except Exception:
            pass

    return "?"
