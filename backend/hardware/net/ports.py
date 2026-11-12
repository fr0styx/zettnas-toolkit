"""Network ports: descriptions, ethtool, MTU, Wake-on-LAN, link negotiation, and Docker networks.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import re
import subprocess
from typing import Any

import httpx

from backend.hardware.net import common, topology
from backend.ignored_errors import ignored


def _query_ethtool(iface: str) -> str:
    """Query ethtool for an interface safely, checking host namespace if needed."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", iface):
        return ""
    try:
        res = subprocess.run(["ethtool", iface], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 or "Settings for" in res.stdout:
            return res.stdout
    except Exception:
        ignored("backend.hardware.network._query_ethtool")

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
            ignored("backend.hardware.network._query_ethtool")

    return ""


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


def create_docker_network(name: str, driver: str = "bridge", subnet: str = "", gateway: str = "") -> dict[str, Any]:
    """Create a new Docker network via Docker engine API."""
    if (driver or "bridge") != "bridge":
        # macvlan and ipvlan need the parent port, which nothing here asks for (network report B8)
        return {"status": "error", "message": "Only bridge networks are created here."}
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


def save_port_alias(iface_name: str, alias: str) -> str:
    """Saves Kiboto's own nickname for a port ("" removes it). The host's wiring is not touched."""
    name = (alias or "").strip()[:64]
    cfg = common.load_network_config()
    aliases = cfg.setdefault("aliases", {})
    if name:
        aliases[iface_name] = name
    else:
        aliases.pop(iface_name, None)
    common.save_network_config(cfg)
    return name
