"""WebDAV through ZettNAS (SEC-34).

rclone serves WebDAV on a loopback port only. Clients keep the address they know, the
WebDAV port (8084), but it is ZettNAS that answers there: blocked addresses get 403, a
failed sign-in counts towards blocking the address, and writes feed the ransomware guard,
as they do on the web app's /webdav path. Both paths forward with `forward`.

This module imports nothing from the rest of ZettNAS: what it checks and reports goes
through a Gate the WebDAV engine hands it (backend.services.webdav_engine.gate).
"""

from __future__ import annotations

import base64
import logging
import socket
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

logger = logging.getLogger("ZettNAS.WebDAV")

METHODS = [
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "HEAD",
    "OPTIONS",
    "PROPFIND",
    "PROPPATCH",
    "MKCOL",
    "COPY",
    "MOVE",
    "LOCK",
    "UNLOCK",
]
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


@dataclass
class Gate:
    """What the front asks ZettNAS: the client's address, whether it is blocked; and what it
    tells it: a failed sign-in, a write for the ransomware guard."""

    client_ip: Callable[[Request], str]
    blocked: Callable[[str], bool]
    failed: Callable[[str], Any]
    observe: Callable[..., Any]


def internal_port(public: int) -> int:
    """The loopback port rclone listens on behind a public one."""
    return public + 10000 if public <= 55535 else public - 10000


def auth_proxy_command(script: str) -> str:
    """rclone's --auth-proxy, run by this Python: the image ships the script without the
    execute bit, and rclone then refused every sign-in ("permission denied")."""
    import sys

    return f"{sys.executable} {script}"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=None)


def _basic_user(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        return ""
    try:
        return base64.b64decode(auth[6:]).decode("utf-8", "replace").split(":", 1)[0]
    except ValueError:
        return ""


def observe_write(request: Request, path: str, prefix: str, gate: Gate) -> None:
    """Feeds WebDAV renames, deletes and writes to the ransomware guard (M4)."""
    kind = {"MOVE": "rename", "DELETE": "delete", "PUT": "write"}.get(request.method)
    if not kind:
        return
    dest = request.headers.get("destination", "")
    if prefix:
        new_path = urllib.parse.unquote(dest.split(f"{prefix}/", 1)[1]) if f"{prefix}/" in dest else ""
    else:
        new_path = urllib.parse.unquote(urllib.parse.urlsplit(dest).path).lstrip("/") if dest else ""
    gate.observe(kind, path, user=_basic_user(request), ip=gate.client_ip(request), new_path=new_path)


async def forward(request: Request, path: str, port: int, gate: Gate, prefix: str = "") -> Response:
    """Sends a request on to rclone at 127.0.0.1:port and streams its answer back.

    prefix is "/webdav" on the web app's port, where the path and the Destination of COPY and
    MOVE are moved to the root rclone serves; on the WebDAV port they reach rclone as sent,
    with the client's Host, which rclone compares the Destination with."""
    observe_write(request, path, prefix, gate)
    target = f"http://127.0.0.1:{port}/{path.lstrip('/')}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    headers = dict(request.headers)
    if prefix:
        headers["host"] = f"127.0.0.1:{port}"
        dest = headers.get("destination", "")
        if f"{prefix}/" in dest:
            headers["destination"] = f"http://127.0.0.1:{port}/{dest.split(f'{prefix}/', 1)[1]}"
    client = _client()
    try:
        resp = await client.send(
            client.build_request(request.method, target, headers=headers, content=request.stream()), stream=True
        )
    except httpx.ConnectError:
        await client.aclose()
        return PlainTextResponse("The WebDAV server is not running.", status_code=502)
    if resp.status_code == 401 and _basic_user(request):
        gate.failed(gate.client_ip(request))

    async def body():
        try:
            if resp.is_stream_consumed:  # an answer the transport read already
                yield resp.content
                return
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    out = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP}
    return StreamingResponse(body(), status_code=resp.status_code, headers=out)


def front_app(port: int, gate: Gate) -> Starlette:
    """The app that answers on the WebDAV port and forwards to rclone on `port`."""

    async def endpoint(request: Request) -> Response:
        if gate.blocked(gate.client_ip(request)):
            return PlainTextResponse("This address is blocked.", status_code=403)
        return await forward(request, request.path_params.get("path", ""), port, gate)

    return Starlette(routes=[Route("/{path:path}", endpoint, methods=METHODS)])


class Front:
    """Runs front_app on the public WebDAV port in its own thread."""

    def __init__(self) -> None:
        self._server: Any = None
        self._thread: threading.Thread | None = None

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, public: int, internal: int, gate: Gate, host: str = "0.0.0.0") -> None:
        """Binds the port first, so a port in use is an error here, not in the thread."""
        import uvicorn

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, public))
        except OSError:
            sock.close()
            raise
        sock.listen(128)
        config = uvicorn.Config(
            front_app(internal, gate), log_level="warning", access_log=False, lifespan="off", proxy_headers=False
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [sock]}, daemon=True, name="webdav-front"
        )
        self._thread.start()
        deadline = time.time() + 5
        while not self._server.started and self._thread.is_alive() and time.time() < deadline:
            time.sleep(0.02)
        logger.info("[WEBDAV] Front on port %s forwards to 127.0.0.1:%s", public, internal)

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
