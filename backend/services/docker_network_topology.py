"""
Docker network topology for the Containers window's Network Map.

Docker's GET /networks no longer lists attached containers (API >= 1.28), so
attachments come from each container's NetworkSettings in /containers/json and
network details (driver, subnet, gateway) from /networks.
"""

from collections.abc import Callable
from typing import Any, Optional

DockerRequest = Callable[..., tuple[int, Any]]


def _short(value: Any) -> str:
    return str(value or "")[:12]


def _empty_network(name: str, network_id: str = "") -> dict[str, Any]:
    return {
        "id": _short(network_id),
        "name": name,
        "driver": "",
        "scope": "",
        "internal": False,
        "subnet": "",
        "gateway": "",
        "container_count": 0,
    }


def summarize_topology(networks_raw: Any, containers_raw: Any) -> dict[str, Any]:
    """Turns raw Docker API lists into {networks: [...], containers: [...]}."""
    networks: dict[str, dict[str, Any]] = {}
    for n in networks_raw if isinstance(networks_raw, list) else []:
        if not isinstance(n, dict) or not n.get("Name"):
            continue
        ipam = (n.get("IPAM") or {}).get("Config") or []
        cfg = ipam[0] if ipam and isinstance(ipam[0], dict) else {}
        net = _empty_network(n["Name"], n.get("Id", ""))
        net.update(
            {
                "driver": n.get("Driver") or "",
                "scope": n.get("Scope") or "",
                "internal": bool(n.get("Internal")),
                "subnet": cfg.get("Subnet") or "",
                "gateway": cfg.get("Gateway") or "",
            }
        )
        networks[n["Name"]] = net

    raw = [c for c in (containers_raw if isinstance(containers_raw, list) else []) if isinstance(c, dict)]
    names_by_id: dict[str, str] = {}
    for c in raw:
        full_id = str(c.get("Id") or "")
        names = c.get("Names") or []
        name = (names[0] if names else _short(full_id)).lstrip("/")
        names_by_id[full_id] = name
        names_by_id[_short(full_id)] = name

    containers: list[dict[str, Any]] = []
    for c in raw:
        full_id = str(c.get("Id") or "")
        mode = str((c.get("HostConfig") or {}).get("NetworkMode") or "")
        attached = []
        for net_name, info in ((c.get("NetworkSettings") or {}).get("Networks") or {}).items():
            info = info if isinstance(info, dict) else {}
            if net_name not in networks:
                networks[net_name] = _empty_network(net_name, info.get("NetworkID", ""))
            networks[net_name]["container_count"] += 1
            attached.append(
                {"network": net_name, "ip": info.get("IPAddress") or "", "mac": info.get("MacAddress") or ""}
            )

        shares_with: str | None = None
        if mode.startswith("container:"):
            target = mode.split(":", 1)[1]
            shares_with = names_by_id.get(target) or names_by_id.get(_short(target)) or target

        ports = []
        seen_ports = set()
        for p in c.get("Ports") or []:
            if not isinstance(p, dict):
                continue
            key = (p.get("PrivatePort"), p.get("PublicPort"), p.get("Type") or "tcp")
            if key in seen_ports:  # Docker lists IPv4 and IPv6 bindings separately
                continue
            seen_ports.add(key)
            ports.append({"private": key[0], "public": key[1], "type": key[2]})

        containers.append(
            {
                "id": _short(full_id),
                "name": names_by_id.get(full_id, _short(full_id)),
                "state": c.get("State") or "",
                "network_mode": mode,
                "compose_project": (c.get("Labels") or {}).get("com.docker.compose.project") or "",
                "networks": sorted(attached, key=lambda a: a["network"]),
                "shares_with": shares_with,
                "ports": ports,
            }
        )

    containers.sort(key=lambda x: x["name"].lower())
    net_list = sorted(networks.values(), key=lambda n: (-n["container_count"], n["name"].lower()))
    return {"networks": net_list, "containers": containers}


def get_network_topology(docker_request: DockerRequest | None = None) -> dict[str, Any]:
    if docker_request is None:
        from backend.services.container_mutator import _docker_request as docker_request
    nets_status, nets = docker_request("GET", "/networks", timeout=5.0)
    ctr_status, ctrs = docker_request("GET", "/containers/json?all=1", timeout=5.0)
    if nets_status != 200 or ctr_status != 200:
        raise RuntimeError(f"Docker API returned {nets_status}/{ctr_status}")
    return summarize_topology(nets, ctrs)
