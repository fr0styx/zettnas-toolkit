"""Network ports: descriptions, ethtool, MTU, Wake-on-LAN, link negotiation, and Docker networks.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import re
import subprocess
from typing import Any

import httpx

from backend.config import logger
from backend.hardware.net import common, topology


def _query_ethtool(iface: str) -> str:
    """Query ethtool for an interface safely, checking host namespace if needed."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", iface):
        return ""
    try:
        res = subprocess.run(["ethtool", iface], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 or "Settings for" in res.stdout:
            return res.stdout
    except Exception:
        logger.debug("backend.hardware.network._query_ethtool: ignored error", exc_info=True)

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
            logger.debug("backend.hardware.network._query_ethtool: ignored error", exc_info=True)

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
        logger.debug("backend.hardware.network._apply_mtu: ignored error", exc_info=True)

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
            logger.debug("backend.hardware.network._apply_mtu: ignored error", exc_info=True)

    for sys_base in [common.HOST_SYS, "/host/sys", "/sys"]:
        mtu_path = os.path.join(sys_base, "class/net", iface, "mtu")
        if os.path.isfile(mtu_path):
            try:
                with open(mtu_path, "w") as f:
                    f.write(str(mtu_val))
                return True
            except Exception:
                logger.debug("backend.hardware.network._apply_mtu: ignored error", exc_info=True)
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
        logger.debug("backend.hardware.network._apply_wol: ignored error", exc_info=True)

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
            logger.debug("backend.hardware.network._apply_wol: ignored error", exc_info=True)
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
        logger.debug("backend.hardware.network._apply_negotiation: ignored error", exc_info=True)

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
            logger.debug("backend.hardware.network._apply_negotiation: ignored error", exc_info=True)
    return False


def get_port_config(iface_name: str) -> dict[str, Any]:
    """Retrieve full configuration, hardware capabilities, and alias for a port."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", iface_name):
        return {"status": "error", "message": "Invalid interface name"}

    topo = topology.get_network_topology()
    nic = next((p for p in topo.get("physical_interfaces", []) if p["name"] == iface_name), None)
    if not nic:
        nic = next((b for b in topo.get("bonds", []) + topo.get("bridges", []) if b["name"] == iface_name), None)
    if not nic:
        return {"status": "error", "message": f"Interface '{iface_name}' not found"}

    cfg = common.load_network_config()
    alias = cfg.get("aliases", {}).get(iface_name, "")
    if not alias:
        unraid_descs = common._get_unraid_descriptions()
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

    cfg = common.load_network_config()
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

    common.save_network_config(cfg)
    return {"status": "ok", "message": f"Port configuration saved for {iface_name}", "config": port_meta}


def create_docker_network(name: str, driver: str = "bridge", subnet: str = "", gateway: str = "") -> dict[str, Any]:
    """Create a new Docker network via Docker engine API."""
    docker_sock = common._docker_sock_path()
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
    docker_sock = common._docker_sock_path()
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
