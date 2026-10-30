#!/usr/bin/env python3
"""SFTP through ZettNAS (SEC-34).

    python3 sftp_front.py <port> <cache dir>

Starts rclone's SFTP server on a loopback port and answers on <port> itself: a connection
from a blocked address is closed before it reaches rclone, everything else is passed on
byte for byte. The SFTP sidecar runs this as its command, and so does the fallback process
inside the app; it ends when rclone ends, and stops rclone when it is stopped.

Failed sign-ins count against the address they came from (NSEC-15). rclone's auth proxy
doesn't know the address, so it writes each failure's time to a small log, and this front
gives it to the one address that was signing in then; with several addresses signing in at
once, nobody is counted.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

CHUNK = 256 * 1024
FAIL_LOG_ENV = "ZETTNAS_AUTH_FAIL_LOG"  # set for the SFTP rclone only, so WebDAV failures aren't counted here
AUTH_WINDOW_S = 30.0  # how long after connecting a client is still signing in


class SignIns:
    """The connections still in their sign-in phase, to tell whose a failed sign-in was."""

    def __init__(self) -> None:
        self.conns: list[list] = []  # [ip, opened, closed or None]

    def opened(self, ip: str, now: float | None = None) -> list:
        entry = [ip, now if now is not None else time.time(), None]
        self.conns.append(entry)
        return entry

    def closed(self, entry: list, now: float | None = None) -> None:
        entry[2] = now if now is not None else time.time()

    def who(self, ts: float) -> str:
        """The address that was signing in at ts, or "" when none or several were."""
        ips = {c[0] for c in self.conns if c[1] - 1 <= ts <= c[1] + AUTH_WINDOW_S and (c[2] is None or c[2] >= ts - 1)}
        return ips.pop() if len(ips) == 1 else ""

    def prune(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.conns = [c for c in self.conns if now - c[1] < AUTH_WINDOW_S + 5 or c[2] is None and now - c[1] < 600]


def take_failures(path: str) -> list[float]:
    """The failure times the auth proxy wrote since the last call (the log is moved aside first,
    so the proxy's next lines go to a new one)."""
    reading = path + ".reading"
    try:
        os.replace(path, reading)
    except FileNotFoundError:
        return []
    out = []
    try:
        with open(reading, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(float(json.loads(line)["ts"]))
                except (ValueError, KeyError, TypeError):
                    continue
    finally:
        try:
            os.remove(reading)
        except OSError:
            from backend.ignored_errors import ignored

            ignored("backend.services.sftp_front.take_failures")
    return out


def count_failures(path: str, sign_ins: SignIns, record: Callable[[str, str], object]) -> int:
    """Gives each new failure to its address; returns how many were counted."""
    counted = 0
    for ts in take_failures(path):
        ip = sign_ins.who(ts)
        if ip:
            record(ip, "SFTP")
            counted += 1
    sign_ins.prune()
    return counted


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
    port: int,
    internal: int,
    blocked: Callable[[str], bool],
    host: str = "0.0.0.0",
    sign_ins: SignIns | None = None,
) -> asyncio.AbstractServer:
    """Listens on host:port and passes each allowed connection on to 127.0.0.1:internal."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        ip = _peer_ip(writer)
        if blocked(ip):
            writer.close()
            return
        try:
            up_reader, up_writer = await asyncio.open_connection("127.0.0.1", internal)
        except OSError:
            writer.close()
            return
        entry = sign_ins.opened(ip) if sign_ins is not None else None
        try:
            await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
        finally:
            if entry is not None and sign_ins is not None:
                sign_ins.closed(entry)

    return await asyncio.start_server(handle, host, port)


async def _run(port: int, internal: int, proc: subprocess.Popen, fail_log: str = "") -> int:
    from backend.services import ip_block

    sign_ins = SignIns()
    server = await serve(port, internal, ip_block.is_blocked, sign_ins=sign_ins)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set() and proc.poll() is None:
            if fail_log:
                count_failures(fail_log, sign_ins, ip_block.record_auth_failure)
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
    fail_log = os.path.join(cache_dir, "auth-failures.log")
    proc = subprocess.Popen(rclone_command(internal, cache_dir), env={**os.environ, FAIL_LOG_ENV: fail_log})
    return asyncio.run(_run(port, internal, proc, fail_log))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
