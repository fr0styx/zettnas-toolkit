"""
Docker Subsystem & Daemon Diagnostics for ZettNAS Toolkit.
Collects Docker daemon health, disk usage (docker system df), port conflict detection,
cgroup limits, and targeted error logs for crashed/restarting containers via /var/run/docker.sock.
"""

import http.client
import json
import os
import socket
import time
from typing import Any, Dict, List, Optional

from backend.config import logger
from backend.logging_config import sanitize_dict, sanitize_string


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str = "/var/run/docker.sock", timeout: float = 2.5):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def _docker_api_get(endpoint: str, timeout: float = 2.5) -> Optional[Any]:
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return None
    conn = None
    try:
        conn = UnixHTTPConnection(sock_path, timeout=timeout)
        conn.request("GET", endpoint)
        res = conn.getresponse()
        if res.status == 200:
            raw = res.read().decode("utf-8", errors="replace")
            return json.loads(raw)
        return None
    except Exception as e:
        logger.debug(f"[Docker Diagnostics] GET {endpoint} failed: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _docker_api_get_logs(container_id: str, tail: int = 50) -> str:
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return ""
    conn = None
    try:
        conn = UnixHTTPConnection(sock_path, timeout=2.0)
        conn.request("GET", f"/containers/{container_id}/logs?stdout=1&stderr=1&tail={tail}")
        res = conn.getresponse()
        if res.status == 200:
            raw_bytes = res.read()
            lines = []
            idx = 0
            while idx < len(raw_bytes):
                if (
                    idx + 8 <= len(raw_bytes)
                    and raw_bytes[idx] in (0, 1, 2)
                    and raw_bytes[idx + 1 : idx + 4] == b"\x00\x00\x00"
                ):
                    size = int.from_bytes(raw_bytes[idx + 4 : idx + 8], "big")
                    line_data = raw_bytes[idx + 8 : idx + 8 + size]
                    lines.append(line_data.decode("utf-8", errors="replace"))
                    idx += 8 + size
                else:
                    lines.append(raw_bytes[idx:].decode("utf-8", errors="replace"))
                    break
            return "".join(lines)
        return ""
    except Exception as e:
        logger.debug(f"[Docker Diagnostics] Logs for {container_id} failed: {e}")
        return ""
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def collect_docker_diagnostics() -> Dict[str, Any]:
    """
    Collects complete Docker daemon and container fleet diagnostics.
    """
    t0 = time.time()
    result: Dict[str, Any] = {
        "daemon_connected": False,
        "daemon_info": {},
        "system_df": {},
        "containers_summary": {
            "total": 0,
            "running": 0,
            "stopped": 0,
            "restarting": 0,
            "dead": 0,
            "oom_killed": 0,
        },
        "port_conflicts": [],
        "troubled_container_logs": {},
    }

    raw_info = _docker_api_get("/info")
    if raw_info is None:
        result["error"] = "Docker socket /var/run/docker.sock unavailable or unresponsive"
        return result

    result["daemon_connected"] = True

    # 1. Daemon Info
    result["daemon_info"] = {
        "server_version": raw_info.get("ServerVersion"),
        "operating_system": raw_info.get("OperatingSystem"),
        "kernel_version": raw_info.get("KernelVersion"),
        "architecture": raw_info.get("Architecture"),
        "ncpu": raw_info.get("NCPU"),
        "mem_total": raw_info.get("MemTotal"),
        "storage_driver": raw_info.get("Driver"),
        "docker_root_dir": raw_info.get("DockerRootDir"),
        "cgroup_driver": raw_info.get("CgroupDriver"),
        "cgroup_version": raw_info.get("CgroupVersion"),
        "live_restore": raw_info.get("LiveRestoreEnabled"),
        "warnings": raw_info.get("Warnings"),
    }

    # 2. System Disk Usage (docker system df)
    raw_df = _docker_api_get("/system/df")
    if isinstance(raw_df, dict):
        images = raw_df.get("Images") or []
        containers = raw_df.get("Containers") or []
        volumes = raw_df.get("Volumes") or []
        build_cache = raw_df.get("BuildCache") or []

        result["system_df"] = {
            "images_count": len(images),
            "images_size_bytes": sum(img.get("Size", 0) for img in images),
            "containers_count": len(containers),
            "containers_size_bytes": sum(c.get("SizeRw", 0) for c in containers if isinstance(c, dict)),
            "volumes_count": len(volumes),
            "volumes_size_bytes": sum(v.get("UsageData", {}).get("Size", 0) for v in volumes if isinstance(v, dict)),
            "build_cache_size_bytes": sum(b.get("Size", 0) for b in build_cache if isinstance(b, dict)),
        }

    # 3. Containers Inspection & Port Conflict Detection
    host_port_map: Dict[str, List[str]] = {}
    troubled_containers: List[Dict[str, str]] = []

    containers_list = _docker_api_get("/containers/json?all=1")
    if isinstance(containers_list, list):
        result["containers_summary"]["total"] = len(containers_list)

        for c in containers_list:
            status = c.get("State", "unknown").lower()
            name = (c.get("Names") or ["/unknown"])[0].lstrip("/")
            cid = c.get("Id", "")[:12]

            if status == "running":
                result["containers_summary"]["running"] += 1
            elif status == "restarting":
                result["containers_summary"]["restarting"] += 1
            elif status == "dead":
                result["containers_summary"]["dead"] += 1
            else:
                result["containers_summary"]["stopped"] += 1

            status_str = c.get("Status", "")
            is_oom = "oom" in status_str.lower()
            if is_oom:
                result["containers_summary"]["oom_killed"] += 1

            is_troubled = status in ("restarting", "dead") or is_oom

            if is_troubled:
                troubled_containers.append(
                    {
                        "id": cid,
                        "name": name,
                        "status": status,
                        "oom_killed": str(is_oom),
                    }
                )

            # Port tracking
            ports = c.get("Ports") or []
            for p in ports:
                pub = p.get("PublicPort")
                if pub:
                    host_ip = p.get("IP", "0.0.0.0")
                    h_port = f"{host_ip}:{pub}"
                    if h_port not in host_port_map:
                        host_port_map[h_port] = []
                    host_port_map[h_port].append(name)

        # Identify conflicts
        for h_port, owners in host_port_map.items():
            if len(owners) > 1:
                result["port_conflicts"].append(
                    {
                        "port": h_port,
                        "containers": owners,
                    }
                )

    # 4. Fetch logs for troubled containers (last 50 lines)
    for tc in troubled_containers[:10]:
        c_id = tc["id"]
        c_name = tc["name"]
        raw_logs = _docker_api_get_logs(c_id, tail=50)
        if raw_logs:
            result["troubled_container_logs"][f"{c_name}_{c_id}"] = {
                "status": tc["status"],
                "oom_killed": tc["oom_killed"],
                "tail_logs": sanitize_string(raw_logs),
            }

    result["collection_time_seconds"] = round(time.time() - t0, 3)
    return sanitize_dict(result)
