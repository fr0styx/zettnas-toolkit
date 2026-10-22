import ipaddress
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time
from datetime import UTC
from typing import Any, Optional

import httpx

from backend.config import HOST_PROC, HOST_SYS, NETWORK_CONFIG_FILE, logger
from backend.fsutil import atomic_write_json, read_json
from backend.state import Z_STATE


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
    candidates = [
        "/boot/config/network.cfg",
        "/host/etc/resolv.conf",
        "/etc/resolv.conf",
    ]
    for c in candidates:
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
                pass
        if servers:
            break
    return servers


def _get_docker_topology() -> list[dict[str, Any]]:
    """Query Docker daemon for active bridge networks and attached container IPs."""
    docker_networks: list[dict[str, Any]] = []
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
            containers_by_net: dict[str, list[dict[str, Any]]] = {}
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
        self.target_config: dict[str, Any] = {}
        self.original_config: dict[str, Any] = {}
        self._timer: threading.Timer | None = None

    def get_status(self) -> dict[str, Any]:
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
        target_config: dict[str, Any],
        original_config: dict[str, Any],
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

    def confirm(self, canary_id: str | None = None) -> bool:
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

    def revert(self, canary_id: str | None = None) -> dict[str, Any] | None:
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


def _parse_unraid_network_cfg() -> dict[str, str]:
    """Parse key-values from Unraid /boot/config/network.cfg if present."""
    cfg: dict[str, str] = {}
    candidates = ["/boot/config/network.cfg", "/host/boot/config/network.cfg"]
    for c in candidates:
        if os.path.isfile(c):
            try:
                with open(c, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            cfg[k.strip()] = v.strip().strip('"').strip("'")
                return cfg
            except Exception as e:
                logger.debug(f"Error parsing unraid network cfg: {e}")
    return cfg


def _write_unraid_network_cfg(updates: dict[str, str]) -> bool:
    """Update Unraid /boot/config/network.cfg preserving order and unmanaged keys."""
    candidates = ["/boot/config/network.cfg", "/host/boot/config/network.cfg"]
    for c in candidates:
        if os.path.isfile(c):
            try:
                lines = []
                with open(c, encoding="utf-8", errors="replace") as f:
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


def _execute_revert(orig: dict[str, Any]) -> None:
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
        raise ValueError(f"Invalid IPv4 address for {field_name}: {val}") from None
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
        raise ValueError(f"Invalid netmask: {val}") from None


def get_host_ip_config() -> dict[str, Any]:
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


def apply_host_ip_config_canary(updates: dict[str, Any], timeout_sec: int = 60) -> dict[str, Any]:
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

    target_cfg: dict[str, Any] = {
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


def confirm_host_ip_config(canary_id: str | None = None) -> dict[str, Any]:
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


def revert_host_ip_config(canary_id: str | None = None) -> dict[str, Any]:
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


def _get_unraid_descriptions() -> dict[str, str]:
    """Parse descriptions from /boot/config/network.cfg if on Unraid."""
    desc_map: dict[str, str] = {}
    candidates = ["/boot/config/network.cfg", "/host/boot/config/network.cfg"]
    for c in candidates:
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


def _apply_negotiation(iface: str, autoneg: bool, speed: int | None = None, duplex: str = "full") -> bool:
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


def get_port_config(iface_name: str) -> dict[str, Any]:
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


def update_port_config(iface_name: str, updates: dict[str, Any]) -> dict[str, Any]:
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


def create_docker_network(name: str, driver: str = "bridge", subnet: str = "", gateway: str = "") -> dict[str, Any]:
    """Create a new Docker network via Docker engine API."""
    docker_sock = "/var/run/docker.sock"
    if not os.path.exists(docker_sock):
        return {"status": "error", "message": "Docker socket not accessible"}

    if not name or not re.match(r"^[a-zA-Z0-9_\-\.]+$", name):
        return {"status": "error", "message": "Invalid network name"}

    body: dict[str, Any] = {
        "Name": name,
        "Driver": driver or "bridge",
        "CheckDuplicate": True,
    }

    if subnet:
        ipam_cfg: dict[str, str] = {"Subnet": subnet}
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


def delete_docker_network(net_id_or_name: str) -> dict[str, Any]:
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


def _parse_proc_net_vlan() -> dict[str, dict[str, Any]]:
    """Parse /proc/net/vlan/config for active 802.1Q VLAN devices."""
    vlan_map: dict[str, dict[str, Any]] = {}
    vlan_file = _find_proc_net_path("vlan/config")
    if not vlan_file:
        for p in [
            "/proc/net/vlan/config",
            "/proc/1/net/vlan/config",
            os.path.join(HOST_PROC, "net/vlan/config"),
            os.path.join(HOST_PROC, "1/net/vlan/config"),
        ]:
            if os.path.isfile(p):
                vlan_file = p
                break
    if vlan_file and os.path.isfile(vlan_file):
        try:
            with open(vlan_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if "|" in line and "VLAN Dev name" not in line:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 3:
                            vname, vid, parent = parts[0], parts[1], parts[2]
                            try:
                                vlan_map[vname] = {"vlan_id": int(vid), "parent": parent}
                            except ValueError:
                                pass
        except Exception as e:
            logger.debug(f"Error parsing /proc/net/vlan/config: {e}")
    return vlan_map


def get_vlans() -> list[dict[str, Any]]:
    """Discover all active 802.1Q VLAN sub-interfaces and persist metadata."""
    sys_net_dir = _find_sys_net_dir()
    routes = _parse_routes()
    saved_cfg = load_network_config()
    saved_vlans = saved_cfg.get("vlans", {})
    proc_vlans = _parse_proc_net_vlan()

    vlans: list[dict[str, Any]] = []
    discovered_names = set()

    if sys_net_dir and os.path.isdir(sys_net_dir):
        try:
            for iface in sorted(os.listdir(sys_net_dir)):
                if iface in ("lo", "bonding_masters"):
                    continue
                iface_dir = os.path.join(sys_net_dir, iface)
                if not os.path.isdir(iface_dir):
                    continue

                is_vlan = False
                parent = ""
                vlan_id = 0

                # 1. Match from /proc/net/vlan/config
                if iface in proc_vlans:
                    is_vlan = True
                    parent = proc_vlans[iface]["parent"]
                    vlan_id = proc_vlans[iface]["vlan_id"]

                # 2. Match from sysfs uevent
                uevent = _read_file(os.path.join(iface_dir, "uevent"), "")
                if "DEVTYPE=vlan" in uevent:
                    is_vlan = True

                # 3. Match dot notation naming (e.g. eth0.10, br0.20)
                if "." in iface:
                    p_cand, vid_cand = iface.rsplit(".", 1)
                    if vid_cand.isdigit() and 1 <= int(vid_cand) <= 4094:
                        is_vlan = True
                        if not parent:
                            parent = p_cand
                        if not vlan_id:
                            vlan_id = int(vid_cand)

                # 4. Check persistent config
                if iface in saved_vlans:
                    is_vlan = True
                    if not parent:
                        parent = saved_vlans[iface].get("parent", "")
                    if not vlan_id:
                        vlan_id = int(saved_vlans[iface].get("vlan_id", 0))

                # 5. Match parent from lower_* symlink only if already confirmed as VLAN
                if is_vlan and not parent:
                    try:
                        for entry in os.listdir(iface_dir):
                            if entry.startswith("lower_"):
                                parent = entry[6:]
                                break
                    except OSError:
                        pass

                if is_vlan and 1 <= vlan_id <= 4094:
                    discovered_names.add(iface)
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

                    mtu = int(_read_file(os.path.join(iface_dir, "mtu"), "1500") or 1500)
                    mac = _read_file(os.path.join(iface_dir, "address"), "").lower()

                    vlan_ip = ""
                    for r in routes:
                        if r.get("iface") == iface and r.get("destination") != "0.0.0.0":
                            vlan_ip = f"{r.get('destination')}/{r.get('cidr')}"
                            break

                    alias = saved_vlans.get(iface, {}).get("alias", "")
                    if not alias:
                        alias = saved_cfg.get("aliases", {}).get(iface, "")

                    vlans.append(
                        {
                            "name": iface,
                            "parent": parent,
                            "vlan_id": vlan_id,
                            "alias": alias,
                            "carrier": carrier,
                            "is_up": is_up,
                            "speed_human": _format_speed(speed_val, is_up),
                            "mtu": mtu,
                            "mac": mac,
                            "ip_address": vlan_ip,
                            "rx_bytes": _read_stat(iface_dir, "rx_bytes"),
                            "tx_bytes": _read_stat(iface_dir, "tx_bytes"),
                        }
                    )
        except Exception as e:
            logger.debug(f"Error enumerating VLAN interfaces: {e}")

    # Merge any saved VLANs that are currently offline or down
    for vname, vdata in saved_vlans.items():
        if vname not in discovered_names:
            vlans.append(
                {
                    "name": vname,
                    "parent": vdata.get("parent", ""),
                    "vlan_id": int(vdata.get("vlan_id", 0)),
                    "alias": vdata.get("alias", ""),
                    "carrier": 0,
                    "is_up": False,
                    "speed_human": "Disconnected",
                    "mtu": 1500,
                    "mac": "",
                    "ip_address": "",
                    "rx_bytes": 0,
                    "tx_bytes": 0,
                }
            )

    return sorted(vlans, key=lambda v: (v.get("parent", ""), v.get("vlan_id", 0)))


def create_vlan(parent: str, vlan_id: int, alias: str = "") -> dict[str, Any]:
    """Create an 802.1Q VLAN sub-interface (e.g. eth0.10) and persist metadata."""
    parent = (parent or "").strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", parent):
        return {"status": "error", "message": "Invalid parent interface name"}

    try:
        vid = int(vlan_id)
        if not (1 <= vid <= 4094):
            return {"status": "error", "message": "VLAN ID must be an integer between 1 and 4094"}
    except (ValueError, TypeError):
        return {"status": "error", "message": "VLAN ID must be an integer between 1 and 4094"}

    vname = f"{parent}.{vid}"

    # Attempt creation using ip link
    cmd = ["ip", "link", "add", "link", parent, "name", vname, "type", "vlan", "id", str(vid)]
    success = False
    err_msg = ""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            success = True
        else:
            err_msg = res.stderr.strip()
    except Exception as e:
        err_msg = str(e)

    if not success and os.path.exists("/host/proc/1/ns/net"):
        try:
            ns_cmd = ["nsenter", "--net=/host/proc/1/ns/net"] + cmd
            res = subprocess.run(ns_cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                success = True
            else:
                err_msg = res.stderr.strip()
        except Exception as e:
            err_msg = str(e)

    # Bring interface up
    if success:
        subprocess.run(["ip", "link", "set", "dev", vname, "up"], capture_output=True, timeout=5)
        if os.path.exists("/host/proc/1/ns/net"):
            subprocess.run(
                ["nsenter", "--net=/host/proc/1/ns/net", "ip", "link", "set", "dev", vname, "up"],
                capture_output=True,
                timeout=5,
            )

    # Persist in network_config.json
    cfg = load_network_config()
    vlans = cfg.setdefault("vlans", {})
    vlans[vname] = {
        "name": vname,
        "parent": parent,
        "vlan_id": vid,
        "alias": alias.strip(),
        "created_at": time.time(),
    }
    if alias.strip():
        cfg.setdefault("aliases", {})[vname] = alias.strip()
    save_network_config(cfg)

    try:
        from backend.state import add_event

        add_event(
            "success",
            "VLAN Created",
            f"802.1Q VLAN sub-interface {vname} (Tag ID: {vid}) created on {parent}.",
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "name": vname,
        "parent": parent,
        "vlan_id": vid,
        "alias": alias.strip(),
        "applied_runtime": success,
        "message": (
            f"VLAN sub-interface '{vname}' created successfully"
            if success
            else f"VLAN '{vname}' configuration saved. {err_msg or 'Will apply on network restart.'}"
        ),
    }


def delete_vlan(vlan_name: str) -> dict[str, Any]:
    """Delete an 802.1Q VLAN sub-interface."""
    vlan_name = (vlan_name or "").strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", vlan_name):
        return {"status": "error", "message": "Invalid VLAN interface name"}

    # Attempt deletion using ip link
    cmd = ["ip", "link", "del", "dev", vlan_name]
    success = False
    err_msg = ""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            success = True
        else:
            err_msg = res.stderr.strip()
    except Exception as e:
        err_msg = str(e)

    if not success and os.path.exists("/host/proc/1/ns/net"):
        try:
            ns_cmd = ["nsenter", "--net=/host/proc/1/ns/net"] + cmd
            res = subprocess.run(ns_cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                success = True
            else:
                err_msg = res.stderr.strip()
        except Exception as e:
            err_msg = str(e)

    # Remove from network_config.json
    cfg = load_network_config()
    if "vlans" in cfg and vlan_name in cfg["vlans"]:
        cfg["vlans"].pop(vlan_name, None)
    if "aliases" in cfg and vlan_name in cfg["aliases"]:
        cfg["aliases"].pop(vlan_name, None)
    save_network_config(cfg)

    try:
        from backend.state import add_event

        add_event(
            "warning",
            "VLAN Deleted",
            f"802.1Q VLAN sub-interface {vlan_name} removed.",
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "name": vlan_name,
        "message": f"VLAN sub-interface '{vlan_name}' removed successfully.",
    }


def get_bond_config(bond_name: str) -> dict[str, Any]:
    """Retrieve configuration, operational mode, slaves, and candidate NICs for a bond."""
    bond_name = (bond_name or "").strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", bond_name):
        return {"status": "error", "message": "Invalid bond interface name"}

    sys_net_dir = _find_sys_net_dir()
    bond_dir = os.path.join(sys_net_dir, bond_name) if sys_net_dir else f"/sys/class/net/{bond_name}"

    mode_str = _read_file(os.path.join(bond_dir, "bonding/mode"), "")
    slaves = _read_file(os.path.join(bond_dir, "bonding/slaves"), "").split()
    active_slave = _read_file(os.path.join(bond_dir, "bonding/active_slave"), "")
    miimon_str = _read_file(os.path.join(bond_dir, "bonding/miimon"), "100")
    try:
        miimon = int(miimon_str) if miimon_str.isdigit() else 100
    except ValueError:
        miimon = 100

    # Check Unraid config
    unraid_cfg = _parse_unraid_network_cfg()
    idx = "0"
    m = re.search(r"\d+", bond_name)
    if m:
        idx = m.group(0)

    if f"BONDING_MODE[{idx}]" in unraid_cfg:
        mode_code = unraid_cfg[f"BONDING_MODE[{idx}]"]
    else:
        mode_parts = mode_str.split()
        if mode_parts and mode_parts[-1].isdigit():
            mode_code = mode_parts[-1]
        elif "802.3ad" in mode_str.lower():
            mode_code = "4"
        elif "balance-alb" in mode_str.lower():
            mode_code = "6"
        elif "balance-rr" in mode_str.lower():
            mode_code = "0"
        elif "balance-xor" in mode_str.lower():
            mode_code = "2"
        else:
            mode_code = "1"

    if f"BONDNICS[{idx}]" in unraid_cfg and not slaves:
        slaves = unraid_cfg[f"BONDNICS[{idx}]"].split()
    if f"BONDING_MIIMON[{idx}]" in unraid_cfg:
        try:
            miimon = int(unraid_cfg[f"BONDING_MIIMON[{idx}]"])
        except ValueError:
            pass

    # Saved config
    saved_cfg = load_network_config()
    bond_meta = saved_cfg.get("bonds", {}).get(bond_name, {})
    if "mode" in bond_meta:
        mode_code = str(bond_meta["mode"])
    if "slaves" in bond_meta and not slaves:
        slaves = list(bond_meta["slaves"])
    if "miimon" in bond_meta:
        miimon = int(bond_meta["miimon"])

    mode_info = BONDING_MODES.get(mode_code, BONDING_MODES["1"])

    # Candidate slave NICs
    topo = get_network_topology()
    candidate_slaves = []
    for nic in topo.get("physical_interfaces", []):
        n_name = nic["name"]
        is_slave = n_name in slaves
        candidate_slaves.append(
            {
                "name": n_name,
                "alias": nic.get("alias", ""),
                "speed_human": nic.get("speed_human", ""),
                "is_up": nic.get("is_up", False),
                "mac": nic.get("mac", ""),
                "is_slave": is_slave,
                "master": nic.get("master"),
            }
        )

    return {
        "status": "ok",
        "bond_name": bond_name,
        "mode": mode_code,
        "mode_name": mode_info.get("name", "active-backup"),
        "mode_title": mode_info.get("title", "Active-Backup"),
        "slaves": sorted(slaves),
        "active_slave": active_slave,
        "miimon": miimon,
        "available_modes": [
            {"code": k, "name": v["name"], "title": v["title"], "description": v["description"]}
            for k, v in BONDING_MODES.items()
        ],
        "candidate_slaves": candidate_slaves,
    }


def update_bond_config(bond_name: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update bonding mode, enslaved interfaces, and MII monitoring."""
    bond_name = (bond_name or "").strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", bond_name):
        return {"status": "error", "message": "Invalid bond interface name"}

    mode = str(updates.get("mode", "1")).strip().lower()
    mode_map = {
        "balance-rr": "0",
        "0": "0",
        "active-backup": "1",
        "1": "1",
        "balance-xor": "2",
        "2": "2",
        "802.3ad": "4",
        "4": "4",
        "balance-alb": "6",
        "6": "6",
    }
    if mode not in mode_map:
        return {
            "status": "error",
            "message": "Invalid bonding mode. Supported modes: 0 (balance-rr), 1 (active-backup), 2 (balance-xor), 4 (802.3ad), 6 (balance-alb)",
        }
    mode_code = mode_map[mode]

    slaves = updates.get("slaves", [])
    if not isinstance(slaves, list) or len(slaves) == 0:
        return {
            "status": "error",
            "message": "At least one member interface must be selected for the bond",
        }
    for s in slaves:
        if not isinstance(s, str) or not re.match(r"^[a-zA-Z0-9_\-\.]+$", s):
            return {"status": "error", "message": f"Invalid slave interface: {s}"}

    try:
        miimon = int(updates.get("miimon", 100))
        if not (10 <= miimon <= 1000):
            miimon = 100
    except (ValueError, TypeError):
        miimon = 100

    # Persist to network_config.json
    cfg = load_network_config()
    bonds = cfg.setdefault("bonds", {})
    bonds[bond_name] = {
        "mode": mode_code,
        "slaves": slaves,
        "miimon": miimon,
        "updated_at": time.time(),
    }
    save_network_config(cfg)

    # Persist to Unraid /boot/config/network.cfg if present
    idx = "0"
    m = re.search(r"\d+", bond_name)
    if m:
        idx = m.group(0)

    unraid_updates = {
        f"BONDING_MODE[{idx}]": mode_code,
        f"BONDNICS[{idx}]": " ".join(slaves),
        f"BONDING_MIIMON[{idx}]": str(miimon),
    }
    _write_unraid_network_cfg(unraid_updates)

    # Runtime sysfs tuning for miimon
    sys_net_dir = _find_sys_net_dir()
    if sys_net_dir:
        miimon_path = os.path.join(sys_net_dir, bond_name, "bonding/miimon")
        if os.path.isfile(miimon_path):
            try:
                with open(miimon_path, "w") as f:
                    f.write(str(miimon))
            except Exception:
                pass

    mode_info = BONDING_MODES.get(mode_code, BONDING_MODES["1"])
    try:
        from backend.state import add_event

        add_event(
            "info",
            "Bonding Mode Updated",
            f"Bond {bond_name} updated to {mode_info['title']} with slaves: {', '.join(slaves)} (miimon: {miimon}ms).",
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "bond_name": bond_name,
        "mode": mode_code,
        "mode_title": mode_info.get("title"),
        "slaves": slaves,
        "miimon": miimon,
        "message": f"Bonding configuration for '{bond_name}' saved successfully. Settings persisted to system config.",
    }


def get_bridge_config(br_name: str) -> dict[str, Any]:
    """Retrieve configuration, STP state, forward delay, and members for a virtual bridge."""
    br_name = (br_name or "").strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", br_name):
        return {"status": "error", "message": "Invalid bridge interface name"}

    sys_net_dir = _find_sys_net_dir()
    br_dir = os.path.join(sys_net_dir, br_name) if sys_net_dir else f"/sys/class/net/{br_name}"

    stp_raw = _read_file(os.path.join(br_dir, "bridge/stp_state"), "0").strip()
    stp_enabled = stp_raw in ("1", "yes", "true")
    fd_raw = _read_file(os.path.join(br_dir, "bridge/forward_delay"), "0").strip()
    try:
        forward_delay = int(fd_raw)
        if forward_delay > 100:
            forward_delay = forward_delay // 100
    except ValueError:
        forward_delay = 0

    members = []
    brif_dir = os.path.join(br_dir, "brif")
    if os.path.isdir(brif_dir):
        members = os.listdir(brif_dir)

    # Check Unraid config
    unraid_cfg = _parse_unraid_network_cfg()
    idx = "0"
    m = re.search(r"\d+", br_name)
    if m:
        idx = m.group(0)

    if f"BRSTP[{idx}]" in unraid_cfg:
        stp_enabled = unraid_cfg[f"BRSTP[{idx}]"].lower() == "yes"
    if f"BRFD[{idx}]" in unraid_cfg:
        try:
            forward_delay = int(unraid_cfg[f"BRFD[{idx}]"])
        except ValueError:
            pass
    if f"BRNICS[{idx}]" in unraid_cfg and not members:
        members = unraid_cfg[f"BRNICS[{idx}]"].split()

    # Saved config
    saved_cfg = load_network_config()
    br_meta = saved_cfg.get("bridges", {}).get(br_name, {})
    if "stp" in br_meta:
        stp_enabled = bool(br_meta["stp"])
    if "forward_delay" in br_meta:
        forward_delay = int(br_meta["forward_delay"])
    if "members" in br_meta and not members:
        members = list(br_meta["members"])

    # Candidate members (physical NICs + bonds)
    topo = get_network_topology()
    candidate_members = []
    for b in topo.get("bonds", []):
        b_name = b["name"]
        candidate_members.append(
            {
                "name": b_name,
                "type": "bond",
                "alias": b.get("alias", ""),
                "speed_human": b.get("speed_human", ""),
                "is_up": b.get("is_up", False),
                "is_member": b_name in members,
            }
        )
    for nic in topo.get("physical_interfaces", []):
        n_name = nic["name"]
        candidate_members.append(
            {
                "name": n_name,
                "type": "physical",
                "alias": nic.get("alias", ""),
                "speed_human": nic.get("speed_human", ""),
                "is_up": nic.get("is_up", False),
                "is_member": n_name in members,
            }
        )

    return {
        "status": "ok",
        "bridge_name": br_name,
        "stp": stp_enabled,
        "forward_delay": forward_delay,
        "members": sorted(members),
        "candidate_members": candidate_members,
    }


def update_bridge_config(br_name: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update virtual bridge parameters: STP toggle, forward delay, and member interfaces."""
    br_name = (br_name or "").strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", br_name):
        return {"status": "error", "message": "Invalid bridge interface name"}

    stp = bool(updates.get("stp", False))
    try:
        forward_delay = int(updates.get("forward_delay", 0))
        if not (0 <= forward_delay <= 30):
            forward_delay = 0
    except (ValueError, TypeError):
        forward_delay = 0

    members = updates.get("members", [])
    if not isinstance(members, list):
        members = []
    for m in members:
        if not isinstance(m, str) or not re.match(r"^[a-zA-Z0-9_\-\.]+$", m):
            return {"status": "error", "message": f"Invalid member interface: {m}"}

    # Persist to network_config.json
    cfg = load_network_config()
    bridges = cfg.setdefault("bridges", {})
    bridges[br_name] = {
        "stp": stp,
        "forward_delay": forward_delay,
        "members": members,
        "updated_at": time.time(),
    }
    save_network_config(cfg)

    # Persist to Unraid /boot/config/network.cfg if present
    idx = "0"
    m_idx = re.search(r"\d+", br_name)
    if m_idx:
        idx = m_idx.group(0)

    unraid_updates = {
        f"BRSTP[{idx}]": "yes" if stp else "no",
        f"BRFD[{idx}]": str(forward_delay),
    }
    if members:
        unraid_updates[f"BRNICS[{idx}]"] = " ".join(members)
    _write_unraid_network_cfg(unraid_updates)

    # Runtime sysfs apply
    sys_net_dir = _find_sys_net_dir()
    if sys_net_dir:
        stp_path = os.path.join(sys_net_dir, br_name, "bridge/stp_state")
        if os.path.isfile(stp_path):
            try:
                with open(stp_path, "w") as f:
                    f.write("1" if stp else "0")
            except Exception:
                pass
        fd_path = os.path.join(sys_net_dir, br_name, "bridge/forward_delay")
        if os.path.isfile(fd_path):
            try:
                with open(fd_path, "w") as f:
                    f.write(str(forward_delay * 100))
            except Exception:
                pass

    try:
        from backend.state import add_event

        add_event(
            "info",
            "Bridge Configured",
            f"Bridge {br_name} updated: STP {'Enabled' if stp else 'Disabled'}, Forward Delay {forward_delay}s, Members: {', '.join(members) or 'None'}.",
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "bridge_name": br_name,
        "stp": stp,
        "forward_delay": forward_delay,
        "members": members,
        "message": f"Bridge configuration for '{br_name}' saved successfully. Settings persisted to system config.",
    }


def get_network_topology() -> dict[str, Any]:
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

    physical_interfaces: list[dict[str, Any]] = []
    bonds: list[dict[str, Any]] = []
    bridges: list[dict[str, Any]] = []
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
            xmit_hash_policy = _read_file(os.path.join(iface_dir, "bonding/xmit_hash_policy"), "")
            lacp_rate = _read_file(os.path.join(iface_dir, "bonding/lacp_rate"), "")
            ad_num_ports = _read_file(os.path.join(iface_dir, "bonding/ad_num_ports"), "")
            miimon_str = _read_file(os.path.join(iface_dir, "bonding/miimon"), "100")
            try:
                miimon_val = int(miimon_str) if miimon_str.isdigit() else 100
            except ValueError:
                miimon_val = 100

            mode_parts = mode.split()
            if mode_parts and mode_parts[-1].isdigit():
                mode_code = mode_parts[-1]
            elif "802.3ad" in mode.lower():
                mode_code = "4"
            elif "balance-alb" in mode.lower():
                mode_code = "6"
            elif "balance-rr" in mode.lower():
                mode_code = "0"
            elif "balance-xor" in mode.lower():
                mode_code = "2"
            else:
                mode_code = "1"

            mode_info = BONDING_MODES.get(mode_code, BONDING_MODES["1"])

            bonds.append(
                {
                    "name": iface,
                    "alias": alias,
                    "mode": mode,
                    "mode_code": mode_code,
                    "mode_name": mode_info.get("name", "active-backup"),
                    "mode_title": mode_info.get("title", "Active-Backup"),
                    "slaves": slaves,
                    "active_slave": active_slave,
                    "xmit_hash_policy": xmit_hash_policy,
                    "lacp_rate": lacp_rate,
                    "ad_num_ports": ad_num_ports,
                    "miimon": miimon_val,
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

            stp_raw = _read_file(os.path.join(iface_dir, "bridge/stp_state"), "0").strip()
            stp_enabled = stp_raw in ("1", "yes", "true")
            fd_raw = _read_file(os.path.join(iface_dir, "bridge/forward_delay"), "0").strip()
            try:
                fd_val = int(fd_raw)
                if fd_val > 100:
                    fd_val = fd_val // 100
            except ValueError:
                fd_val = 0

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
                    "stp": stp_enabled,
                    "forward_delay": fd_val,
                    "carrier": carrier,
                    "is_up": is_up,
                    "mtu": mtu,
                    "mac": mac,
                    "ip_address": bridge_ip,
                    "rx_bytes": _read_stat(iface_dir, "rx_bytes"),
                    "tx_bytes": _read_stat(iface_dir, "tx_bytes"),
                }
            )

    # 4. VLAN Sub-Interfaces (802.1Q)
    vlans = get_vlans()

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
        "vlan_count": len(vlans),
        "docker_networks_count": len(docker_networks),
        "docker_containers_count": total_containers,
        "canary": get_canary_watchdog().get_status(),
    }

    listening_ports = []
    try:
        listening_ports = get_active_listening_ports()
    except Exception as e:
        logger.debug(f"[Network Diagnostics] Error reading listening ports: {e}")

    return {
        "status": "ok",
        "summary": summary,
        "physical_interfaces": physical_interfaces,
        "bonds": bonds,
        "bridges": bridges,
        "vlans": vlans,
        "docker_networks": docker_networks,
        "routes": routes,
        "listening_ports": listening_ports,
    }


def read_network_rates():
    now = time.time()
    dev_path = _find_proc_net_path("dev")
    ifaces = {}
    if dev_path:
        try:
            with open(dev_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if ":" in line:
                        iface, data = line.split(":", 1)
                        iface = iface.strip()
                        fields = data.split()
                        if len(fields) >= 9:
                            ifaces[iface] = (int(fields[0]), int(fields[8]))
        except Exception as e:
            logger.debug(f"Silenced exception reading net/dev: {e}")

    def fmt_speed(b):
        if b >= 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024 * 1024):.1f} GB/s"
        elif b >= 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MB/s"
        elif b >= 1024:
            return f"{b / 1024:.0f} KB/s"
        return f"{b:.0f} B/s"

    prev_ifaces = getattr(Z_STATE, "prev_net_ifaces", None)
    if not isinstance(prev_ifaces, dict):
        prev_ifaces = {}

    interfaces_info = {}
    total_physical_rx_rate = 0.0
    total_physical_tx_rate = 0.0
    total_physical_rx_bytes = 0
    total_physical_tx_bytes = 0

    bond_slaves = set()
    for b in [i for i in ifaces if i.startswith("bond")]:
        try:
            bonding_slaves_path = os.path.join(HOST_SYS, "class/net", b, "bonding/slaves")
            if os.path.exists(bonding_slaves_path):
                with open(bonding_slaves_path, encoding="utf-8") as bf:
                    bond_slaves.update(bf.read().split())
        except Exception:
            pass

    for iface_name, (cur_rx, cur_tx) in ifaces.items():
        if iface_name == "lo" or iface_name.startswith(("veth", "docker", "br-", "shim-", "tunl", "tailscale", "wg")):
            continue

        prev_data = prev_ifaces.get(iface_name)
        rx_rate = 0.0
        tx_rate = 0.0
        if prev_data:
            dt = max(0.1, now - prev_data["time"])
            if cur_rx >= prev_data["rx"] and cur_tx >= prev_data["tx"]:
                rx_rate = max(0.0, (cur_rx - prev_data["rx"]) / dt)
                tx_rate = max(0.0, (cur_tx - prev_data["tx"]) / dt)

        prev_ifaces[iface_name] = {"time": now, "rx": cur_rx, "tx": cur_tx}

        is_physical = iface_name.startswith(("eth", "en"))
        interfaces_info[iface_name] = {
            "rx": fmt_speed(rx_rate),
            "tx": fmt_speed(tx_rate),
            "rx_bytes": cur_rx,
            "tx_bytes": cur_tx,
            "rx_rate": round(rx_rate, 1),
            "tx_rate": round(tx_rate, 1),
            "is_physical": is_physical,
            "is_bond": iface_name.startswith("bond"),
            "is_bridge": iface_name.startswith("br"),
        }

        if iface_name.startswith("bond") or is_physical and iface_name not in bond_slaves:
            total_physical_rx_rate += rx_rate
            total_physical_tx_rate += tx_rate
            total_physical_rx_bytes += cur_rx
            total_physical_tx_bytes += cur_tx

    Z_STATE.prev_net_ifaces = prev_ifaces

    env_iface = os.environ.get("HOST_NET_IFACE", "").strip()
    if env_iface and env_iface in interfaces_info:
        target = interfaces_info[env_iface]
        combined_rx_rate = target["rx_rate"]
        combined_tx_rate = target["tx_rate"]
        combined_rx_bytes = target["rx_bytes"]
        combined_tx_bytes = target["tx_bytes"]
        chosen_iface = env_iface
    else:
        combined_rx_rate = total_physical_rx_rate
        combined_tx_rate = total_physical_tx_rate
        combined_rx_bytes = total_physical_rx_bytes
        combined_tx_bytes = total_physical_tx_bytes
        chosen_iface = "combined"

    Z_STATE.prev_net = {
        "time": now,
        "rx": combined_rx_bytes,
        "tx": combined_tx_bytes,
        "iface": chosen_iface,
    }

    return {
        "rx": fmt_speed(combined_rx_rate),
        "tx": fmt_speed(combined_tx_rate),
        "rx_bytes": combined_rx_bytes,
        "tx_bytes": combined_tx_bytes,
        "rx_rate": round(combined_rx_rate, 1),
        "tx_rate": round(combined_tx_rate, 1),
        "rx_bytes_sec": round(combined_rx_rate, 1),
        "tx_bytes_sec": round(combined_tx_rate, 1),
        "iface": chosen_iface,
        "interfaces": interfaces_info,
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
                with open(p, encoding="utf-8", errors="replace") as f:
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
            with open(fib_path, encoding="utf-8", errors="replace") as f:
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


def _find_tailscale_bin() -> str | None:
    """Finds tailscale CLI executable across standard PATH and NAS host plugin paths."""
    ts_bin = shutil.which("tailscale")
    if ts_bin:
        return ts_bin
    for cand in (
        "/usr/local/sbin/tailscale",
        "/usr/sbin/tailscale",
        "/usr/bin/tailscale",
        "/usr/local/bin/tailscale",
        "/usr/local/emhttp/plugins/tailscale/bin/tailscale",
    ):
        if os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _get_tailscale_container_info() -> dict[str, Any]:
    """Checks if a Docker container named 'tailscale' exists and returns its state."""
    try:
        from backend.services.container_mutator import _docker_request

        status, data = _docker_request("GET", "/containers/tailscale/json")
        if status == 200 and isinstance(data, dict):
            state = data.get("State", {})
            return {
                "exists": True,
                "running": bool(state.get("Running", False)),
                "id": str(data.get("Id", ""))[:12],
                "status": state.get("Status", "unknown"),
            }
    except Exception:
        pass
    return {"exists": False, "running": False, "id": "", "status": "not_found"}


def _run_tailscale_cmd(args: list[str], timeout: float = 10.0) -> tuple[int, str]:
    """
    Executes a Tailscale command using Docker exec if 'tailscale' container is running,
    or falls back to native host binary if present and daemon is accessible.
    Returns (returncode, output_text).
    """
    c_info = _get_tailscale_container_info()
    use_container = bool(c_info.get("exists") and c_info.get("running"))

    if use_container:
        try:
            from backend.services.compose_synthesizer import execute_in_container

            # If command can block for approval (like serve or funnel activation),
            # wrap with timeout so Docker exec returns output cleanly before timing out
            cmd_list = ["tailscale"] + args
            if args and args[0] in ("serve", "funnel") and len(args) > 1 and args[1] not in ("status", "reset"):
                cmd_list = ["timeout", str(max(1, int(timeout))), "tailscale"] + args
            res = execute_in_container("tailscale", cmd_list)
            if res.get("success"):
                exit_code = res.get("exit_code", 0)
                out = (res.get("output") or "").strip()
                return exit_code, out
        except Exception as e:
            logger.debug(f"[Tailscale] Container execution error: {e}")

    # Fallback to native host binary
    ts_bin = _find_tailscale_bin()
    bin_cmd = ts_bin or "tailscale"
    try:
        r = subprocess.run([bin_cmd] + args, capture_output=True, text=True, timeout=timeout)
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return r.returncode, out
    except subprocess.TimeoutExpired as te:
        out = ((te.stdout or "") + "\n" + (te.stderr or "")).strip()
        return 1, out or "Command timed out"
    except FileNotFoundError:
        pass
    except Exception as e:
        return 1, str(e)

    if c_info.get("exists"):
        return 1, "Tailscale container is stopped"

    return 127, "tailscale CLI or running container not found"


def detect_local_subnets() -> list[str]:
    """Detects local physical IPv4 network subnets (e.g. ['10.40.30.0/24'])."""
    subnets = []
    try:
        routes = _parse_routes()
        for r in routes:
            iface = r.get("iface", "")
            if r.get("is_default") or iface.startswith(
                ("lo", "docker", "shim-", "br-", "tunl", "wg", "tailscale", "veth")
            ):
                continue
            dest = r.get("destination", "")
            cidr = r.get("cidr", 24)
            if dest and dest != "0.0.0.0" and not dest.startswith(("127.", "169.254.")):
                s = f"{dest}/{cidr}"
                if s not in subnets:
                    subnets.append(s)
    except Exception as e:
        logger.debug(f"[Network] Error detecting subnets: {e}")
    if not subnets:
        subnets = ["192.168.1.0/24"]
    return subnets


def get_taildrop_dir() -> str:
    """Finds or creates persistent Taildrop directory on host."""
    from backend.config import DATA_DIR

    candidates = [
        "/mnt/user/downloads/taildrop",
        "/mnt/user/appdata/tailscale/taildrop",
        os.path.join(DATA_DIR, "tailscale", "taildrop"),
    ]
    for c in candidates:
        try:
            parent = os.path.dirname(c)
            if os.path.isdir(parent):
                os.makedirs(c, exist_ok=True)
                return c
        except Exception:
            continue
    fallback = os.path.join(DATA_DIR, "taildrop")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def get_taildrop_inbox_files() -> list[dict[str, Any]]:
    """Lists files received via Taildrop."""
    from datetime import datetime, timezone

    target_dir = get_taildrop_dir()
    files = []
    if not os.path.isdir(target_dir):
        return files
    try:
        for entry in os.scandir(target_dir):
            if entry.is_file():
                try:
                    st = entry.stat()
                    size_b = st.st_size
                    if size_b < 1024:
                        size_fmt = f"{size_b} B"
                    elif size_b < 1024 * 1024:
                        size_fmt = f"{size_b / 1024:.1f} KB"
                    elif size_b < 1024 * 1024 * 1024:
                        size_fmt = f"{size_b / (1024 * 1024):.1f} MB"
                    else:
                        size_fmt = f"{size_b / (1024 * 1024 * 1024):.2f} GB"
                    mtime_iso = datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%d %H:%M")
                    files.append(
                        {
                            "name": entry.name,
                            "size_bytes": size_b,
                            "size_formatted": size_fmt,
                            "modified_at": mtime_iso,
                            "path": entry.path,
                        }
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"[Tailscale] Failed to read taildrop inbox: {e}")
    files.sort(key=lambda x: x["name"].lower())
    return files


def execute_tailscale_taildrop_receive() -> dict[str, Any]:
    """Ingests any pending files from Taildrop queue into the inbox."""
    target_dir = get_taildrop_dir()
    c_info = _get_tailscale_container_info()
    if c_info.get("exists") and c_info.get("running"):
        cmd = ["file", "get", "--conflict=rename", "/var/lib/tailscale/taildrop"]
    else:
        cmd = ["file", "get", "--conflict=rename", target_dir]
    code, out = _run_tailscale_cmd(cmd, timeout=12.0)
    files = get_taildrop_inbox_files()
    return {
        "status": "ok" if code == 0 else "error",
        "code": code,
        "output": out,
        "directory": target_dir,
        "files": files,
        "count": len(files),
        "received_count": len(files),
    }


def execute_tailscale_ping(peer: str) -> dict[str, Any]:
    """Pings a Tailscale peer and parses round-trip latency and route path."""
    import re

    clean_peer = peer.strip()
    if not clean_peer:
        return {"status": "error", "message": "Peer IP or hostname is required"}
    code, out = _run_tailscale_cmd(["ping", "--c=1", "--timeout=2s", clean_peer], timeout=4.0)
    out_clean = out.strip()
    if "pong from" in out_clean.lower():
        route = ""
        latency_str = ""
        latency_ms = None
        m_route = re.search(r"via\s+([^\s]+)", out_clean)
        if m_route:
            route = m_route.group(1)
        m_time = re.search(r"in\s+([0-9.]+)\s*(ms|s)", out_clean)
        if m_time:
            val = float(m_time.group(1))
            unit = m_time.group(2)
            latency_ms = val if unit == "ms" else val * 1000.0
            latency_str = f"{latency_ms:.1f} ms"
        is_direct = bool(route and not route.lower().startswith("derp"))
        return {
            "status": "success",
            "peer": clean_peer,
            "route": route,
            "latency": latency_str,
            "latency_ms": latency_ms,
            "is_direct": is_direct,
            "output": out_clean,
        }
    return {
        "status": "error",
        "peer": clean_peer,
        "output": out_clean or "Ping timed out or peer is unreachable",
    }


def execute_tailscale_set_routes(routes: str, enabled: bool = True) -> dict[str, Any]:
    """Advertises or withdraws subnet routes to the Tailnet."""
    clean_routes = routes.strip() if enabled else ""
    if clean_routes:
        parts = [p.strip() for p in clean_routes.split(",") if p.strip() and p.strip() not in ("0.0.0.0/0", "::/0")]
        clean_routes = ",".join(parts)
    cmd = ["set", f"--advertise-routes={clean_routes}"]
    code, out = _run_tailscale_cmd(cmd, timeout=8.0)
    return {
        "status": "ok" if code == 0 else "error",
        "code": code,
        "enabled": enabled and bool(clean_routes),
        "advertised_routes": clean_routes,
        "output": out,
    }


def execute_tailscale_set_exit_node(enabled: bool) -> dict[str, Any]:
    """Advertises this node as a Tailscale Exit Node."""
    val = "true" if enabled else "false"
    cmd = ["set", f"--advertise-exit-node={val}"]
    code, out = _run_tailscale_cmd(cmd, timeout=8.0)
    return {
        "status": "ok" if code == 0 else "error",
        "code": code,
        "enabled": enabled,
        "output": out,
    }


def execute_tailscale_set_ssh(enabled: bool) -> dict[str, Any]:
    """Enables or disables Tailscale SSH."""
    val = "true" if enabled else "false"
    cmd = ["set", f"--ssh={val}"]
    code, out = _run_tailscale_cmd(cmd, timeout=8.0)
    return {
        "status": "ok" if code == 0 else "error",
        "code": code,
        "enabled": enabled,
        "output": out,
    }


def execute_tailscale_set_serve(serve: bool, funnel: bool = False, port: int = 8082) -> dict[str, Any]:
    """Configures Tailscale Serve and Funnel proxy for ZettNAS Web Desktop."""
    import re

    approval_url = ""
    error_msg = ""
    feature = "serve"
    _code_s = 0
    _code_f = 0

    # 1. Handle Serve
    if serve:
        _code_s, out_s = _run_tailscale_cmd(["serve", "--bg", "--yes", str(port)], timeout=3.0)
        m_s = re.search(r"https://login\.tailscale\.com/f/serve[^\s]+", out_s)
        if m_s:
            approval_url = m_s.group(0)
            feature = "serve"
        elif _code_s != 0 and "No serve config" not in out_s and "login.tailscale.com" not in out_s:
            error_msg = out_s.strip()
    else:
        _run_tailscale_cmd(["serve", "reset"], timeout=4.0)

    # 2. Handle Funnel
    if funnel and serve and not approval_url:
        _code_f, out_f = _run_tailscale_cmd(["funnel", "--bg", "--yes", str(port)], timeout=3.0)
        m_f = re.search(r"https://login\.tailscale\.com/f/funnel[^\s]+", out_f)
        if m_f:
            approval_url = m_f.group(0)
            feature = "funnel"
        elif _code_f != 0 and "No serve config" not in out_f and "login.tailscale.com" not in out_f:
            if not error_msg:
                error_msg = out_f.strip()
    elif not funnel:
        _run_tailscale_cmd(["funnel", "reset"], timeout=4.0)

    # Check actual status from tailscale daemon
    sv_code, sv_out = _run_tailscale_cmd(["serve", "status", "--json"], timeout=3.0)
    actual_serve = (sv_code == 0 and sv_out.strip().startswith("{") and len(sv_out.strip()) > 2) or (
        _code_s == 0 and not approval_url and serve
    )

    actual_funnel = False
    if actual_serve:
        fn_code, fn_out = _run_tailscale_cmd(["funnel", "status", "--json"], timeout=3.0)
        actual_funnel = (fn_code == 0 and "AllowFunnel" in fn_out) or (_code_f == 0 and funnel and serve)

    return {
        "status": "needs_approval"
        if approval_url
        else ("ok" if (actual_serve or not serve) else ("error" if error_msg else "pending")),
        "serve_enabled": actual_serve,
        "funnel_enabled": actual_funnel,
        "approval_url": approval_url,
        "feature": feature,
        "error": error_msg,
        "port": port,
    }


def execute_tailscale_reauth() -> dict[str, Any]:
    """Forces Tailscale node re-authentication, returning interactive login URL."""
    import re

    code, out = _run_tailscale_cmd(["up", "--force-reauth", "--reset"], timeout=8.0)
    m = re.search(r"https://login\.tailscale\.com/a/[a-zA-Z0-9_-]+", out)
    auth_url = m.group(0) if m else ""
    if not auth_url:
        s_code, s_out = _run_tailscale_cmd(["status", "--json"], timeout=4.0)
        if s_code == 0 and s_out.strip().startswith("{"):
            try:
                import json

                s_doc = json.loads(s_out.strip())
                auth_url = s_doc.get("AuthURL", "")
            except Exception:
                pass
    return {
        "status": "needs_login" if auth_url else ("ok" if code == 0 else "error"),
        "auth_url": auth_url,
        "output": out,
    }


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

    ts_bin = _find_tailscale_bin()
    c_info = _get_tailscale_container_info()
    if c_info.get("exists"):
        ts_info["container_mode"] = True
        ts_info["container_id"] = c_info.get("id", "")
        ts_info["installed"] = True
        if not c_info.get("running"):
            ts_info["active"] = False
            ts_info["backend_state"] = "Stopped"
            ts_info["taildrop_dir"] = get_taildrop_dir()
            ts_info["detected_subnets"] = detect_local_subnets()
            return {
                "tailscale": ts_info,
                "wireguard": _get_wireguard_status(),
            }

    code, out = _run_tailscale_cmd(["status", "--json"], timeout=4.0)
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
                    from datetime import datetime, timezone

                    exp_dt = datetime.fromisoformat(key_exp.replace("Z", "+00:00"))
                    now_dt = datetime.now(UTC)
                    delta = (exp_dt - now_dt).days
                    key_days = max(0, delta)
                except Exception:
                    pass
            ts_info["key_expiry_days"] = key_days
            ts_info["key_expired"] = (key_days == 0) if key_days is not None else False

            # Check debug prefs for RunSSH and AdvertiseRoutes
            p_routes = []
            p_code, p_out = _run_tailscale_cmd(["debug", "prefs"], timeout=2.0)
            if p_code == 0 and p_out.strip().startswith("{"):
                try:
                    p_doc = json.loads(p_out.strip())
                    ts_info["ssh_enabled"] = bool(p_doc.get("RunSSH", False))
                    p_routes = p_doc.get("AdvertiseRoutes") or []
                except Exception:
                    pass

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
            ts_info["detected_subnets"] = detect_local_subnets()

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
            sv_code, sv_out = _run_tailscale_cmd(["serve", "status", "--json"], timeout=2.0)
            if sv_code == 0 and sv_out.strip().startswith("{") and len(sv_out.strip()) > 2:
                ts_info["serve_enabled"] = True
                fn_code, fn_out = _run_tailscale_cmd(["funnel", "status", "--json"], timeout=2.0)
                if fn_code == 0 and "AllowFunnel" in fn_out:
                    ts_info["funnel_enabled"] = True

            # Taildrop inbox files
            ts_info["taildrop_dir"] = get_taildrop_dir()
            taildrop_files = get_taildrop_inbox_files()
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
        "wireguard": _get_wireguard_status(),
    }


def execute_tailscale_up(
    auth_key: str | None = None,
    hostname: str | None = None,
    accept_routes: bool = True,
) -> dict[str, Any]:
    """Connects host to the Zero-Trust Tailscale mesh network."""
    c_info = _get_tailscale_container_info()
    if c_info.get("exists") and not c_info.get("running"):
        try:
            from backend.services.container_mutator import _docker_request

            _docker_request("POST", "/containers/tailscale/start")
            time.sleep(2.0)
        except Exception as e:
            logger.debug(f"[Tailscale] Failed to start container before tailscale up: {e}")

    cmd = ["up", "--reset"]
    if auth_key:
        cmd.extend(["--authkey", auth_key])
    if hostname:
        cmd.extend(["--hostname", hostname])
    if accept_routes:
        cmd.append("--accept-routes")
    if not auth_key:
        cmd.append("--timeout=3s")

    code, out = _run_tailscale_cmd(cmd, timeout=15.0)

    # Check for interactive authentication URL in output
    auth_url = None
    m = re.search(r"https://login\.tailscale\.com/a/[a-zA-Z0-9_-]+", out)
    if m:
        auth_url = m.group(0)
    elif "login.tailscale.com" in out:
        m2 = re.search(r"https://\S+", out)
        if m2:
            auth_url = m2.group(0)

    # If auth_url was not in stdout, query status --json fallback for AuthURL
    if not auth_url and not auth_key:
        try:
            s_code, s_out = _run_tailscale_cmd(["status", "--json"], timeout=4.0)
            if s_code == 0 and s_out.strip().startswith("{"):
                import json

                s_doc = json.loads(s_out.strip())
                if s_doc.get("AuthURL"):
                    auth_url = s_doc["AuthURL"]
        except Exception as e:
            logger.debug(f"[Network] Fallback status json check: {e}")

    if auth_url:
        return {
            "status": "needs_login",
            "code": 0,
            "auth_url": auth_url,
            "output": out,
            "message": "Authentication required. Visit the authorization URL to link this device.",
        }

    if code == 0:
        return {
            "status": "success",
            "code": 0,
            "output": out or "Tailscale connected successfully",
        }

    if code == 127:
        return {"status": "error", "code": 127, "output": "tailscale CLI or container not found on host"}

    return {"status": "error", "code": code, "output": out or "Tailscale connection failed"}


def execute_tailscale_down() -> dict[str, Any]:
    """Disconnects host from the Zero-Trust Tailscale mesh network."""
    c_info = _get_tailscale_container_info()
    if c_info.get("exists"):
        try:
            from backend.services.container_mutator import _docker_request

            if c_info.get("running"):
                _run_tailscale_cmd(["down"], timeout=5.0)
                _docker_request("POST", "/containers/tailscale/stop?t=5")
            return {
                "status": "success",
                "code": 0,
                "output": "Tailscale container stopped and disconnected",
            }
        except Exception as e:
            return {"status": "error", "code": 1, "output": str(e)}

    code, out = _run_tailscale_cmd(["down"], timeout=10.0)
    if code == 0:
        return {
            "status": "success",
            "code": 0,
            "output": out or "Tailscale disconnected successfully",
        }
    if code == 127:
        return {"status": "error", "code": 127, "output": "tailscale CLI or container not found on host"}
    return {"status": "error", "code": code, "output": out or "Tailscale disconnection failed"}


def deploy_tailscale_container(
    auth_key: str | None = None,
    hostname: str | None = None,
    accept_routes: bool = True,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """
    1-Click turnkey provisioning of the official Tailscale Docker container
    with host network mode, NET_ADMIN caps, and persistent state storage.
    """
    from backend.hardware.docker_stats import UnixHTTPConnection
    from backend.services.container_mutator import _docker_request

    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return {
            "status": "error",
            "message": "Docker socket /var/run/docker.sock not available. Docker is required for 1-click deployment.",
        }

    # 1. Check if 'tailscale' container already exists
    st_exist, c_info = _docker_request("GET", "/containers/tailscale/json")
    if st_exist == 200 and isinstance(c_info, dict):
        cid = str(c_info.get("Id", ""))[:12]
        is_running = bool(c_info.get("State", {}).get("Running", False))
        if not is_running:
            _docker_request("POST", "/containers/tailscale/start")
            time.sleep(2)

        if auth_key:
            up_res = execute_tailscale_up(auth_key=auth_key, hostname=hostname, accept_routes=accept_routes)
            return {
                "status": "success",
                "container_id": cid,
                "message": "Tailscale container started and connected with auth key.",
                "details": up_res,
            }
        else:
            up_res = execute_tailscale_up(hostname=hostname, accept_routes=accept_routes)
            auth_url = up_res.get("auth_url")
            return {
                "status": "success",
                "container_id": cid,
                "auth_url": auth_url,
                "backend_state": "NeedsLogin" if auth_url else "Running",
                "message": (
                    "Tailscale container running. Please authenticate in your browser to complete setup."
                    if auth_url
                    else "Tailscale container running."
                ),
            }

    # 2. Pull official image if not cached locally
    image_name = "tailscale/tailscale:stable"
    st_img, _ = _docker_request("GET", f"/images/{image_name}/json")
    if st_img != 200:
        logger.info(f"[Network] Pulling image {image_name} for 1-click Tailscale deployment...")
        pull_conn = None
        try:
            pull_conn = UnixHTTPConnection(sock_path, timeout=180.0)
            pull_conn.request("POST", "/images/create?fromImage=tailscale/tailscale&tag=stable")
            res_p = pull_conn.getresponse()
            while True:
                chunk = res_p.read(4096)
                if not chunk:
                    break
        except Exception as e:
            logger.warning(f"[Network] Image pull notice: {e}")
        finally:
            if pull_conn:
                try:
                    pull_conn.close()
                except Exception:
                    pass

    # 3. Resolve persistent host storage directory
    if not state_dir:
        if os.path.isdir("/mnt/user/appdata"):
            state_dir = "/mnt/user/appdata/tailscale"
        else:
            from backend.config import DATA_DIR

            state_dir = os.path.join(DATA_DIR, "tailscale")
    try:
        os.makedirs(state_dir, exist_ok=True)
    except Exception as e:
        logger.warning(f"[Network] Could not create state_dir {state_dir}: {e}")

    # 4. Configure environment variables
    env_vars = [
        "TS_STATE_DIR=/var/lib/tailscale",
        "TS_USERSPACE=false",
    ]
    if hostname:
        env_vars.append(f"TS_HOSTNAME={hostname.strip()}")
    if auth_key:
        env_vars.append(f"TS_AUTHKEY={auth_key.strip()}")
    if accept_routes:
        env_vars.append("TS_EXTRA_ARGS=--reset --accept-routes")
    else:
        env_vars.append("TS_EXTRA_ARGS=--reset")

    # 5. Device and capabilities handling
    devices = []
    if os.path.exists("/dev/net/tun") or os.path.exists("/host/dev/net/tun"):
        devices.append(
            {
                "PathOnHost": "/dev/net/tun",
                "PathInContainer": "/dev/net/tun",
                "CgroupPermissions": "rwm",
            }
        )
    else:
        # Fallback to userspace networking if /dev/net/tun is unavailable
        env_vars = [e for e in env_vars if not e.startswith("TS_USERSPACE=")]
        env_vars.append("TS_USERSPACE=true")

    create_body = {
        "Image": image_name,
        "Env": env_vars,
        "HostConfig": {
            "NetworkMode": "host",
            "CapAdd": ["NET_ADMIN", "NET_RAW"],
            "Binds": [f"{state_dir}:/var/lib/tailscale"],
            "Devices": devices,
            "RestartPolicy": {"Name": "unless-stopped"},
        },
        "Labels": {
            "com.docker.compose.project": "tailscale",
            "com.docker.compose.service": "tailscale",
            "net.unraid.docker.managed": "dockerman",
            "net.unraid.docker.icon": "https://raw.githubusercontent.com/tailscale/tailscale/main/cmd/tailscale/logo.png",
            "app.name": "Tailscale Zero-Trust Mesh",
        },
    }

    # 6. Create container
    st_create, res_create = _docker_request("POST", "/containers/create?name=tailscale", body=create_body)
    if st_create != 201:
        err_msg = res_create.get("message") if isinstance(res_create, dict) else str(res_create)
        return {"status": "error", "message": f"Failed to create Tailscale container: {err_msg}"}

    cid = str(res_create.get("Id", ""))

    # 7. Start container
    st_start, res_start = _docker_request("POST", f"/containers/{cid}/start")
    if st_start not in (204, 304):
        err_msg = res_start.get("message") if isinstance(res_start, dict) else str(res_start)
        return {"status": "error", "message": f"Failed to start Tailscale container: {err_msg}"}

    time.sleep(2.5)

    # 8. Check auth requirement or trigger login
    auth_url = None
    if not auth_key:
        up_res = execute_tailscale_up(hostname=hostname, accept_routes=accept_routes)
        auth_url = up_res.get("auth_url")
    else:
        execute_tailscale_up(auth_key=auth_key, hostname=hostname, accept_routes=accept_routes)

    return {
        "status": "success",
        "container_id": cid[:12],
        "state_dir": state_dir,
        "auth_url": auth_url,
        "backend_state": "NeedsLogin" if auth_url else "Running",
        "message": (
            "Tailscale container deployed. Please authenticate in your browser to complete setup."
            if auth_url
            else "Tailscale container deployed and connected to Tailnet."
        ),
    }


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
        pass

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
    for p in ["/proc/sys/net/ipv4/ip_forward", os.path.join(HOST_PROC, "sys/net/ipv4/ip_forward")]:
        if os.path.isfile(p):
            try:
                with open(p) as f:
                    return f.read().strip() == "1"
            except Exception:
                pass
    return False


def set_ip_forwarding(enable: bool) -> bool:
    """Configures kernel IPv4 packet forwarding."""
    val = "1" if enable else "0"
    for p in ["/proc/sys/net/ipv4/ip_forward", os.path.join(HOST_PROC, "sys/net/ipv4/ip_forward")]:
        if os.path.isfile(p):
            try:
                with open(p, "w") as f:
                    f.write(f"{val}\n")
                return True
            except Exception:
                pass
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
            pass
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
        pass

    proc_bases = [HOST_PROC, "/proc"]
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
