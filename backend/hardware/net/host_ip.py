"""The host IP settings: what they are now, and changing them under the canary (validation, apply, confirm, revert).

Part of backend/hardware/network.py, split out by ARC-5."""

import ipaddress
from typing import Any

from backend.hardware.net import common, topology
from backend.hardware.net import unraid_cfg as unraid_file


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
    topo = topology.get_network_topology()
    summary = topo.get("summary", {})
    routes = topo.get("routes", [])

    phys_names = [p["name"] for p in topo.get("physical_interfaces", [])]
    br_names = [b["name"] for b in topo.get("bridges", [])]
    bond_names = [b["name"] for b in topo.get("bonds", [])]
    available_ifaces = list(dict.fromkeys(br_names + bond_names + phys_names)) or ["eth0"]

    primary_iface = summary.get("primary_interface") or available_ifaces[0]
    unraid_cfg = unraid_file._parse_unraid_network_cfg()
    saved_cfg = common.load_network_config()
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
        persisted_host.get("ip_address")
        or unraid_cfg.get("IPADDR[0]")
        or summary.get("primary_ip")
        or topology.read_ip()
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
    cidr = common._mask_to_cidr(netmask)

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
    }
