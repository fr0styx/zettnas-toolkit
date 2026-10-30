"""Two-way sync between a folder here and a cloud folder, with a dry run first (FEAT-06).

rclone bisync keeps both sides the same: a file added, changed or deleted on either side goes to
the other. A file changed on both sides since the last run is kept twice, as name..path1 (this
NAS) and name..path2 (the cloud), so nothing is lost silently.

Nothing runs until someone has seen what it would do: a new or changed pair is first run with
--dry-run and the planned copies, deletions and conflicts are shown; only after that is approved
does it run for real. The first real run (--resync) only copies, never deletes. Every run stops
when more than max_delete percent of the files would be deleted (rclone's --max-delete), skips
while the ransomware guard has frozen writes, and waits when the folder's disk is asleep.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, RCLONE_CONFIG_FILE, logger
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.proc import run_bounded

PAIRS_FILE = os.path.join(DATA_DIR, "two_way_sync.json")
WORKDIR = os.path.join(DATA_DIR, "bisync")
PREVIEW_VALID_SECS = 24 * 3600
RUN_TIMEOUT = 6 * 3600
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_RUNNING: set[str] = set()
_LOCK = threading.Lock()


def _pairs() -> dict[str, dict[str, Any]]:
    return (read_json(PAIRS_FILE, {}) or {}).get("pairs") or {}


def _save(pairs: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(PAIRS_FILE, {"pairs": pairs})


def list_pairs() -> list[dict[str, Any]]:
    return [{**p, "running": p["id"] in _RUNNING} for p in _pairs().values()]


def get_pair(pair_id: str) -> dict[str, Any]:
    p = _pairs().get(pair_id)
    if not p:
        raise KeyError("No such sync.")
    return p


@json_locked(lambda *a, **k: PAIRS_FILE)
def _update(pair_id: str, **fields: Any) -> dict[str, Any]:
    pairs = _pairs()
    if pair_id not in pairs:
        raise KeyError("No such sync.")
    pairs[pair_id].update(fields)
    _save(pairs)
    return pairs[pair_id]


@json_locked(lambda *a, **k: PAIRS_FILE)
def save_pair(
    pair_id: str,
    name: str,
    local: str,
    remote: str,
    every_hours: int = 6,
    max_delete: int = 25,
    check: Callable[[str], str] | None = None,
    new: bool = False,
) -> dict[str, Any]:
    """Adds or changes a pair. New places mean a new dry run and a new first run. A new pair whose
    id is taken gets a free one (sync-2, sync-3, ...): it never replaces another (NUX-6)."""
    if not _ID.match(pair_id or ""):
        raise ValueError("Use lowercase letters, digits and dashes for the id.")
    if check is None:
        from backend.services.rclone_engine import get_rclone_engine

        check = get_rclone_engine().checked_location
    local_ok, remote_ok = check(local), check(remote)
    if not local_ok.startswith("/"):
        raise ValueError("The first side is a folder on this NAS.")
    if remote_ok.startswith("/"):
        raise ValueError("The second side is a cloud folder (remote:path).")
    pairs = _pairs()
    if new:
        base, n = pair_id[:36], 2
        while pair_id in pairs:
            pair_id, n = f"{base}-{n}", n + 1
    old = pairs.get(pair_id, {})
    same = old.get("local") == local_ok and old.get("remote") == remote_ok
    pairs[pair_id] = {
        "id": pair_id,
        "name": name or pair_id,
        "local": local_ok,
        "remote": remote_ok,
        "every_hours": max(1, min(int(every_hours or 6), 168)),
        "max_delete": max(1, min(int(max_delete or 25), 100)),
        "state": old.get("state", "new") if same else "new",
        "baseline": bool(old.get("baseline")) and same,
        "preview": old.get("preview") if same else None,
        "last_run": old.get("last_run") if same else None,
        "last_result": old.get("last_result", "") if same else "",
        "created_at": old.get("created_at") or time.time(),
    }
    _save(pairs)
    return pairs[pair_id]


@json_locked(lambda *a, **k: PAIRS_FILE)
def delete_pair(pair_id: str) -> bool:
    pairs = _pairs()
    found = pairs.pop(pair_id, None) is not None
    if found:
        _save(pairs)
    return found


def command(pair: dict[str, Any], dry_run: bool) -> list[str]:
    cmd = [
        "rclone",
        "bisync",
        pair["local"],
        pair["remote"],
        "--config",
        RCLONE_CONFIG_FILE,
        "--workdir",
        WORKDIR,
        "--max-delete",
        str(pair.get("max_delete") or 25),
        "-v",
    ]
    if not pair.get("baseline"):
        cmd.append("--resync")  # the first run: _newer_wins has made both sides equal before it
    if dry_run:
        cmd.append("--dry-run")
    return cmd


_COUNT = {
    "to_remote": re.compile(r"Queue copy to Path2\s+-\s+(.+)$"),
    "to_local": re.compile(r"Queue copy to Path1\s+-\s+(.+)$"),
    "delete_remote": re.compile(r"-\s+Path2\s+Queue delete\s+-\s+(.+)$"),
    "delete_local": re.compile(r"-\s+Path1\s+Queue delete\s+-\s+(.+)$"),
    "conflicts": re.compile(r"New or changed in both paths\s+-\s+(.+)$"),
}
_SKIPPED = re.compile(r"NOTICE: (.+?): Skipped (?:copy|update modification time) as --dry-run is set")


def parse(text: str) -> dict[str, Any]:
    """Counts and the first files of each kind from bisync's -v output (normal and --resync)."""
    out: dict[str, Any] = {k: [] for k in _COUNT}
    phase = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if "Copying unique Path2 files to Path1" in line:
            phase = "to_local"
        elif "Resynching Path1 to Path2" in line:
            phase = "to_remote"
        m = _SKIPPED.search(line)
        if m and phase:
            out[phase].append(m.group(1).strip())
            continue
        for key, rx in _COUNT.items():
            m = rx.search(line)
            if m:
                out[key].append(m.group(1).strip().removeprefix("{path1/}").removeprefix("{path2/}"))
                break
    summary: dict[str, Any] = {k: len(v) for k, v in out.items()}
    summary["files"] = {k: v[:20] for k, v in out.items() if v}
    summary["too_many_deletes"] = "too many deletes" in (text or "").lower() or "safety abort" in (text or "").lower()
    return summary


def _blocked(pair: dict[str, Any]) -> str | None:
    try:
        from backend.services.ransomware_guard import writes_frozen

        if writes_frozen():
            return "Writes are frozen by the ransomware guard"
    except ImportError:
        logger.debug("two_way_sync: no ransomware guard", exc_info=True)
    try:
        from backend.services.rag_standby import is_backing_disk_in_standby

        if is_backing_disk_in_standby(pair["local"]):
            return "The folder's disk is asleep; the sync waits until it wakes"
    except (ImportError, OSError, ValueError):
        logger.debug("two_way_sync: standby check failed", exc_info=True)
    return None


def _newer_wins(pair: dict[str, Any], run: Callable) -> str | None:
    """Before a first run (or one after bisync lost track): each side's newer files are copied to
    the other, nothing is deleted. bisync --resync then finds them equal, so it can't overwrite edits
    made in the cloud with this NAS's older copy, which it would otherwise do (NREL-12; the rclone in
    the image predates --resync-mode newer). Returns why it failed, or None."""
    for src, dst in ((pair["local"], pair["remote"]), (pair["remote"], pair["local"])):
        cmd = ["rclone", "copy", src, dst, "--update", "--config", RCLONE_CONFIG_FILE, "-v"]
        res = run(cmd, timeout=RUN_TIMEOUT, capture_output=True, text=True)
        if res.returncode != 0:
            text = (res.stdout or "") + (res.stderr or "")
            tail = [line for line in text.splitlines() if "ERROR" in line]
            return (tail[-1] if tail else f"rclone copy exited with {res.returncode}")[-300:]
    return None


def _run(pair: dict[str, Any], dry_run: bool, run: Callable = run_bounded) -> dict[str, Any]:
    os.makedirs(WORKDIR, exist_ok=True)
    if not dry_run and not pair.get("baseline"):
        failed = _newer_wins(pair, run)
        if failed:
            return {**parse(""), "ok": False, "error": failed}
    res = run(command(pair, dry_run), timeout=RUN_TIMEOUT if not dry_run else 1800, capture_output=True, text=True)
    text = (res.stdout or "") + (res.stderr or "")
    summary = parse(text)
    summary["ok"] = res.returncode == 0
    if res.returncode != 0:
        tail = [
            line
            for line in text.splitlines()
            if "ERROR" in line or "Bisync critical error" in line or "aborted" in line.lower()
        ]
        summary["error"] = (tail[-1] if tail else f"rclone bisync exited with {res.returncode}")[-300:]
    return summary


def preview(pair_id: str, run: Callable = run_bounded) -> dict[str, Any]:
    """The dry run: what the next real run would copy, delete and keep twice."""
    pair = get_pair(pair_id)
    summary = {**_run(pair, True, run), "at": time.time(), "first_run": not pair.get("baseline")}
    _update(pair_id, preview=summary, state="previewed" if summary["ok"] else "new")
    return summary


def approve(pair_id: str) -> dict[str, Any]:
    """Turns a pair on after its dry run was seen; a stale or failed dry run must be redone."""
    pair = get_pair(pair_id)
    p = pair.get("preview") or {}
    if pair.get("state") not in ("previewed", "active") or not p.get("ok"):
        raise ValueError("Run the preview first and check what it would do.")
    if time.time() - float(p.get("at") or 0) > PREVIEW_VALID_SECS:
        raise ValueError("The preview is more than a day old; run it again.")
    return _update(pair_id, state="active")


def run_now(pair_id: str, run: Callable = run_bounded) -> dict[str, Any]:
    """One real run of an approved pair."""
    pair = get_pair(pair_id)
    if pair.get("state") != "active":
        raise ValueError("Preview and approve this sync before it runs.")
    why = _blocked(pair)
    if why:
        return _update(pair_id, last_result=why)
    with _LOCK:
        if pair_id in _RUNNING:
            raise ValueError("This sync is already running.")
        _RUNNING.add(pair_id)
    try:
        summary = _run(pair, False, run)
    finally:
        with _LOCK:
            _RUNNING.discard(pair_id)
    fields: dict[str, Any] = {"last_run": time.time(), "last_summary": summary}
    if summary["ok"]:
        fields.update(baseline=True, last_result="ok")
    elif summary["too_many_deletes"]:
        # a sudden mass delete on one side: stop and ask, never pass it on (FEAT-06)
        fields.update(
            state="previewed",
            last_result=f"Stopped: more than {pair['max_delete']}% of the files would be deleted. Check the preview.",
        )
        _notify(pair, fields["last_result"])
    elif "--resync" in (summary.get("error") or ""):
        # bisync lost its listings (interrupted run): a new preview and first run (copies only)
        fields.update(baseline=False, state="new", last_result="The sync lost track of the last run; preview it again.")
        _notify(pair, fields["last_result"])
    else:
        fields.update(last_result=summary.get("error") or "failed")
    logger.info("[Sync] %s: %s", pair["name"], fields.get("last_result"))
    return _update(pair_id, **fields)


def _notify(pair: dict[str, Any], message: str) -> None:
    try:
        from backend.services.notifications import send_notification

        send_notification(
            {"type": "backup", "title": f"Sync {pair['name']} stopped", "message": message, "level": "warning"}
        )
    except (ImportError, OSError, ValueError):
        logger.debug("two_way_sync: notification failed", exc_info=True)


def run_due(now: float | None = None, start: Callable[[str], Any] | None = None) -> list[str]:
    """Starts every active pair whose interval has passed (called once a minute)."""
    now = now or time.time()
    started = []
    for p in _pairs().values():
        if p.get("state") != "active" or p["id"] in _RUNNING:
            continue
        if now - float(p.get("last_run") or 0) < p.get("every_hours", 6) * 3600:
            continue
        started.append(p["id"])
        if start:
            start(p["id"])
        else:
            threading.Thread(target=_safe_run, args=(p["id"],), daemon=True, name=f"Sync-{p['id']}").start()
    return started


def _safe_run(pair_id: str) -> None:
    try:
        run_now(pair_id)
    except (KeyError, ValueError, OSError) as e:
        logger.warning("[Sync] %s: %s", pair_id, e)
