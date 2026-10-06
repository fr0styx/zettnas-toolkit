"""
ZettNAS Toolkit - Docker Introspection Subsystem
Queries local Docker daemon Unix socket (/var/run/docker.sock) for container
health, status, image tags, and uptime.
"""

import http.client
import json
import os
import socket
import time
from typing import Any, Dict, List

from backend.config import logger

_CACHED_CONTAINERS: List[Dict[str, Any]] = []
_LAST_DOCKER_POLL = 0.0
_DOCKER_CACHE_TTL = 3.0


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 3.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def read_docker_containers(force: bool = False) -> List[Dict[str, Any]]:
    global _CACHED_CONTAINERS, _LAST_DOCKER_POLL
    now = time.time()
    if not force and _CACHED_CONTAINERS and (now - _LAST_DOCKER_POLL) < _DOCKER_CACHE_TTL:
        return _CACHED_CONTAINERS

    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return []

    try:
        conn = UnixHTTPConnection(sock_path, timeout=3.0)
        conn.request("GET", "/containers/json?all=1")
        res = conn.getresponse()
        if res.status != 200:
            return _CACHED_CONTAINERS

        raw = json.loads(res.read().decode("utf-8", errors="replace"))
        out = []
        for c in raw:
            names = c.get("Names", [])
            name = names[0].lstrip("/") if names else "unnamed"
            out.append(
                {
                    "id": c.get("Id", "")[:12],
                    "name": name,
                    "image": c.get("Image", ""),
                    "state": c.get("State", "unknown"),
                    "status": c.get("Status", ""),
                    "created": c.get("Created", 0),
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
