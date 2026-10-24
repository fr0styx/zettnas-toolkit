"""The one Docker Engine API client (ARCH-3).

- request(): status and decoded JSON (or {"raw": text}); never raises for HTTP errors.
- raw_request(): status and bytes, for archives and logs.
- call(): decoded JSON for a 2xx answer, otherwise a typed DockerError.
All of them talk to docker_sock(): the allow-list proxy when it runs, else the raw socket.
"""

import http.client
import json
import os
import socket
import urllib.parse
from typing import Any

from backend.config import docker_sock, logger


class DockerError(Exception):
    """Docker answered with an error status."""

    def __init__(self, status: int, message: str, path: str = ""):
        super().__init__(f"Docker {status} on {path}: {message}" if path else f"Docker {status}: {message}")
        self.status = status
        self.message = message
        self.path = path


class DockerUnavailable(DockerError):
    """The Docker socket is missing or doesn't answer."""


class DockerNotFound(DockerError):
    """404: no such container, image, network or volume."""


class DockerConflict(DockerError):
    """409: name in use, container already running/stopped, etc."""


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str | None = None, timeout: float = 3.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path or docker_sock()

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def _safe_path(path: str) -> str:
    """Quote query values so control characters or JSON never make an invalid URL."""
    if "?" in path:
        base, query = path.split("?", 1)
        parts = []
        for p in query.split("&"):
            if "=" in p:
                k, v = p.split("=", 1)
                parts.append(f"{k}={urllib.parse.quote(urllib.parse.unquote(v))}")
            else:
                parts.append(p)
        return f"{base}?{'&'.join(parts)}"
    return path.replace(" ", "%20") if " " in path else path


def raw_request(
    method: str,
    path: str,
    body: bytes | None = None,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    """Status and body bytes. Raises DockerUnavailable when the socket is missing or unreachable."""
    sock_path = docker_sock()
    if not os.path.exists(sock_path):
        raise DockerUnavailable(503, f"Docker socket {sock_path} not found", path)
    conn = UnixHTTPConnection(sock_path, timeout=timeout)
    try:
        req_headers = dict(headers or {})
        if body is not None and "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"
        conn.request(method, _safe_path(path), body=body, headers=req_headers)
        res = conn.getresponse()
        return res.status, res.read()
    except OSError as e:
        raise DockerUnavailable(503, str(e), path) from e
    finally:
        try:
            conn.close()
        except Exception:
            logger.debug("docker_client: close failed", exc_info=True)


def _decode(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text) if text.strip() else {}
    except ValueError:
        return {"raw": text}


def request(
    method: str,
    path: str,
    body: Any = None,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """Status and decoded body. Raises only DockerUnavailable (socket missing or unreachable)."""
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    status, raw = raw_request(method, path, payload, timeout=timeout, headers=headers)
    return status, _decode(raw)


def call(method: str, path: str, body: Any = None, timeout: float = 15.0, headers: dict[str, str] | None = None) -> Any:
    """Decoded body of a 2xx answer; otherwise DockerNotFound, DockerConflict or DockerError."""
    status, data = request(method, path, body=body, timeout=timeout, headers=headers)
    if 200 <= status < 300:
        return data
    message = (data.get("message") or data.get("raw") or "") if isinstance(data, dict) else str(data)
    error_cls = {404: DockerNotFound, 409: DockerConflict}.get(status, DockerError)
    raise error_cls(status, str(message)[:500], path)
