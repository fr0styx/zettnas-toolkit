"""Bonds and bridges: their settings and changes.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import re
import time
from typing import Any

from backend.config import logger
from backend.hardware.net import canary, common, topology
from backend.ignored_errors import ignored


def get_bond_config(bond_name: str) -> dict[str, Any]:
    """Retrieve configuration, operational mode, slaves, and candidate NICs for a bond."""
    bond_name = (bond_name or "").strip()
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", bond_name):
        return {"status": "error", "message": "Invalid bond interface name"}

    sys_net_dir = common._find_sys_net_dir()
    bond_dir = os.path.join(sys_net_dir, bond_name) if sys_net_dir else f"/sys/class/net/{bond_name}"

    mode_str = common._read_file(os.path.join(bond_dir, "bonding/mode"), "")
    slaves = common._read_file(os.path.join(bond_dir, "bonding/slaves"), "").split()
    active_slave = common._read_file(os.path.join(bond_dir, "bonding/active_slave"), "")
    miimon_str = common._read_file(os.path.join(bond_dir, "bonding/miimon"), "100")
    try:
        miimon = int(miimon_str) if miimon_str.isdigit() else 100
    except ValueError:
        miimon = 100

    # Check Unraid config
    unraid_cfg = canary._parse_unraid_network_cfg()
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
    saved_cfg = common.load_network_config()
    bond_meta = saved_cfg.get("bonds", {}).get(bond_name, {})
    if "mode" in bond_meta:
        mode_code = str(bond_meta["mode"])
    if "slaves" in bond_meta and not slaves:
        slaves = list(bond_meta["slaves"])
    if "miimon" in bond_meta:
        miimon = int(bond_meta["miimon"])

    mode_info = common.BONDING_MODES.get(mode_code, common.BONDING_MODES["1"])

    # Candidate slave NICs
    topo = topology.get_network_topology()
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
            for k, v in common.BONDING_MODES.items()
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
    cfg = common.load_network_config()
    bonds = cfg.setdefault("bonds", {})
    bonds[bond_name] = {
        "mode": mode_code,
        "slaves": slaves,
        "miimon": miimon,
        "updated_at": time.time(),
    }
    common.save_network_config(cfg)

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
    canary._write_unraid_network_cfg(unraid_updates)

    # Runtime sysfs tuning for miimon
    sys_net_dir = common._find_sys_net_dir()
    if sys_net_dir:
        miimon_path = os.path.join(sys_net_dir, bond_name, "bonding/miimon")
        if os.path.isfile(miimon_path):
            try:
                with open(miimon_path, "w") as f:
                    f.write(str(miimon))
            except Exception:
                ignored("backend.hardware.network.update_bond_config")

    mode_info = common.BONDING_MODES.get(mode_code, common.BONDING_MODES["1"])
    try:
        from backend.state import add_event

        add_event(
            "info",
            "Bonding Mode Updated",
            f"Bond {bond_name} updated to {mode_info['title']} with slaves: {', '.join(slaves)} (miimon: {miimon}ms).",
        )
    except Exception:
        ignored("backend.hardware.network.update_bond_config")

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

    sys_net_dir = common._find_sys_net_dir()
    br_dir = os.path.join(sys_net_dir, br_name) if sys_net_dir else f"/sys/class/net/{br_name}"

    stp_raw = common._read_file(os.path.join(br_dir, "bridge/stp_state"), "0").strip()
    stp_enabled = stp_raw in ("1", "yes", "true")
    fd_raw = common._read_file(os.path.join(br_dir, "bridge/forward_delay"), "0").strip()
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
    unraid_cfg = canary._parse_unraid_network_cfg()
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
    saved_cfg = common.load_network_config()
    br_meta = saved_cfg.get("bridges", {}).get(br_name, {})
    if "stp" in br_meta:
        stp_enabled = bool(br_meta["stp"])
    if "forward_delay" in br_meta:
        forward_delay = int(br_meta["forward_delay"])
    if "members" in br_meta and not members:
        members = list(br_meta["members"])

    # Candidate members (physical NICs + bonds)
    topo = topology.get_network_topology()
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
    cfg = common.load_network_config()
    bridges = cfg.setdefault("bridges", {})
    bridges[br_name] = {
        "stp": stp,
        "forward_delay": forward_delay,
        "members": members,
        "updated_at": time.time(),
    }
    common.save_network_config(cfg)

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
    canary._write_unraid_network_cfg(unraid_updates)

    # Runtime sysfs apply
    sys_net_dir = common._find_sys_net_dir()
    if sys_net_dir:
        stp_path = os.path.join(sys_net_dir, br_name, "bridge/stp_state")
        if os.path.isfile(stp_path):
            try:
                with open(stp_path, "w") as f:
                    f.write("1" if stp else "0")
            except Exception:
                ignored("backend.hardware.network.update_bridge_config")
        fd_path = os.path.join(sys_net_dir, br_name, "bridge/forward_delay")
        if os.path.isfile(fd_path):
            try:
                with open(fd_path, "w") as f:
                    f.write(str(forward_delay * 100))
            except Exception:
                ignored("backend.hardware.network.update_bridge_config")

    try:
        from backend.state import add_event

        add_event(
            "info",
            "Bridge Configured",
            f"Bridge {br_name} updated: STP {'Enabled' if stp else 'Disabled'}, Forward Delay {forward_delay}s, Members: {', '.join(members) or 'None'}.",
        )
    except Exception:
        ignored("backend.hardware.network.update_bridge_config")

    return {
        "status": "ok",
        "bridge_name": br_name,
        "stp": stp,
        "forward_delay": forward_delay,
        "members": members,
        "message": f"Bridge configuration for '{br_name}' saved successfully. Settings persisted to system config.",
    }
