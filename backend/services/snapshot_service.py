"""Per-share snapshot schedules, file-level browse and restore (Batch 6).

Snapshots are taken by the storage platform (Btrfs/ZFS on generic Linux and ZettOS; the host
on Unraid/TrueNAS in observer mode). Scheduled snapshots are named
"<share>@auto-YYYYMMDD-HHMM", which is also the format Samba's shadow_copy2 reads for
Windows' Previous Versions. Restores copy out of the read-only snapshot, next to the
original by default, so nothing is overwritten unless asked.
"""

import os
import shutil
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json, resolve_within

SCHEDULES_FILE = os.path.join(DATA_DIR, "snapshot_schedules.json")
EVERY = {"hourly": 3600, "daily": 86400, "weekly": 7 * 86400}
AUTO_TAG = "@auto-"
NAME_FORMAT = "%Y%m%d-%H%M"
_LOCK = threading.Lock()


def _pal():
    from backend.hardware.pal_storage import get_storage_platform

    return get_storage_platform()


def _default_pool_id(pal: Any) -> str:
    try:
        pools = pal.list_pools()
        if pools:
            return str(pools[0].id)
    except Exception:
        logger.debug("snapshot_service: pool list failed", exc_info=True)
    return "default"


def availability(pal: Any = None) -> tuple[bool, str]:
    """Whether this host can take snapshots, and why not (REL-4)."""
    try:
        caps = (pal or _pal()).get_capabilities()
    except Exception:
        return True, ""
    if getattr(caps, "can_snapshot", True):
        return True, ""
    from backend.hardware.pal.base import storage_tools_problem

    why = storage_tools_problem()
    if why:
        return False, f"Snapshots aren't available on this host: {why}."
    return False, "Snapshots aren't available on this host: the btrfs and ZFS tools are missing."


def list_schedules() -> list[dict[str, Any]]:
    data = read_json(SCHEDULES_FILE, {})
    return list((data.get("schedules") or {}).values()) if isinstance(data, dict) else []


@json_locked(lambda *a, **k: SCHEDULES_FILE)
def save_schedule(
    share: str, every: str, keep: int, immutable_days: int = 0, pool_id: str | None = None
) -> dict[str, Any]:
    if not share or "/" in share or share.startswith(".") or "@" in share:
        raise ValueError("Pick a share by its name.")
    if every not in EVERY:
        raise ValueError("Snapshots run hourly, daily or weekly.")
    ok, why = availability()
    if not ok:
        raise ValueError(why)
    keep = max(1, min(int(keep), 1000))
    immutable_days = max(0, min(int(immutable_days), 3650))
    with _LOCK:
        data = read_json(SCHEDULES_FILE, {}) or {}
        sched = data.setdefault("schedules", {})
        old = sched.get(share, {})
        sched[share] = {
            "share": share,
            "every": every,
            "keep": keep,
            "immutable_days": immutable_days,
            "pool_id": pool_id or old.get("pool_id"),
            "last_run": old.get("last_run", 0.0),
            "last_result": old.get("last_result", ""),
        }
        atomic_write_json(SCHEDULES_FILE, data)
    _set_previous_versions(share, True)
    return sched[share]


@json_locked(lambda *a, **k: SCHEDULES_FILE)
def delete_schedule(share: str) -> bool:
    with _LOCK:
        data = read_json(SCHEDULES_FILE, {}) or {}
        found = data.get("schedules", {}).pop(share, None) is not None
        if found:
            atomic_write_json(SCHEDULES_FILE, data)
    if found:
        _set_previous_versions(share, False)
    return found


def snapshot_name(share: str, now: float | None = None) -> str:
    return f"{share}{AUTO_TAG}{time.strftime(NAME_FORMAT, time.localtime(now or time.time()))}"


def take(share: str, schedule: dict[str, Any] | None = None, pal: Any = None) -> dict[str, Any]:
    """Takes one snapshot of a share now and prunes old scheduled ones beyond `keep`."""
    pal = pal or _pal()
    schedule = schedule or next((s for s in list_schedules() if s["share"] == share), {"keep": 30, "immutable_days": 0})
    pool_id = schedule.get("pool_id") or _default_pool_id(pal)
    name = snapshot_name(share)
    days = int(schedule.get("immutable_days") or 0)
    kwargs: dict[str, Any] = {"readonly": True}
    if days:
        kwargs.update(worm_mode="governance", retention_days=days)
    res = pal.create_snapshot(pool_id, share, name, **kwargs)
    ok = res.get("status") in ("created", "ok") or res.get("success") is True
    pruned = prune(share, int(schedule.get("keep") or 30), pool_id, pal) if ok else []
    return {
        "share": share,
        "name": name,
        "ok": ok,
        "pruned": pruned,
        "detail": res.get("output") or res.get("error") or "",
    }


def prune(share: str, keep: int, pool_id: str, pal: Any) -> list[str]:
    auto = sorted(
        (s for s in pal.list_snapshots(pool_id) if str(s.get("name", "")).startswith(f"{share}{AUTO_TAG}")),
        key=lambda s: s["name"],
        reverse=True,
    )
    removed = []
    for s in auto[keep:]:
        if s.get("is_immutable"):
            continue
        try:
            pal.delete_snapshot(pool_id, s["name"])
            removed.append(s["name"])
        except Exception as e:
            logger.info(f"[Snapshots] kept {s['name']}: {e}")
    return removed


@json_locked(lambda *a, **k: SCHEDULES_FILE)
def run_due(now: float | None = None, pal: Any = None) -> list[dict[str, Any]]:
    """Called by the scheduler every minute: takes the snapshots that are due."""
    now = now or time.time()
    done = []
    for s in list_schedules():
        if now - float(s.get("last_run") or 0) < EVERY.get(s.get("every", "daily"), 86400):
            continue
        try:
            res = take(s["share"], s, pal=pal)
        except Exception as e:
            res = {"share": s["share"], "ok": False, "detail": str(e)[:200]}
        with _LOCK:
            data = read_json(SCHEDULES_FILE, {}) or {}
            cur = data.get("schedules", {}).get(s["share"])
            if cur is not None:
                cur["last_run"] = now
                cur["last_result"] = "ok" if res.get("ok") else f"failed: {res.get('detail', '')}"[:200]
                atomic_write_json(SCHEDULES_FILE, data)
        done.append(res)
    return done


# --- browse and restore -------------------------------------------------------
def _snapshot(name: str, pal: Any, pool_id: str | None = None) -> dict[str, Any]:
    pool_id = pool_id or _default_pool_id(pal)
    snap = next((s for s in pal.list_snapshots(pool_id) if s.get("name") == name), None)
    if not snap or not snap.get("path"):
        raise FileNotFoundError("No such snapshot.")
    return snap


def _live_root(name: str, pal: Any, pool_id: str) -> str:
    """Where a snapshot's files live today: the share for "<share>@...", else the pool."""
    if "@" in name:
        share = name.split("@", 1)[0]
        try:
            for sh in pal.list_shares():
                if sh.name == share and getattr(sh, "mountpoint", ""):
                    return str(sh.mountpoint)
        except Exception:
            logger.debug("snapshot_service: share lookup failed", exc_info=True)
        pool = pal.get_pool_path(pool_id)
        for cand in (os.path.join(pool, "@shares", share), os.path.join(pool, share)):
            if os.path.isdir(cand):
                return cand
        raise FileNotFoundError("The share this snapshot belongs to no longer exists.")
    return pal.get_pool_path(pool_id)


def browse(
    name: str, rel: str = "", pal: Any = None, pool_id: str | None = None, principal: Any = None
) -> dict[str, Any]:
    """A folder of a snapshot. With a principal, only what that person may open today is listed
    (REL-23): a snapshot is no back door to someone else's folder."""
    pal = pal or _pal()
    snap = _snapshot(name, pal, pool_id)
    root = os.path.realpath(snap["path"])
    target = resolve_within(os.path.join(root, (rel or "").lstrip("/")), root)
    if target is None or not os.path.isdir(target):
        raise FileNotFoundError("No such folder in this snapshot.")
    visible: Callable[[str, bool], bool] | None = None
    if principal is not None:
        from backend.services.path_access import user_can_access_path

        live = _live_root(name, pal, pool_id or _default_pool_id(pal))
        here = os.path.join(live, os.path.relpath(target, root))
        if not user_can_access_path(here, principal, allow_list=True):
            raise PermissionError("You don't have access to this folder.")

        def _visible(entry_name: str, is_dir: bool) -> bool:
            return user_can_access_path(os.path.join(here, entry_name), principal, allow_list=is_dir)

        visible = _visible

    entries = []
    with os.scandir(target) as it:
        for e in it:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            is_dir = e.is_dir(follow_symlinks=False)
            if visible is not None and not visible(e.name, is_dir):
                continue
            entries.append({"name": e.name, "is_dir": is_dir, "size": st.st_size, "mtime": st.st_mtime})
    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return {
        "snapshot": name,
        "path": os.path.relpath(target, root).replace(os.sep, "/").lstrip("."),
        "entries": entries[:5000],
    }


def restore(
    name: str, rel: str, overwrite: bool = False, pal: Any = None, pool_id: str | None = None
) -> dict[str, Any]:
    """Copies a file or folder out of a snapshot. By default it lands beside the original as
    "<name> (restored YYYY-MM-DD HHMM)"; overwrite=True replaces the current version."""
    pal = pal or _pal()
    pool_id = pool_id or _default_pool_id(pal)
    snap = _snapshot(name, pal, pool_id)
    src_root = os.path.realpath(snap["path"])
    src = resolve_within(os.path.join(src_root, rel.lstrip("/")), src_root)
    if not rel.strip("/") or src is None or not os.path.lexists(src):
        raise FileNotFoundError("No such file in this snapshot.")
    live_root = os.path.realpath(_live_root(name, pal, pool_id))
    dest = resolve_within(os.path.join(live_root, rel.lstrip("/")), live_root)
    if dest is None:
        raise PermissionError("That path is outside the share.")
    if os.path.lexists(dest) and not overwrite:
        stem, ext = os.path.splitext(dest) if os.path.isfile(src) else (dest, "")
        dest = f"{stem} (restored {time.strftime('%Y-%m-%d %H%M')}){ext}"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isdir(src) and not os.path.islink(src):
        if os.path.lexists(dest) and overwrite:
            shutil.rmtree(dest)
        shutil.copytree(src, dest, symlinks=True)
    else:
        shutil.copy2(src, dest, follow_symlinks=False)
    return {"restored": os.path.relpath(dest, live_root).replace(os.sep, "/"), "overwrote": overwrite}


def _set_previous_versions(share: str, on: bool) -> None:
    """Windows' Previous Versions for this share, when ZettNAS manages its Samba config."""
    try:
        from backend.services.samba_engine import get_samba_engine

        eng = get_samba_engine()
        cfg = eng.get_share(share)
        if cfg is None or cfg.previous_versions == on:
            return
        cfg.previous_versions = on
        eng.add_or_update_share(cfg)
    except Exception:
        logger.debug("snapshot_service: Samba previous versions not updated", exc_info=True)
