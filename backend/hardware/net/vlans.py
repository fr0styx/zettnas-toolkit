"""VLAN sub-interfaces: list, create, delete.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import re
from typing import Any

from backend.config import logger
from backend.hardware.net import common


def _parse_proc_net_vlan() -> dict[str, dict[str, Any]]:
    """Parse /proc/net/vlan/config for active 802.1Q VLAN devices."""
    vlan_map: dict[str, dict[str, Any]] = {}
    vlan_file = common._find_proc_net_path("vlan/config")
    if not vlan_file:
        for p in [
            "/proc/net/vlan/config",
            "/proc/1/net/vlan/config",
            os.path.join(common.HOST_PROC, "net/vlan/config"),
            os.path.join(common.HOST_PROC, "1/net/vlan/config"),
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
    sys_net_dir = common._find_sys_net_dir()
    routes = common._parse_routes()
    saved_cfg = common.load_network_config()
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
                uevent = common._read_file(os.path.join(iface_dir, "uevent"), "")
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

                # 4. Match parent from lower_* symlink only if already confirmed as VLAN
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
                    operstate = common._read_file(os.path.join(iface_dir, "operstate"), "unknown").lower()
                    carrier_str = common._read_file(os.path.join(iface_dir, "carrier"), "0")
                    carrier = 1 if carrier_str == "1" else 0
                    is_up = operstate == "up" and carrier == 1

                    raw_speed = common._read_file(os.path.join(iface_dir, "speed"), "-1")
                    try:
                        speed_val = int(raw_speed) if raw_speed and raw_speed.lstrip("-").isdigit() else -1
                        if speed_val < 0:
                            speed_val = None
                    except ValueError:
                        speed_val = None

                    mtu = int(common._read_file(os.path.join(iface_dir, "mtu"), "1500") or 1500)
                    mac = common._read_file(os.path.join(iface_dir, "address"), "").lower()

                    vlan_ip = ""
                    for r in routes:
                        if r.get("iface") == iface and r.get("destination") != "0.0.0.0":
                            vlan_ip = f"{r.get('destination')}/{r.get('cidr')}"
                            break

                    alias = saved_cfg.get("aliases", {}).get(iface, "")

                    vlans.append(
                        {
                            "name": iface,
                            "parent": parent,
                            "vlan_id": vlan_id,
                            "alias": alias,
                            "carrier": carrier,
                            "is_up": is_up,
                            "speed_human": common._format_speed(speed_val, is_up),
                            "mtu": mtu,
                            "mac": mac,
                            "ip_address": vlan_ip,
                            "rx_bytes": common._read_stat(iface_dir, "rx_bytes"),
                            "tx_bytes": common._read_stat(iface_dir, "tx_bytes"),
                        }
                    )
        except Exception as e:
            logger.debug(f"Error enumerating VLAN interfaces: {e}")

    return sorted(vlans, key=lambda v: (v.get("parent", ""), v.get("vlan_id", 0)))


# A Linux interface name: at most 15 characters, and no leading dash (it would read as an option)
_IFNAME = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-\.]{0,14}$")
