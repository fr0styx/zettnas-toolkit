"""VLAN sub-interfaces: list, create, delete.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import re
import subprocess
import time
from typing import Any

from backend.config import logger
from backend.hardware.net import common
from backend.ignored_errors import ignored


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


# A Linux interface name: at most 15 characters, and no leading dash (it would read as an option)
_IFNAME = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-\.]{0,14}$")


def create_vlan(parent: str, vlan_id: int, alias: str = "") -> dict[str, Any]:
    """Create an 802.1Q VLAN sub-interface (e.g. eth0.10) and persist metadata."""
    parent = (parent or "").strip()
    if not _IFNAME.match(parent):
        return {"status": "error", "message": "Invalid parent interface name"}

    try:
        vid = int(vlan_id)
        if not (1 <= vid <= 4094):
            return {"status": "error", "message": "VLAN ID must be an integer between 1 and 4094"}
    except (ValueError, TypeError):
        return {"status": "error", "message": "VLAN ID must be an integer between 1 and 4094"}

    vname = f"{parent}.{vid}"
    if len(vname) > 15:  # it would never apply, not even after a restart
        return {
            "status": "error",
            "message": f"'{vname}' is longer than the 15 characters Linux allows for an interface name.",
        }

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
    cfg = common.load_network_config()
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
    common.save_network_config(cfg)

    try:
        from backend.state import add_event

        add_event(
            "success",
            "VLAN Created",
            f"802.1Q VLAN sub-interface {vname} (Tag ID: {vid}) created on {parent}.",
        )
    except Exception:
        ignored("backend.hardware.network.create_vlan")

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


def _ip_link_delete(name: str) -> tuple[bool, str]:
    """Runs "ip link del" here, then in the host's network namespace if that failed."""
    cmd = ["ip", "link", "del", "dev", name]
    err_msg = ""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return True, ""
        err_msg = res.stderr.strip()
    except Exception as e:
        err_msg = str(e)
    if os.path.exists("/host/proc/1/ns/net"):
        try:
            res = subprocess.run(
                ["nsenter", "--net=/host/proc/1/ns/net"] + cmd, capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                return True, ""
            err_msg = res.stderr.strip()
        except Exception as e:
            err_msg = str(e)
    return False, err_msg


def delete_vlan(vlan_name: str) -> dict[str, Any]:
    """Delete an 802.1Q VLAN sub-interface."""
    vlan_name = (vlan_name or "").strip()
    if not _IFNAME.match(vlan_name) or not re.search(r"\.\d{1,4}$", vlan_name):
        return {"status": "error", "message": "Invalid VLAN interface name"}
    # Only VLANs: "ip link del" would just as well remove br0 or bond0 and cut the NAS off the network
    in_kernel = vlan_name in _parse_proc_net_vlan()
    in_config = vlan_name in (common.load_network_config().get("vlans") or {})
    if not in_kernel and not in_config:
        return {
            "status": "error",
            "message": f"'{vlan_name}' is not a VLAN; only VLAN sub-interfaces can be removed here.",
        }

    # a VLAN that is only in the saved settings just leaves them
    success, err_msg = _ip_link_delete(vlan_name) if in_kernel else (True, "")
    if not success:
        return {"status": "error", "message": f"Could not remove '{vlan_name}': {err_msg or 'unknown error'}"}

    # Remove from network_config.json
    cfg = common.load_network_config()
    if "vlans" in cfg and vlan_name in cfg["vlans"]:
        cfg["vlans"].pop(vlan_name, None)
    if "aliases" in cfg and vlan_name in cfg["aliases"]:
        cfg["aliases"].pop(vlan_name, None)
    common.save_network_config(cfg)

    try:
        from backend.state import add_event

        add_event(
            "warning",
            "VLAN Deleted",
            f"802.1Q VLAN sub-interface {vlan_name} removed.",
        )
    except Exception:
        ignored("backend.hardware.network.delete_vlan")

    return {
        "status": "ok",
        "name": vlan_name,
        "message": f"VLAN sub-interface '{vlan_name}' removed successfully.",
    }
