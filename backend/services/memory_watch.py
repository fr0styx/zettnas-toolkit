"""The backend's own memory over time, and what it holds (hardware budget follow-up).

Every 10 minutes the stats loop records this process's resident memory with its uptime and
PID, kept 30 days in history.db, so slow growth shows across restarts and deploys. A
breakdown on demand counts Python objects by type and, while allocation tracing is on, lists
the code lines that allocated the most.
"""

import collections
import gc
import os
import time
import tracemalloc

from backend.config import logger
from backend.db_crypto import sqlite3

SAMPLE_SECS = 600
KEEP_SECS = 30 * 86400
TRACE_FRAMES = 5
_STARTED = time.time()
_STATE = {"at": 0.0, "pruned": 0.0}


def read_status(path: str = "/proc/self/status") -> dict[str, int]:
    """Resident memory (all, anonymous, file-backed) in kB and the thread count."""
    wanted = {"VmRSS": "rss_kb", "RssAnon": "anon_kb", "RssFile": "file_kb", "Threads": "threads"}
    out = dict.fromkeys(wanted.values(), 0)
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            for line in f:
                key, _, rest = line.partition(":")
                if key in wanted:
                    out[wanted[key]] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        logger.debug("memory_watch: %s unreadable", path, exc_info=True)
    return out


def current(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    return {"ts": int(now), "pid": os.getpid(), "uptime_s": int(now - _STARTED), **read_status()}


def sample(now: float | None = None, read=current) -> dict | None:
    """Records one sample when SAMPLE_SECS have passed since the last; returns it, or None."""
    from backend.db import history_session

    now = time.time() if now is None else now
    if now - _STATE["at"] < SAMPLE_SECS:
        return None
    _STATE["at"] = now
    row = read(now)
    try:
        with history_session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO memory_samples (ts, pid, uptime_s, rss_kb, anon_kb, file_kb, threads)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row["ts"], row["pid"], row["uptime_s"], row["rss_kb"], row["anon_kb"], row["file_kb"], row["threads"]),
            )
            if now - _STATE["pruned"] >= 3600:
                conn.execute("DELETE FROM memory_samples WHERE ts < ?", (int(now - KEEP_SECS),))
                _STATE["pruned"] = now
    except (OSError, sqlite3.Error):
        logger.debug("memory_watch: sample not saved", exc_info=True)
        return None
    return row


def history(hours: int = 168, now: float | None = None) -> list[dict]:
    from backend.db import db_read_session

    now = time.time() if now is None else now
    since = int(now - max(1, min(24 * 30, hours)) * 3600)
    with db_read_session() as conn:
        rows = conn.execute(
            "SELECT ts, pid, uptime_s, rss_kb, anon_kb, file_kb, threads FROM memory_samples WHERE ts >= ? ORDER BY ts",
            (since,),
        ).fetchall()
    keys = ("ts", "pid", "uptime_s", "rss_kb", "anon_kb", "file_kb", "threads")
    return [dict(zip(keys, r, strict=True)) for r in rows]


def growth(rows: list[dict]) -> list[dict]:
    """Per run between restarts: first and last sample and the growth per hour. A run ends where
    the PID changes or the uptime goes back down (in a container the backend is always PID 1)."""
    runs: list[list[dict]] = []
    for r in sorted(rows, key=lambda r: r["ts"]):
        last = runs[-1][-1] if runs else None
        if last is None or r["pid"] != last["pid"] or r["uptime_s"] < last["uptime_s"]:
            runs.append([r])
        else:
            runs[-1].append(r)
    out = []
    for rs in runs:
        first, last = rs[0], rs[-1]
        hours = (last["ts"] - first["ts"]) / 3600
        out.append(
            {
                "pid": first["pid"],
                "from_ts": first["ts"],
                "to_ts": last["ts"],
                "uptime_s": last["uptime_s"],
                "rss_kb_first": first["rss_kb"],
                "rss_kb_last": last["rss_kb"],
                "kb_per_hour": round((last["rss_kb"] - first["rss_kb"]) / hours) if hours >= 1 else None,
            }
        )
    return out


def object_counts(limit: int = 25, objects=None) -> list[dict]:
    """The Python object types the process holds most of (a full gc walk: on demand only)."""
    objs = gc.get_objects() if objects is None else objects
    counts = collections.Counter(type(o).__qualname__ for o in objs)
    return [{"type": name, "count": n} for name, n in counts.most_common(limit)]


def tracing() -> bool:
    return tracemalloc.is_tracing()


def set_tracing(on: bool) -> bool:
    """Allocation tracing costs memory and time while on, so it is off unless asked for."""
    if on and not tracemalloc.is_tracing():
        tracemalloc.start(TRACE_FRAMES)
        logger.info("memory_watch: allocation tracing on")
    elif not on and tracemalloc.is_tracing():
        tracemalloc.stop()
        logger.info("memory_watch: allocation tracing off")
    return tracemalloc.is_tracing()


def top_allocations(limit: int = 25) -> list[dict]:
    """While tracing: the code lines holding the most memory allocated since tracing began."""
    if not tracemalloc.is_tracing():
        return []
    stats = tracemalloc.take_snapshot().statistics("lineno")
    out = []
    for s in stats[:limit]:
        frame = s.traceback[0]
        out.append({"where": f"{frame.filename}:{frame.lineno}", "kb": round(s.size / 1024), "blocks": s.count})
    return out


def breakdown(limit: int = 25) -> dict:
    return {
        "now": current(),
        "objects": object_counts(limit),
        "tracing": tracing(),
        "allocations": top_allocations(limit),
    }
