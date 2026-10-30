"""Where chunked uploads keep their parts (NARC-9): each upload's staging folder and temporary
file are noted here, in the data folder, so that what an update, a crash or a closed laptop
leaves behind in a share is found and removed, without walking any share.

An entry is swept when it was made before this process started (its upload can't go on: the
sessions live in memory) or when it is older than a day. A disk that is asleep is left alone
until it is awake.
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, locked_json, read_json

INDEX = os.path.join(DATA_DIR, "upload_staging.json")
TTL_S = 24 * 3600
SWEEP_EVERY_S = 3600
PROCESS_START = time.time()
_last_sweep = [0.0]


def _load() -> dict[str, Any]:
    data = read_json(INDEX, {}) or {}
    return data if isinstance(data, dict) else {}


def note(upload_id: str, paths: list[str], now: float | None = None) -> None:
    """Remembers an upload's staging folder and temporary file until it ends."""
    with locked_json(INDEX):
        data = _load()
        data[upload_id] = {"paths": [p for p in paths if p], "at": time.time() if now is None else now}
        atomic_write_json(INDEX, data)


def forget(upload_id: str) -> None:
    with locked_json(INDEX):
        data = _load()
        if data.pop(upload_id, None) is not None:
            atomic_write_json(INDEX, data)


def _asleep(path: str) -> bool:
    try:
        from backend.services.rag_standby import is_backing_disk_in_standby

        return bool(is_backing_disk_in_standby(os.path.dirname(path)))
    except (ImportError, OSError, ValueError):
        return False


def _remove(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        os.unlink(path)


def sweep(now: float | None = None, force: bool = False) -> list[str]:
    """Removes the parts of uploads that can't finish any more; returns their upload ids."""
    now = time.time() if now is None else now
    if not force and now - _last_sweep[0] < SWEEP_EVERY_S:
        return []
    _last_sweep[0] = now
    gone = []
    with locked_json(INDEX):
        data = _load()
        for upload_id, entry in list(data.items()):
            at = float(entry.get("at") or 0)
            if at >= PROCESS_START and now - at < TTL_S:
                continue  # may still be going on
            paths = [str(p) for p in entry.get("paths") or [] if ".zettnas_" in os.path.basename(str(p))]
            if any(_asleep(p) for p in paths):
                continue  # next time, once the disk is awake
            try:
                for p in paths:
                    _remove(p)
            except OSError as e:
                logger.warning("[Uploads] Could not remove what upload %s left: %s", upload_id, e)
                continue
            data.pop(upload_id, None)
            gone.append(upload_id)
        if gone:
            atomic_write_json(INDEX, data)
    if gone:
        logger.info("[Uploads] Removed what %d unfinished upload(s) left in shares", len(gone))
    return gone
