"""Drive Health: every drive's verdict in one call (the app's first page).

Each drive is read the way the S.M.A.R.T. detail reads it, never waking a sleeping one (a
sleeping drive is judged on its stored history), and the result is kept for 30 seconds so an
open window refreshing itself does not run smartctl over and over.
"""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends

from backend.auth import require_scope
from backend.hardware.disks import _discover_disks, fetch_disk_smart_detail
from backend.state import Z_STATE

router = APIRouter(tags=["Drive Health"])

CACHE_SECS = 30
_cache: dict[str, Any] = {"ts": 0.0, "data": None}
ORDER = {"now": 0, "soon": 1, "watch": 2, "unknown": 3, "ok": 4}


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


def _read_all() -> dict[str, Any]:
    disks = [d for d in _discover_disks() if d.get("dev")]
    out = []
    for d in disks:
        try:
            detail = fetch_disk_smart_detail(d["dev"], False)
        except Exception as e:  # one unreadable drive must not hide the others
            detail = {"error": f"{type(e).__name__}: {e}"}
        out.append(_summary(d, detail or {}))
    out.sort(key=lambda r: (ORDER.get(r["verdict"], 3), r["dev"]))
    counts: dict[str, int] = {}
    for r in out:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"drives": out, "counts": counts, "checked_at": time.time()}


@router.get("/drives/health", dependencies=[Depends(require_scope("storage:read", "system:view"))])
async def drives_health(refresh: bool = False) -> dict[str, Any]:
    """Every drive with its verdict, reason and what to do; worst first. Never wakes a drive."""
    if not refresh and _cache["data"] is not None and time.time() - _cache["ts"] < CACHE_SECS:
        return _cache["data"]
    data = await asyncio.to_thread(_read_all)
    _cache.update(ts=time.time(), data=data)
    return data
