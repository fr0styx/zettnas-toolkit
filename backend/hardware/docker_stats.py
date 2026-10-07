"""
ZettNAS Toolkit - Docker Introspection Subsystem
Queries local Docker daemon Unix socket (/var/run/docker.sock) for container
health, status, image tags, and uptime.
"""

import concurrent.futures
import http.client
import json
import os
import socket
import threading
import time
from typing import Any, Dict, List

from backend.config import logger

_CACHED_CONTAINERS: List[Dict[str, Any]] = []
_LAST_DOCKER_POLL = 0.0
_DOCKER_CACHE_TTL = 3.0
_CONTAINER_METRICS: Dict[str, Dict[str, Any]] = {}
_TELEMETRY_THREAD_STARTED = False
_TELEMETRY_LOCK = threading.Lock()


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 3.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def _fetch_container_telemetry(cid: str) -> Dict[str, Any]:
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return {}

    try:
        conn = UnixHTTPConnection(sock_path, timeout=2.5)
        conn.request("GET", f"/containers/{cid}/stats?stream=false")
        res = conn.getresponse()
        if res.status != 200:
            return {}

        stats = json.loads(res.read().decode("utf-8", errors="replace"))
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        mem_stats = stats.get("memory_stats", {})
        networks = stats.get("networks", {})

        # Calculate CPU %
        cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get(
            "total_usage", 0
        )
        sys_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
        online_cpus = cpu_stats.get("online_cpus") or len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [1]))

        cpu_pct = 0.0
        if sys_delta > 0 and cpu_delta > 0 and online_cpus > 0:
            cpu_pct = round((cpu_delta / sys_delta) * online_cpus * 100.0, 1)

        # Calculate Memory (excluding kernel buffer/cache)
        mem_usage = mem_stats.get("usage", 0)
        stats_sub = mem_stats.get("stats", {})
        mem_cache = stats_sub.get("cache", 0) or stats_sub.get("inactive_file", 0)
        real_mem = max(0, mem_usage - mem_cache)
        mem_limit = mem_stats.get("limit", 1)
        mem_pct = round((real_mem / mem_limit) * 100.0, 1) if mem_limit > 0 else 0.0

        # Calculate Network I/O
        net_rx = sum(v.get("rx_bytes", 0) for v in networks.values()) if networks else 0
        net_tx = sum(v.get("tx_bytes", 0) for v in networks.values()) if networks else 0

        return {
            "cpu_pct": max(0.0, min(1000.0, cpu_pct)),
            "mem_used": real_mem,
            "mem_limit": mem_limit,
            "mem_pct": max(0.0, min(100.0, mem_pct)),
            "net_rx": net_rx,
            "net_tx": net_tx,
            "updated_at": time.time(),
        }
    except Exception as e:
        logger.debug(f"[Docker] Failed to fetch telemetry for {cid}: {e}")
        return {}


def _docker_telemetry_worker():
    while True:
        try:
            sock_path = "/var/run/docker.sock"
            if not os.path.exists(sock_path):
                time.sleep(5.0)
                continue

            conn = UnixHTTPConnection(sock_path, timeout=3.0)
            conn.request("GET", "/containers/json?filters=%7B%22status%22%3A%5B%22running%22%5D%7D")
            res = conn.getresponse()
            if res.status != 200:
                time.sleep(5.0)
                continue

            running = json.loads(res.read().decode("utf-8", errors="replace"))
            if not running:
                time.sleep(5.0)
                continue

            # Limit parallel queries to avoid burdening Docker daemon
            cids = [c["Id"] for c in running if "Id" in c][:16]
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(cids))) as pool:
                future_to_cid = {pool.submit(_fetch_container_telemetry, cid): cid for cid in cids}
                for fut in concurrent.futures.as_completed(future_to_cid, timeout=12.0):
                    cid = future_to_cid[fut]
                    try:
                        telemetry = fut.result()
                        if telemetry:
                            short_id = cid[:12]
                            with _TELEMETRY_LOCK:
                                _CONTAINER_METRICS[short_id] = telemetry
                    except Exception:
                        pass
            time.sleep(6.0)
        except Exception as e:
            logger.debug(f"[Docker] Telemetry worker error: {e}")
            time.sleep(5.0)


def start_docker_telemetry_collector():
    global _TELEMETRY_THREAD_STARTED
    if not _TELEMETRY_THREAD_STARTED:
        with _TELEMETRY_LOCK:
            if not _TELEMETRY_THREAD_STARTED:
                t = threading.Thread(target=_docker_telemetry_worker, daemon=True, name="DockerTelemetry")
                t.start()
                _TELEMETRY_THREAD_STARTED = True


def read_docker_containers(force: bool = False) -> List[Dict[str, Any]]:
    global _CACHED_CONTAINERS, _LAST_DOCKER_POLL
    now = time.time()
    if not force and _CACHED_CONTAINERS and (now - _LAST_DOCKER_POLL) < _DOCKER_CACHE_TTL:
        return _CACHED_CONTAINERS

    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return []

    start_docker_telemetry_collector()

    try:
        conn = UnixHTTPConnection(sock_path, timeout=3.0)
        conn.request("GET", "/containers/json?all=1")
        res = conn.getresponse()
        if res.status != 200:
            return _CACHED_CONTAINERS

        raw = json.loads(res.read().decode("utf-8", errors="replace"))
        out = []
        for c in raw:
            cid_short = c.get("Id", "")[:12]
            names = c.get("Names", [])
            name = names[0].lstrip("/") if names else "unnamed"
            metrics = _CONTAINER_METRICS.get(cid_short, {})
            out.append(
                {
                    "id": cid_short,
                    "name": name,
                    "image": c.get("Image", ""),
                    "state": c.get("State", "unknown"),
                    "status": c.get("Status", ""),
                    "created": c.get("Created", 0),
                    "cpu_pct": metrics.get("cpu_pct", 0.0),
                    "mem_used": metrics.get("mem_used", 0),
                    "mem_limit": metrics.get("mem_limit", 0),
                    "mem_pct": metrics.get("mem_pct", 0.0),
                    "net_rx": metrics.get("net_rx", 0),
                    "net_tx": metrics.get("net_tx", 0),
                }
            )
        out.sort(key=lambda x: (x["state"] != "running", x["name"]))
        _CACHED_CONTAINERS = out
        _LAST_DOCKER_POLL = now
        return out
    except Exception as e:
        logger.debug(f"[Docker] Failed to introspect containers: {e}")
        return _CACHED_CONTAINERS


def container_action(container_id: str, action: str) -> Dict[str, Any]:
    global _CACHED_CONTAINERS, _LAST_DOCKER_POLL
    # Sanitize container_id: alphanumeric only, 1-64 chars
    if not container_id or not container_id.isalnum() or len(container_id) > 64:
        return {"success": False, "error": "Invalid container ID"}

    action = action.lower().strip()
    if action not in ("start", "stop", "restart", "pause", "unpause"):
        return {"success": False, "error": f"Unsupported action: {action}"}

    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return {"success": False, "error": "Docker socket not available"}

    endpoint = f"/containers/{container_id}/{action}"
    if action in ("stop", "restart"):
        endpoint += "?t=10"

    try:
        conn = UnixHTTPConnection(sock_path, timeout=15.0)
        conn.request("POST", endpoint)
        res = conn.getresponse()
        resp_data = res.read().decode("utf-8", errors="replace")

        # 204 No Content, 200 OK, or 304 Not Modified
        if res.status in (200, 204, 304):
            _CACHED_CONTAINERS = []
            _LAST_DOCKER_POLL = 0.0
            return {"success": True, "action": action, "id": container_id}

        err_msg = f"HTTP {res.status}"
        try:
            parsed = json.loads(resp_data)
            if "message" in parsed:
                err_msg = parsed["message"]
        except Exception:
            if resp_data:
                err_msg = resp_data
        return {"success": False, "error": err_msg}
    except Exception as e:
        logger.error(f"[Docker] Failed to perform {action} on {container_id}: {e}")
        return {"success": False, "error": str(e)}
