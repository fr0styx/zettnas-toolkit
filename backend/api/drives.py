"""Drive Health: every drive's verdict in one call (the app's first page).

Each drive is read the way the S.M.A.R.T. detail reads it, never waking a sleeping one (a
sleeping drive is judged on its stored history). Drives are read side by side, so the page
takes as long as the slowest drive, not the sum of all of them.

Opening the window should feel instant: when every drive has a reading from the last
STALE_SECS (the SMART poller takes one every 30 minutes), the list is answered from those
readings at once, marked "stale", and a fresh read starts in the background; the window
then asks again with refresh=1, which joins that read instead of starting another.
"""

import asyncio
import re
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import require_scope
from backend.hardware.disks import _discover_disks, cached_smart_detail, read_smart_detail
from backend.state import Z_STATE

router = APIRouter(tags=["Drive Health"])

CACHE_SECS = 30  # a reading this young is shown as current
STALE_SECS = 2 * 3600  # a reading this young is shown at once while a fresh one is taken
MAX_PARALLEL = 4
ORDER = {"now": 0, "soon": 1, "watch": 2, "unknown": 3, "ok": 4}
_inflight: dict[str, Any] = {"task": None}


def _summary(disk: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    health = detail.get("drive_health") or {}
    dev = disk.get("dev") or detail.get("dev")
    with Z_STATE.lock:
        active = (Z_STATE.active_smart_tests or {}).get(dev)
    model = detail.get("model") if not detail.get("is_standby") else None
    serial = detail.get("serial") if not detail.get("is_standby") else None
    return {
        "dev": dev,
        "model": model or disk.get("model") or "",
        "serial": serial or disk.get("serial") or "",
        "role": disk.get("role") or "",
        "transport": disk.get("transport") or ("nvme" if str(dev).startswith("nvme") else ""),
        "asleep": bool(detail.get("is_standby")),
        "temp": detail.get("temp"),
        "power_on_hours": detail.get("power_on_hours") if not detail.get("is_standby") else None,
        "capacity_bytes": (health.get("identity") or {}).get("capacity_bytes") or disk.get("size_bytes"),
        "verdict": health.get("verdict", "unknown"),
        "label": health.get("label", "Not read yet"),
        "label_key": health.get("label_key", "unknown"),
        "summary": health.get("summary", ""),
        "summary_key": health.get("summary_key", ""),
        "summary_params": health.get("summary_params") or {},
        "findings": health.get("findings", []),
        "from_history": bool(health.get("from_history")),
        "reading_ts": health.get("reading_ts"),
        "active_test": active,
        "error": detail.get("error"),
    }


def _page(disks: list[dict[str, Any]], details: Sequence[dict[str, Any] | None], stale: bool = False) -> dict[str, Any]:
    out = [_summary(d, det or {}) for d, det in zip(disks, details, strict=True)]
    out.sort(key=lambda r: (ORDER.get(r["verdict"], 3), r["dev"]))
    counts: dict[str, int] = {}
    for r in out:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"drives": out, "counts": counts, "checked_at": time.time(), "stale": stale}


def _disks() -> list[dict[str, Any]]:
    return [d for d in _discover_disks() if d.get("dev")]


def _read_one(dev: str, max_age: float) -> dict[str, Any]:
    return read_smart_detail(dev, False, max_age)  # an unreadable drive comes back as {"error": ...}


def _read_all(max_age: float = 0.0) -> dict[str, Any]:
    disks = _disks()
    if not disks:
        return _page([], [])
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(disks)), thread_name_prefix="DriveHealth") as pool:
        details = list(pool.map(lambda d: _read_one(d["dev"], max_age), disks))
    return _page(disks, details)


def _from_readings(max_age: float) -> dict[str, Any] | None:
    """The page from readings at most max_age old, or None when any drive has none."""
    disks = _disks()
    details = [cached_smart_detail(d["dev"], max_age) for d in disks]
    if not disks or any(det is None for det in details):
        return None
    return _page(disks, details)


def _start_fresh() -> "asyncio.Future[dict[str, Any]]":
    """The fresh read running now on this event loop, or a new one."""
    task = _inflight["task"]
    if task is None or task.done() or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.ensure_future(asyncio.to_thread(_read_all, 0.0))
        _inflight["task"] = task
    return task


async def _fresh() -> dict[str, Any]:
    """One fresh read at a time: a second caller joins the read already running."""
    return await asyncio.shield(_start_fresh())


@router.get("/drives/health", dependencies=[Depends(require_scope("storage:read", "system:view"))])
async def drives_health(refresh: bool = False) -> dict[str, Any]:
    """Every drive with its verdict, reason and what to do; worst first. Never wakes a drive."""
    if refresh:
        return await _fresh()
    current = await asyncio.to_thread(_from_readings, CACHE_SECS)
    if current is not None:
        return current
    older = await asyncio.to_thread(_from_readings, STALE_SECS)
    if older is not None:
        _start_fresh()
        older["stale"] = True
        return older
    return await asyncio.to_thread(_read_all, CACHE_SECS)


@router.get("/drives/history", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def drive_history(dev: str, days: int = 30) -> dict[str, Any]:
    """A drive's temperature and error counters over time, and its age and wear outlook, from the
    stored readings: a sleeping drive is not touched (Drive Health revamp)."""
    from backend.db import get_smart_history_samples
    from backend.services import drive_health

    dev = dev.removeprefix("/dev/")
    if not re.fullmatch(r"(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)", dev):
        raise HTTPException(status_code=400, detail="Invalid device parameter.")
    days = max(1, min(int(days), 45))
    samples = get_smart_history_samples(dev, days=days, bucket_secs=max(3600, days * 86400 // 120))
    return {
        "dev": dev,
        "days": days,
        "history": drive_health.history_view(samples),
        "life": drive_health.life_outlook(samples),
    }
