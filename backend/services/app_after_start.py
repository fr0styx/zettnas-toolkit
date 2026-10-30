"""Set-up a built-in app needs once it runs (COMP-15): commands run in its container, in order.

A template lists them under "after_start", each {"cmd": [...], "label": "...", "user": "...",
"tries": n, "every": secs, "expect": "text", "timeout": secs}. A step is retried until it exits 0
(and prints `expect`, when given), so the first one can wait for the app to finish installing.
Values may use {{secret:name}} (the app's generated secrets), {{host}} and {{port}} (where the
browser reaches the app), {{zettnas}} (ZettNAS's name on its Docker network) and {{arch}}
("" on x86, "_arm64" on ARM). Only built-in templates may have such steps.
"""

from __future__ import annotations

import json
import platform
import re
import socket
import time
from collections.abc import Iterator
from typing import Any

from backend.config import logger

HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$|^\[[0-9A-Fa-f:]{2,45}\]$")
PLACEHOLDER = re.compile(r"\{\{(secret:[a-z_]+|host|port|zettnas|arch)\}\}")


def valid_host(host: str | None) -> str:
    host = (host or "").strip()
    return host if host and HOST_RE.match(host) else ""


def demux(raw: bytes) -> str:
    """Docker's multiplexed exec output as text (8-byte frame headers removed)."""
    out, i = [], 0
    while i + 8 <= len(raw) and raw[i] in (0, 1, 2):
        size = int.from_bytes(raw[i + 4 : i + 8], "big")
        out.append(raw[i + 8 : i + 8 + size])
        i += 8 + size
    text = b"".join(out) if out else raw
    return text.decode("utf-8", errors="replace").strip()


def exec_in(container: str, cmd: list[str], user: str = "", timeout: float = 300) -> tuple[int | None, str]:
    """Runs one command in a container: its exit code (None if it couldn't run) and output."""
    from backend.services import docker_client

    body: dict[str, Any] = {"AttachStdout": True, "AttachStderr": True, "Tty": False, "Cmd": cmd}
    if user:
        body["User"] = user
    status, created = docker_client.request("POST", f"/containers/{container}/exec", body, timeout=15)
    if status not in (200, 201) or not isinstance(created, dict) or not created.get("Id"):
        return None, f"could not run it ({status})"
    start = json.dumps({"Detach": False, "Tty": False}).encode()
    _status, raw = docker_client.raw_request("POST", f"/exec/{created['Id']}/start", start, timeout=timeout)
    _status, info = docker_client.request("GET", f"/exec/{created['Id']}/json")
    code = info.get("ExitCode") if isinstance(info, dict) else None
    return code, demux(raw if isinstance(raw, bytes) else str(raw or "").encode())


def zettnas_name() -> str:
    """ZettNAS's own container name, which other containers on its network resolve."""
    from backend.services import docker_client

    try:
        status, me = docker_client.request("GET", f"/containers/{socket.gethostname()}/json")
    except (OSError, ValueError, RuntimeError, docker_client.DockerUnavailable):
        logger.debug("app_after_start: own container unknown", exc_info=True)
        return "zettnas-toolkit"
    name = str(me.get("Name") or "").lstrip("/") if status == 200 and isinstance(me, dict) else ""
    return name or "zettnas-toolkit"


def fill(value: str, ctx: dict[str, str], secrets: dict[str, str]) -> str:
    def one(m: re.Match[str]) -> str:
        key = m.group(1)
        if key.startswith("secret:"):
            return secrets.get(key[len("secret:") :], "")
        return ctx.get(key, "")

    return PLACEHOLDER.sub(one, str(value))


def context(host: str, port: int) -> dict[str, str]:
    arm = platform.machine().lower() in ("aarch64", "arm64")
    return {
        "host": valid_host(host) or "localhost",
        "port": str(port),
        "zettnas": zettnas_name(),
        "arch": "_arm64" if arm else "",
    }


def run_steps(
    app: dict[str, Any],
    container: str,
    secrets: dict[str, str],
    host: str = "",
    port: int = 0,
    sleep: Any = time.sleep,
    ctx: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Runs the template's steps, yielding progress. Returns the labels of steps that didn't finish;
    the app is installed either way, and those are named to the person."""
    steps = app.get("after_start") or []
    if not steps or app.get("source_id", "builtin") != "builtin":
        return []
    ctx = ctx if ctx is not None else context(host, port)
    unfinished: list[str] = []
    for i, step in enumerate(steps):
        label = str(step.get("label") or "Setting up")
        yield {"step": "configure", "percent": 93 + int(6 * i / len(steps)), "message": f"{label}...", "done": False}
        cmd = [fill(c, ctx, secrets) for c in step.get("cmd") or []]
        tries, every = max(1, int(step.get("tries", 1))), float(step.get("every", 5))
        expect = str(step.get("expect") or "")
        for attempt in range(tries):
            code, out = exec_in(container, cmd, str(step.get("user") or ""), float(step.get("timeout", 300)))
            if code == 0 and (not expect or expect in out):
                break
            if attempt < tries - 1:
                sleep(every)
        else:
            unfinished.append(label)
            logger.warning("[AppCatalog] %s: %s didn't finish: %s", container, label, (out or "")[-300:])
    return unfinished
