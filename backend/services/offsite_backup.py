"""Versioned, deduplicated, encrypted offsite backup with restic (Batch 6).

A repository is a folder (a USB disk, another NAS) or an rclone remote ("rclone:name:path",
using ZettNAS's rclone config, so every cloud rclone supports works). restic encrypts
everything with the repository key, stores each file once however many versions exist, and
keeps the versions the retention rules ask for. The key lives in the data folder; without it
the backup can't be read, so the interface offers it for safe keeping.
"""

import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from typing import Any

from backend import config
from backend.config import DATA_DIR, RCLONE_CONFIG_FILE, logger
from backend.fsutil import atomic_write_json, read_json, resolve_within

REPOS_FILE = os.path.join(DATA_DIR, "offsite_repos.json")
KEY_DIR = os.path.join(DATA_DIR, "offsite_keys")
DEFAULT_KEEP = {"daily": 7, "weekly": 4, "monthly": 12}
_LOCK = threading.Lock()
_RUNNING: dict[str, subprocess.Popen] = {}
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


class ResticError(RuntimeError):
    pass


def _in_storage(path: str) -> bool:
    """True for paths inside the storage folders (pool, remotes, disks); never the app or system."""
    return resolve_within(path, config.ALLOWED_BROWSE_ROOTS) is not None


def restic_available() -> bool:
    return shutil.which("restic") is not None


def _repos() -> dict[str, dict[str, Any]]:
    data = read_json(REPOS_FILE, {}) or {}
    return data.get("repos") or {}


def _save(repos: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(REPOS_FILE, {"repos": repos})


def _key_file(repo_id: str) -> str:
    return os.path.join(KEY_DIR, f"{repo_id}.key")


def list_repos() -> list[dict[str, Any]]:
    return list(_repos().values())


def get_repo(repo_id: str) -> dict[str, Any]:
    repo = _repos().get(repo_id)
    if not repo:
        raise KeyError("No such backup.")
    return repo


def save_repo(
    repo_id: str, name: str, location: str, paths: list[str], keep: dict[str, int] | None = None, hour: int | None = 2
) -> dict[str, Any]:
    if not _ID.match(repo_id or ""):
        raise ValueError("Use lowercase letters, digits and dashes for the id.")
    if not location or not (location.startswith("/") or location.startswith("rclone:")):
        raise ValueError("The destination is a folder (/mnt/disks/usb/backup) or an rclone remote (rclone:name:path).")
    if location.startswith("/") and not _in_storage(location):
        raise ValueError("A folder destination must be on the storage (for example a USB disk under /mnt/disks).")
    clean_paths = [p for p in (paths or []) if p.startswith("/") and ".." not in p.split("/") and _in_storage(p)]
    if not clean_paths:
        raise ValueError("Choose at least one folder on the storage to back up.")
    k = {**DEFAULT_KEEP, **{x: max(0, min(int(v), 1000)) for x, v in (keep or {}).items() if x in DEFAULT_KEEP}}
    with _LOCK:
        repos = _repos()
        old = repos.get(repo_id, {})
        repos[repo_id] = {
            "id": repo_id,
            "name": name or repo_id,
            "location": location,
            "paths": clean_paths,
            "keep": k,
            "hour": None if hour is None else max(0, min(int(hour), 23)),
            "initialized": old.get("initialized", False),
            "last_backup": old.get("last_backup"),
            "last_check": old.get("last_check"),
            "last_result": old.get("last_result", ""),
            "last_drill": old.get("last_drill"),
            "last_drill_result": old.get("last_drill_result", ""),
            "created_at": old.get("created_at") or time.time(),
            "kit_saved_at": old.get("kit_saved_at"),
        }
        _save(repos)
    return repos[repo_id]


def delete_repo(repo_id: str) -> bool:
    """Forgets the backup in ZettNAS. The repository and its key file stay where they are."""
    with _LOCK:
        repos = _repos()
        found = repos.pop(repo_id, None) is not None
        if found:
            _save(repos)
    return found


def _env(repo: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "RESTIC_REPOSITORY": repo["location"],
            "RESTIC_PASSWORD_FILE": _key_file(repo["id"]),
            "RCLONE_CONFIG": RCLONE_CONFIG_FILE,
            "RESTIC_CACHE_DIR": os.path.join(DATA_DIR, "restic_cache"),
        }
    )
    env.pop("RESTIC_PASSWORD", None)
    return env


def run_restic(repo: dict[str, Any], args: list[str], timeout: int = 6 * 3600, track: bool = False) -> str:
    if not restic_available():
        raise ResticError("restic is not installed in this image.")
    cmd = ["restic", *args]
    proc = subprocess.Popen(cmd, env=_env(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if track:
        _RUNNING[repo["id"]] = proc
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise ResticError("restic took too long and was stopped.") from None
    finally:
        _RUNNING.pop(repo["id"], None)
    if proc.returncode != 0:
        raise ResticError((err or out or f"restic exited with {proc.returncode}").strip().splitlines()[-1][:300])
    return out


def init(repo_id: str) -> dict[str, Any]:
    repo = get_repo(repo_id)
    os.makedirs(KEY_DIR, mode=0o700, exist_ok=True)
    key = _key_file(repo_id)
    if not os.path.exists(key):
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    if repo["location"].startswith("/"):
        os.makedirs(repo["location"], exist_ok=True)
    try:
        run_restic(repo, ["init"], timeout=600)
    except ResticError as e:
        if "already" not in str(e) and "exists" not in str(e):
            raise
    _update(repo_id, initialized=True)
    return {"initialized": True}


def recovery_key(repo_id: str) -> str:
    get_repo(repo_id)
    with open(_key_file(repo_id), encoding="utf-8") as f:
        return f.read().strip()


def _rclone_section(remote: str) -> str:
    """The rclone settings of one remote, as rclone.conf text (empty when unknown)."""
    import configparser

    cp = configparser.RawConfigParser()
    try:
        cp.read(RCLONE_CONFIG_FILE, encoding="utf-8")
    except (OSError, configparser.Error):
        return ""
    if not cp.has_section(remote):
        return ""
    lines = [f"[{remote}]"] + [f"{k} = {v}" for k, v in cp.items(remote)]
    return "\n".join(lines)


def recovery_kit(repo_id: str) -> str:
    """Everything needed to read this backup on another computer, with plain restic (REL-17):
    the key, where the backup is, the cloud settings it needs, and the commands."""
    repo = get_repo(repo_id)
    key = recovery_key(repo_id)
    loc = repo["location"]
    lines = [
        "ZettNAS off-site backup: recovery kit",
        "Keep this outside the NAS (a password manager, a USB stick in a drawer, or printed).",
        "Anyone with this kit can read the backup.",
        "",
        f"Name: {repo.get('name') or repo_id}",
        f"Backup location: {loc}",
        f"Recovery key: {key}",
        f"Folders in it: {', '.join(repo.get('paths') or [])}",
        "",
    ]
    rclone_conf = ""
    if loc.startswith("rclone:"):
        remote = loc.split(":", 2)[1] if loc.count(":") >= 2 else ""
        rclone_conf = _rclone_section(remote)
    lines += [
        "To get your files back on any computer:",
        "  1. Install restic (https://restic.net)" + (" and rclone (https://rclone.org)." if rclone_conf else "."),
    ]
    if rclone_conf:
        lines += ["  2. Save the cloud settings below as rclone.conf, then: export RCLONE_CONFIG=./rclone.conf"]
    step = 3 if rclone_conf else 2
    lines += [
        f"  {step}. export RESTIC_PASSWORD='{key}'",
        f"  {step + 1}. See the versions: restic -r '{loc}' snapshots",
        f"  {step + 2}. Restore the newest: restic -r '{loc}' restore latest --target ./restored",
        "",
        "To restore the whole server on new hardware, see 'Recover on new hardware' in BACKUP_GUIDE.md.",
    ]
    if rclone_conf:
        lines += ["", "----- rclone.conf -----", rclone_conf, "-----------------------"]
    return "\n".join(lines) + "\n"


def mark_kit_saved(repo_id: str) -> float:
    """The person downloaded or copied the kit (REL-17)."""
    with _LOCK:
        repos = _repos()
        if repo_id not in repos:
            raise KeyError("No such backup.")
        now = time.time()
        repos[repo_id]["kit_saved_at"] = now
        _save(repos)
    return now


def kits_not_saved() -> list[dict[str, Any]]:
    """Set-up backups whose recovery kit nobody saved yet."""
    return [
        {"id": r["id"], "name": r.get("name") or r["id"]}
        for r in list_repos()
        if r.get("initialized") and not r.get("kit_saved_at")
    ]


def backup(repo_id: str, owner: str | None = None) -> dict[str, Any]:
    """Backs up the repository's folders, then applies the retention rules."""
    repo = get_repo(repo_id)
    if not repo.get("initialized"):
        init(repo_id)
    from backend.services.jobs import job_manager

    job = job_manager.register("backup", f"Offsite backup: {repo['name']}", owner=owner, cancel=lambda: cancel(repo_id))
    try:
        out = run_restic(repo, ["backup", "--json", "--tag", "zettnas", *repo["paths"]], track=True)
        summary = next(
            (
                json.loads(line)
                for line in reversed(out.splitlines())
                if '"message_type":"summary"' in line.replace(" ", "")
            ),
            {},
        )
        k = repo["keep"]
        run_restic(
            repo,
            [
                "forget",
                "--prune",
                "--tag",
                "zettnas",
                "--keep-daily",
                str(k["daily"]),
                "--keep-weekly",
                str(k["weekly"]),
                "--keep-monthly",
                str(k["monthly"]),
            ],
        )
        result = {
            "snapshot": summary.get("snapshot_id", "")[:8],
            "files_new": summary.get("files_new", 0),
            "files_changed": summary.get("files_changed", 0),
            "data_added": summary.get("data_added", 0),
        }
        _update(repo_id, last_backup=time.time(), last_result="ok")
        job_manager.finish(job.id, "done")
        return result
    except ResticError as e:
        _update(repo_id, last_result=f"failed: {e}"[:300])
        job_manager.finish(job.id, "error", error=str(e))
        raise


def cancel(repo_id: str) -> bool:
    proc = _RUNNING.get(repo_id)
    if proc:
        proc.terminate()
        return True
    return False


def snapshots(repo_id: str) -> list[dict[str, Any]]:
    repo = get_repo(repo_id)
    out = run_restic(repo, ["snapshots", "--json"], timeout=600)
    snaps = json.loads(out or "[]")
    return [
        {
            "id": s.get("short_id") or s["id"][:8],
            "time": s.get("time"),
            "paths": s.get("paths", []),
            "hostname": s.get("hostname"),
        }
        for s in sorted(snaps, key=lambda s: s.get("time", ""), reverse=True)
    ]


def browse(repo_id: str, snapshot_id: str, path: str = "/") -> list[dict[str, Any]]:
    """Entries directly inside `path` of a backup version."""
    repo = get_repo(repo_id)
    if not re.fullmatch(r"[0-9a-f]{6,64}|latest", snapshot_id):
        raise ValueError("Pick a backup version.")
    path = "/" + path.strip("/")
    out = run_restic(repo, ["ls", "--json", snapshot_id, path], timeout=600)
    entries = []
    for line in out.splitlines():
        try:
            node = json.loads(line)
        except ValueError:
            continue
        if node.get("struct_type") != "node":
            continue
        p = node.get("path", "")
        if os.path.dirname(p.rstrip("/")) != path.rstrip("/") and not (path == "/" and p.count("/") == 1):
            continue
        entries.append(
            {
                "name": node.get("name"),
                "path": p,
                "is_dir": node.get("type") == "dir",
                "size": node.get("size", 0),
                "mtime": node.get("mtime"),
            }
        )
    return sorted(entries, key=lambda e: (not e["is_dir"], str(e["name"]).lower()))


def restore(repo_id: str, snapshot_id: str, path: str, target: str) -> dict[str, Any]:
    """Restores one file or folder of a backup version into `target` (a folder that gets the
    original path below it), never over the live files."""
    repo = get_repo(repo_id)
    if not re.fullmatch(r"[0-9a-f]{6,64}|latest", snapshot_id):
        raise ValueError("Pick a backup version.")
    if not target.startswith("/") or ".." in target.split("/") or not _in_storage(target):
        raise ValueError("Restore into a folder on the storage.")
    os.makedirs(target, exist_ok=True)
    run_restic(repo, ["restore", snapshot_id, "--target", target, "--include", "/" + path.strip("/")])
    return {"restored_to": os.path.join(target, path.strip("/"))}


def check(repo_id: str, read_percent: int = 5) -> dict[str, Any]:
    """Verifies the repository's structure and reads back a sample of the data."""
    repo = get_repo(repo_id)
    pct = max(1, min(int(read_percent), 100))
    try:
        run_restic(repo, ["check", f"--read-data-subset={pct}%"])
    except ResticError as e:
        _update(repo_id, last_check=time.time(), last_result=f"check failed: {e}"[:300])
        raise
    _update(repo_id, last_check=time.time(), last_result="ok")
    return {"ok": True, "read_percent": pct}


DRILL_EVERY_SECS = 30 * 86400
DRILL_MAX_FILE_BYTES = 20 * 1024 * 1024


def drill(repo_id: str) -> dict[str, Any]:
    """A restore drill: brings back one small file of the newest version into a scratch folder and
    checks its size, proving the backup can actually be restored (audit batch 1)."""
    import shutil
    import tempfile

    repo = get_repo(repo_id)
    out = run_restic(repo, ["ls", "--json", "latest"], timeout=900)
    pick = None
    for line in out.splitlines():
        try:
            node = json.loads(line)
        except ValueError:
            continue
        if (
            node.get("struct_type") == "node"
            and node.get("type") == "file"
            and 0 < int(node.get("size") or 0) <= DRILL_MAX_FILE_BYTES
        ):
            pick = node
            break
    if not pick:
        _update(repo_id, last_drill=time.time(), last_drill_result="no file small enough to test")
        return {"ok": False, "reason": "no file small enough to test"}
    scratch = tempfile.mkdtemp(prefix="zettnas-drill-")
    try:
        run_restic(repo, ["restore", "latest", "--target", scratch, "--include", pick["path"]], timeout=1800)
        restored = os.path.join(scratch, pick["path"].lstrip("/"))
        ok = os.path.isfile(restored) and os.path.getsize(restored) == int(pick["size"])
    except ResticError as e:
        _update(repo_id, last_drill=time.time(), last_drill_result=f"failed: {e}"[:300])
        raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    _update(repo_id, last_drill=time.time(), last_drill_result="ok" if ok else "failed: restored file differs")
    if not ok:
        raise ResticError("the restored test file differs from the backup")
    return {"ok": True, "file": pick["path"], "size": int(pick["size"])}


def _update(repo_id: str, **fields: Any) -> None:
    with _LOCK:
        repos = _repos()
        if repo_id in repos:
            repos[repo_id].update(fields)
            _save(repos)


def run_due(now: float | None = None) -> list[str]:
    """Called every minute by the scheduler: daily backups at their hour, a weekly check."""
    now = now or time.time()
    t = time.localtime(now)
    started = []
    for repo in list_repos():
        if repo.get("hour") is None or repo["id"] in _RUNNING:
            continue
        if t.tm_hour == repo["hour"] and now - float(repo.get("last_backup") or 0) > 20 * 3600:
            threading.Thread(target=_safe, args=(backup, repo["id"]), daemon=True, name=f"offsite-{repo['id']}").start()
            started.append(repo["id"])
        elif (
            now - float(repo.get("last_check") or 0) > 7 * 86400
            and repo.get("initialized")
            and t.tm_hour == (repo["hour"] + 3) % 24
        ):
            threading.Thread(
                target=_safe, args=(check, repo["id"]), daemon=True, name=f"offsite-check-{repo['id']}"
            ).start()
        elif (
            now - float(repo.get("last_drill") or 0) > DRILL_EVERY_SECS
            and repo.get("last_backup")
            and t.tm_hour == (repo["hour"] + 4) % 24
        ):
            threading.Thread(
                target=_safe, args=(drill, repo["id"]), daemon=True, name=f"offsite-drill-{repo['id']}"
            ).start()
    return started


def _safe(fn: Any, repo_id: str) -> None:
    try:
        fn(repo_id)
    except Exception as e:
        logger.warning(f"[Offsite] {fn.__name__} of {repo_id} failed: {e}")
        try:
            from backend.services.notifications import send_notification

            send_notification(
                "ZettNAS offsite backup failed",
                f"{repo_id}: {e}",
                level="warning",
                event_type="backup",
                dedup_key=f"offsite-{repo_id}",
            )
        except Exception:
            logger.debug("offsite: notification failed", exc_info=True)
