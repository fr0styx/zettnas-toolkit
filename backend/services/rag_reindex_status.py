"""Progress of a re-embedding run, for the AI settings page and the live stats (ARCH-2)."""

import os
from typing import Any

from backend.config import logger
from backend.ignored_errors import ignored
from backend.services.rag_engine import get_rag_engine

REINDEX_STATUS: dict[str, Any] = {
    "status": "idle",
    "completed": 0,
    "total": 0,
    "speed": 0.0,
    "eta_sec": 0.0,
    "percentage": 0.0,
}


_REINDEX_CACHE: dict[str, Any] = {"status": "idle"}
_REINDEX_CACHE_TIME: float = 0.0
IDLE_RECHECK_SECS = 15.0
_REINDEX_KEY = ""  # the in-process status the cached answer was built from


def get_reindex_status() -> dict[str, Any]:
    global _REINDEX_CACHE, _REINDEX_CACHE_TIME
    import json
    import time

    now = time.time()
    if (now - _REINDEX_CACHE_TIME) < 2.0 and _REINDEX_CACHE.get("status") == "running":
        return dict(_REINDEX_CACHE)
    global _REINDEX_KEY
    key = repr(sorted(REINDEX_STATUS.items(), key=lambda kv: str(kv[0])))
    if (
        _REINDEX_CACHE
        and (now - _REINDEX_CACHE_TIME) < IDLE_RECHECK_SECS
        and _REINDEX_CACHE.get("status") != "running"
        and REINDEX_STATUS.get("status") != "running"
        and key == _REINDEX_KEY
    ):
        # PERF-5: idle, so the progress file is read every 15 s; any change to the in-process
        # status (a run started, finished or failed) is seen at once
        return dict(_REINDEX_CACHE)
    _REINDEX_KEY = key

    # 1. Check persistent progress file on disk (shared across CLI and web server)
    from backend import config as _cfg

    progress_file = os.path.join(_cfg.DATA_DIR, "reindex_progress.json")
    if os.path.exists(progress_file):
        try:
            with open(progress_file) as f:
                data = json.load(f)
            if data.get("status") == "running":
                mtime = os.path.getmtime(progress_file)
                if (time.time() - mtime) < 90:
                    _REINDEX_CACHE = data
                    _REINDEX_CACHE_TIME = now
                    return data
                data["status"] = "idle"
            _REINDEX_CACHE = data
            _REINDEX_CACHE_TIME = now
            return data
        except Exception:
            ignored("backend.services.rag_reindex_status.get_reindex_status")

    # 2. Check in-memory task status
    if REINDEX_STATUS.get("status") == "running":
        _REINDEX_CACHE = dict(REINDEX_STATUS)
        _REINDEX_CACHE_TIME = now
        return dict(REINDEX_STATUS)

    # 3. Dynamic SQLite detection: detect if a CLI reindex or background job is running
    try:
        rag = get_rag_engine()
        with rag._write_lock:
            conn = rag._get_conn(readonly=True)
            from backend.services.rag_engine import vec_table

            table = vec_table(getattr(rag, "_vec_table_dim", 768))
            has_vec = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if has_vec:
                c_vec = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                total = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
                if 0 < c_vec < total:
                    pct = round((c_vec / total) * 100, 1)
                    speed = 2.6
                    eta_sec = round((total - c_vec) / speed, 1)
                    res = {
                        "status": "running",
                        "completed": c_vec,
                        "total": total,
                        "speed": speed,
                        "eta_sec": eta_sec,
                        "percentage": pct,
                        "source": "cli_or_background",
                        "updated_at": now,
                    }
                    _REINDEX_CACHE = res
                    _REINDEX_CACHE_TIME = now
                    return res
            conn.close()
    except Exception:
        ignored("backend.services.rag_reindex_status.get_reindex_status")

    _REINDEX_CACHE = dict(REINDEX_STATUS)
    _REINDEX_CACHE_TIME = now
    return dict(REINDEX_STATUS)
