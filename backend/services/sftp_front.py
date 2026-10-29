#!/usr/bin/env python3
"""SFTP through ZettNAS (SEC-34).

    python3 sftp_front.py <port> <cache dir>

Starts rclone's SFTP server on a loopback port and answers on <port> itself: a connection
from a blocked address is closed before it reaches rclone, everything else is passed on
byte for byte. The SFTP sidecar runs this as its command, and so does the fallback process
inside the app; it ends when rclone ends, and stops rclone when it is stopped.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import Callable

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

CHUNK = 256 * 1024


def internal_port(public: int) -> int:
    from backend.services.webdav_front import internal_port as port_behind

    return port_behind(public)


def rclone_command(internal: int, cache_dir: str) -> list[str]:
    from backend.config import POOL_PATH
    from backend.fsutil import protected_rclone_excludes
    from backend.services.webdav_front import auth_proxy_command

    return [
        "rclone",
        "serve",
        "sftp",
        "--addr",
        f"127.0.0.1:{internal}",
        "--vfs-cache-mode",
        "writes",
        "--dir-cache-time",
        "10s",
        "--cache-dir",
        cache_dir,
        "--auth-proxy",
        auth_proxy_command(os.path.join(SCRIPT_DIR, "rclone_auth_proxy.py")),
        *protected_rclone_excludes(POOL_PATH),
    ]


def _peer_ip(writer: asyncio.StreamWriter) -> str:
    peer = writer.get_extra_info("peername")
    ip = str(peer[0]) if peer else ""
    return ip[7:] if ip.startswith("::ffff:") else ip


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(CHUNK):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except (ConnectionError, OSError):
            pass


async def serve(
    port: int, internal: int, blocked: Callable[[str], bool], host: str = "0.0.0.0"
) -> asyncio.AbstractServer:
    """Listens on host:port and passes each allowed connection on to 127.0.0.1:internal."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if blocked(_peer_ip(writer)):
            writer.close()
            return
        try:
            up_reader, up_writer = await asyncio.open_connection("127.0.0.1", internal)
        except OSError:
            writer.close()
            return
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))

    return await asyncio.start_server(handle, host, port)


async def _run(port: int, internal: int, proc: subprocess.Popen) -> int:
    from backend.services import ip_block

    server = await serve(port, internal, ip_block.is_blocked)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set() and proc.poll() is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                continue
    finally:
        server.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    if stop.is_set():
        return 0
    code = proc.returncode or 0
    return code if code >= 0 else 1  # rclone ended by a signal


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[0].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    port, cache_dir = int(argv[0]), argv[1]
    internal = internal_port(port)
    os.makedirs(cache_dir, exist_ok=True)
    proc = subprocess.Popen(rclone_command(internal, cache_dir))
    return asyncio.run(_run(port, internal, proc))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
