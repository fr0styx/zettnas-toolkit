"""The hardware helper (SEC-24 step 2): the only process that opens /dev/mem.

It runs in a small container of its own (no network, every capability dropped but SYS_RAWIO,
read-only), maps just the two physical pages Kiboto needs on Zettlab boxes, and answers a fixed list
of requests over a Unix socket that Kiboto's container shares:

    {"op": "ping"}                          -> {"ok": true}
    {"op": "fans"}                          -> {"rpm": [zone1, zone2, cpu]}
    {"op": "pwm", "channel": 1-3, "value": 0..FAN_MAX_PWM}   -> {"ok": true}
    {"op": "button"}                        -> {"value": <the copy button register>}

Anything else is refused. Kiboto itself then needs neither /dev/mem nor SYS_RAWIO. Standard library
only, so the helper starts from the app's image without the app.

    python3 -m backend.hw_helper --socket /run/kiboto-hw/hw.sock
"""

from __future__ import annotations

import argparse
import json
import mmap
import os
import socketserver
import struct
import sys
import threading

PAGE = 4096
# Embedded controller (fans), the register aperture backend/hardware/fans.py documents
EC_BASE = 0xFE0B0456
EC_RPM = (0, 3, 6)  # 16-bit big-endian tachometers: disks zone 1, disks zone 2, CPU
EC_PWM = {1: 2, 2: 5, 3: 8}  # 8-bit duty per channel
FAN_MAX_PWM = 183
# GPIO block with the front COPY button (backend/services/button_listener.py)
GPIO_BASE = 0xE0D20000
COPY_OFFSET = 0x6C0
MAX_LINE = 256


class Pages:
    """The two pages, mapped once from /dev/mem (or a stand-in file in tests)."""

    def __init__(self, mem_path: str = "/dev/mem"):
        self.mem_path = mem_path
        self._lock = threading.Lock()
        self._maps: dict[int, mmap.mmap] = {}

    def _page(self, base: int) -> tuple[mmap.mmap, int]:
        start = base - (base % PAGE)
        with self._lock:
            mm = self._maps.get(start)
            if mm is None:
                fd = os.open(self.mem_path, os.O_RDWR | getattr(os, "O_SYNC", 0))
                try:
                    mm = mmap.mmap(fd, PAGE, offset=start)
                finally:
                    os.close(fd)
                self._maps[start] = mm
        return mm, base - start

    def fans(self) -> list[int]:
        mm, at = self._page(EC_BASE)
        return [(mm[at + o] << 8) | mm[at + o + 1] for o in EC_RPM]

    def pwm(self, channel: int, value: int) -> None:
        mm, at = self._page(EC_BASE)
        mm[at + EC_PWM[channel]] = value

    def button(self) -> int:
        mm, at = self._page(GPIO_BASE)
        return struct.unpack("<I", mm[at + COPY_OFFSET : at + COPY_OFFSET + 4])[0]


def answer(pages: Pages, request: object) -> dict:
    """One request of the fixed list, checked; anything else is refused."""
    if not isinstance(request, dict):
        return {"error": "not a request"}
    op = request.get("op")
    try:
        if op == "ping":
            return {"ok": True}
        if op == "fans":
            return {"rpm": pages.fans()}
        if op == "button":
            return {"value": pages.button()}
        if op == "pwm":
            channel, value = request.get("channel"), request.get("value")
            if type(channel) is not int or channel not in EC_PWM:
                return {"error": "channel must be 1, 2 or 3"}
            if type(value) is not int or not 0 <= value <= FAN_MAX_PWM:
                return {"error": f"value must be 0..{FAN_MAX_PWM}"}
            pages.pwm(channel, value)
            return {"ok": True}
    except OSError as e:
        return {"error": f"hardware: {e.strerror or e}"}
    return {"error": "unknown request"}


def serve(socket_path: str, mem_path: str = "/dev/mem") -> socketserver.ThreadingUnixStreamServer:
    pages = Pages(mem_path)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            for raw in iter(lambda: self.rfile.readline(MAX_LINE + 1), b""):
                if len(raw) > MAX_LINE:
                    self.wfile.write(b'{"error": "request too long"}\n')
                    return
                try:
                    reply = answer(pages, json.loads(raw))
                except ValueError:
                    reply = {"error": "not JSON"}
                self.wfile.write(json.dumps(reply).encode() + b"\n")

    if os.path.exists(socket_path):
        os.unlink(socket_path)
    os.makedirs(os.path.dirname(socket_path) or ".", exist_ok=True)
    old = os.umask(0o117)  # owner and group: Kiboto's container shares the folder, nobody else
    try:
        server = socketserver.ThreadingUnixStreamServer(socket_path, Handler)
    finally:
        os.umask(old)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kiboto hardware helper (SEC-24)")
    ap.add_argument("--socket", default="/run/kiboto-hw/hw.sock")
    ap.add_argument("--mem", default="/dev/mem")
    args = ap.parse_args(argv)
    server = serve(args.socket, args.mem)
    print(f"[hw-helper] answering on {args.socket}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[hw-helper] stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
