"""Container CPU, memory and network straight from the kernel (PERF-4).

Asking dockerd for /containers/<id>/stats costs dockerd a sample per container every round; the
same numbers sit in files the kernel keeps for each container. This reads them:

- CPU and memory from the container's cgroup. Docker puts it in one of a few places depending on
  the cgroup version and driver: v2 with the cgroupfs driver (docker/<id>), v2 with the systemd
  driver (system.slice/docker-<id>.scope), or v1 with either (<controller>/docker/<id>, ...).
  The first layout that has the files wins and is remembered per container.
- Network from /proc/<pid>/net/dev of the container's main process, which shows its own network
  namespace. A container on the host's network has no counters of its own (as in docker stats).

Anything missing or unreadable returns None, and the caller asks dockerd as before. Nothing here
writes anywhere.
"""

from __future__ import annotations

import os
import time
from typing import Any

from backend.config import HOST_PROC, HOST_SYS

# where the host's cgroup tree is visible from inside the container
CGROUP_ROOT = os.path.join(HOST_SYS, "fs", "cgroup")

_LAYOUT: dict[str, tuple[str, str, str] | None] = {}  # container id -> (version, cpu dir, memory dir)
_PREV: dict[str, tuple[float, int]] = {}  # container id -> (monotonic seconds, CPU usage in µs)
_HOST_MEM: dict[str, int] = {}  # proc root -> the host's memory in bytes


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _kv(text: str | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            out[parts[0]] = int(parts[1])
    return out


def _layout(cid: str, root: str) -> tuple[str, str, str] | None:
    if cid in _LAYOUT:
        return _LAYOUT[cid]
    found = None
    for d in (os.path.join(root, "docker", cid), os.path.join(root, "system.slice", f"docker-{cid}.scope")):
        if os.path.exists(os.path.join(d, "cpu.stat")) and os.path.exists(os.path.join(d, "memory.current")):
            found = ("v2", d, d)
            break
    if found is None:
        for tail in (os.path.join("docker", cid), os.path.join("system.slice", f"docker-{cid}.scope")):
            cpu = next(
                (
                    os.path.join(root, c, tail)
                    for c in ("cpuacct", "cpu,cpuacct", "cpuacct,cpu")
                    if os.path.exists(os.path.join(root, c, tail, "cpuacct.usage"))
                ),
                None,
            )
            mem = os.path.join(root, "memory", tail)
            if cpu and os.path.exists(os.path.join(mem, "memory.usage_in_bytes")):
                found = ("v1", cpu, mem)
                break
    # only a hit is remembered: a container that just started may not have its cgroup yet
    if found is not None:
        _LAYOUT[cid] = found
    return found


def _host_mem_total(proc: str) -> int:
    if proc not in _HOST_MEM:
        total = 0
        for line in (_read(os.path.join(proc, "meminfo")) or "").splitlines():
            parts = line.split()
            if parts[:1] == ["MemTotal:"] and len(parts) > 1 and parts[1].isdigit():
                total = int(parts[1]) * 1024
                break
        _HOST_MEM[proc] = total
    return _HOST_MEM[proc]


def cpu_and_memory(cid: str, root: str = CGROUP_ROOT, proc: str = HOST_PROC) -> dict[str, int] | None:
    """{cpu_usec, mem_used, mem_limit} for a container (full id), or None when its cgroup is not readable.
    mem_used leaves out page cache the kernel can drop (inactive files), as docker stats does."""
    layout = _layout(cid, root)
    if layout is None:
        return None
    version, cpu_dir, mem_dir = layout
    if version == "v2":
        usec = _kv(_read(os.path.join(cpu_dir, "cpu.stat"))).get("usage_usec")
        current = _read(os.path.join(mem_dir, "memory.current"))
        limit = (_read(os.path.join(mem_dir, "memory.max")) or "").strip()
        stat = _kv(_read(os.path.join(mem_dir, "memory.stat")))
        inactive = stat.get("inactive_file", 0)
    else:
        ns = (_read(os.path.join(cpu_dir, "cpuacct.usage")) or "").strip()
        usec = int(ns) // 1000 if ns.isdigit() else None
        current = _read(os.path.join(mem_dir, "memory.usage_in_bytes"))
        limit = (_read(os.path.join(mem_dir, "memory.limit_in_bytes")) or "").strip()
        stat = _kv(_read(os.path.join(mem_dir, "memory.stat")))
        inactive = stat.get("total_inactive_file", stat.get("inactive_file", 0))
    if usec is None or current is None or not current.strip().isdigit():
        _LAYOUT.pop(cid, None)  # the container went away or was recreated: look again next time
        return None
    host = _host_mem_total(proc)
    mem_limit = int(limit) if limit.isdigit() else host
    if host and mem_limit > host:  # v1 writes "no limit" as a huge number
        mem_limit = host
    return {"cpu_usec": usec, "mem_used": max(0, int(current) - inactive), "mem_limit": mem_limit}


def owns(pid: int, cid: str, proc: str = HOST_PROC) -> bool:
    """Whether process `pid` is still in container `cid` (a restart gives it a new main process, and
    the old number may go to another one). Seen from inside a container, another container's cgroup
    path ends in its id ("0::/../<id>"); our own container's is the root ("0::/")."""
    if not pid:
        return False
    text = _read(os.path.join(proc, str(pid), "cgroup")) or ""
    return cid in text or any(line.endswith("::/") for line in text.splitlines())


def network(pid: int, cid: str, proc: str = HOST_PROC) -> tuple[int, int] | None:
    """(received, sent) bytes over every interface but loopback in the container's own network,
    or None when /proc/<pid> is not that container's process any more."""
    if not owns(pid, cid, proc):
        return None
    text = _read(os.path.join(proc, str(pid), "net", "dev"))
    if text is None:
        return None
    rx = tx = 0
    for line in text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        cols = rest.split()
        if name.strip() == "lo" or len(cols) < 9:
            continue
        rx += int(cols[0])
        tx += int(cols[8])
    return rx, tx


def cpu_percent(cid: str, usec: int, now: float | None = None) -> float | None:
    """CPU % since the last sample of this container (100 = one core busy), or None for the first."""
    now = time.monotonic() if now is None else now
    prev = _PREV.get(cid)
    _PREV[cid] = (now, usec)
    if prev is None or now <= prev[0] or usec < prev[1]:
        return None
    return round((usec - prev[1]) / ((now - prev[0]) * 1e6) * 100.0, 1)


def telemetry(
    cid: str, pid: int, host_network: bool, root: str = CGROUP_ROOT, proc: str = HOST_PROC
) -> dict[str, Any] | None:
    """The same dict docker_stats builds from dockerd's stats, from the kernel's files; None when
    any part is not readable (the caller then asks dockerd) or for a container's first sample (a
    CPU % needs two)."""
    cm = cpu_and_memory(cid, root, proc)
    if cm is None:
        return None
    net = (0, 0) if host_network else network(pid, cid, proc)
    pct = cpu_percent(cid, cm["cpu_usec"])
    if net is None or pct is None:
        return None
    limit = cm["mem_limit"] or 1
    return {
        "cpu_pct": max(0.0, min(1000.0, pct)),
        "mem_used": cm["mem_used"],
        "mem_limit": limit,
        "mem_pct": max(0.0, min(100.0, round(cm["mem_used"] / limit * 100.0, 1))),
        "net_rx": net[0],
        "net_tx": net[1],
        "updated_at": time.time(),
        "source": "cgroup",
    }


def forget(cids_running: set[str]) -> None:
    """Drops what is kept for containers that stopped."""
    for cid in set(_PREV) - cids_running:
        _PREV.pop(cid, None)
    for cid in set(_LAYOUT) - cids_running:
        _LAYOUT.pop(cid, None)
