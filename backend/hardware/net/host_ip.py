"""The host IP settings: what they are now, and changing them under the canary (validation, apply, confirm, revert).

Part of backend/hardware/network.py, split out by ARC-5."""

import ipaddress
import re
import time
from typing import Any

from backend.config import logger
from backend.hardware.net import canary, common, topology


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
    unraid_cfg = canary._parse_unraid_network_cfg()
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

    canary_status = canary.get_canary_watchdog().get_status()

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
                "cidr": common._mask_to_cidr(netmask),
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
    canary_id = canary.get_canary_watchdog().arm(target_cfg, original_cfg, timeout_sec=timeout_sec)

    # Stage in network_config.json
    cfg = common.load_network_config()
    cfg["host_ip_staged"] = {
        "canary_id": canary_id,
        "target": target_cfg,
        "original": original_cfg,
        "deadline": time.time() + timeout_sec,
    }
    common.save_network_config(cfg)

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
        canary._write_unraid_network_cfg(unraid_updates)

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
        logger.debug("backend.hardware.network.apply_host_ip_config_canary: ignored error", exc_info=True)

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
    watchdog = canary.get_canary_watchdog()
    if not watchdog.is_active:
        return {"status": "ok", "message": "No active canary test to confirm"}

    target_cfg = dict(watchdog.target_config)
    success = watchdog.confirm(canary_id=canary_id)
    if not success:
        return {"status": "error", "message": "Invalid or expired canary ID"}

    # Commit permanently in network_config.json
    cfg = common.load_network_config()
    cfg["host_ip_config"] = target_cfg
    cfg.pop("host_ip_staged", None)
    common.save_network_config(cfg)

    # Add audit log
    try:
        from backend.state import add_event

        add_event(
            "success",
            "Network Confirmed",
            f"Host network settings confirmed permanently: {target_cfg.get('mode', 'static').upper()} {target_cfg.get('ip_address', '')}",
        )
    except Exception:
        logger.debug("backend.hardware.network.confirm_host_ip_config: ignored error", exc_info=True)

    return {
        "status": "confirmed",
        "config": target_cfg,
        "message": "Host network configuration successfully committed.",
    }


def revert_host_ip_config(canary_id: str | None = None) -> dict[str, Any]:
    """Manually aborts canary test and immediately restores original network settings."""
    watchdog = canary.get_canary_watchdog()
    if not watchdog.is_active:
        return {"status": "error", "message": "No active canary test to revert"}

    orig = watchdog.revert(canary_id=canary_id)
    if not orig:
        return {"status": "error", "message": "Invalid or expired canary ID"}

    canary._execute_revert(orig)

    try:
        from backend.state import add_event

        add_event(
            "warning",
            "Network Reverted",
            f"Host network configuration manually reverted to {orig.get('ip_address', 'original')}.",
        )
    except Exception:
        logger.debug("backend.hardware.network.revert_host_ip_config: ignored error", exc_info=True)

    return {
        "status": "reverted",
        "restored_ip": orig.get("ip_address"),
        "message": "Host network configuration reverted to previous state.",
    }
