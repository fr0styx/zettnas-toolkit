"""Versioned, deduplicated, encrypted offsite backup with restic (Batch 6).

A repository is a folder (a USB disk, another NAS), an rclone remote ("rclone:name:path",
using ZettNAS's rclone config, so every cloud rclone supports works) or a restic REST server
("rest:http://host:8000/name/", for example another ZettNAS running the backup-target app,
FEAT-08). restic encrypts
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
from collections.abc import Callable
from typing import Any

from backend import config
from backend.config import DATA_DIR, RCLONE_CONFIG_FILE, logger
from backend.fsutil import atomic_write_json, atomic_write_text, read_json, resolve_within

REPOS_FILE = os.path.join(DATA_DIR, "offsite_repos.json")
KEY_DIR = os.path.join(DATA_DIR, "offsite_keys")
DEFAULT_KEEP = {"daily": 7, "weekly": 4, "monthly": 12}
_LOCK = threading.Lock()
_RUNNING: dict[str, subprocess.Popen] = {}
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_BUSY: set[str] = set()  # repos with a backup or restore started, before restic itself runs
WARN_EXIT = 3  # restic backup: the snapshot was made, but some files could not be read
OFF_BOX_ROOTS = ("/mnt/disks/", "/mnt/remotes/", "/mnt/addons/")  # USB and network disks
_HOST = re.compile(r"^zettnas-[0-9a-f]{8}$")
# rest:http(s)://host[:port][/path]; user and password go in their own fields, never the address
_REST = re.compile(r"^rest:https?://[A-Za-z0-9.\-\[\]:]+(/[A-Za-z0-9._~\-/]*)?$")


class ResticError(RuntimeError):
    pass


class BusyError(RuntimeError):
    pass


def host_id() -> str:
    """The host name this NAS's backups carry in restic (REL-16). It stays the same across
    updates, which give the container a new hostname each time; with a new one restic re-read
    every file and the old versions were never pruned."""
    path = os.path.join(DATA_DIR, "offsite_host")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
        if _HOST.match(value):
            return value
    value = f"zettnas-{secrets.token_hex(4)}"
    os.makedirs(DATA_DIR, exist_ok=True)
    atomic_write_text(path, value + "\n")
    return value


def _device(path: str) -> int | None:
    while path and path != "/" and not os.path.exists(path):
        path = os.path.dirname(path)
    try:
        return os.stat(path or "/").st_dev
    except OSError:
        return None


def same_disk(location: str, paths: list[str]) -> bool:
    """True when a folder destination sits on the same storage as the folders it protects, so
    one failed disk, a theft or a fire takes both (REL-16)."""
    if not location.startswith("/") or location.startswith(OFF_BOX_ROOTS):
        return False
    dev = _device(location)
    return dev is not None and any(_device(p) == dev for p in paths)


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


def _public(repo: dict[str, Any]) -> dict[str, Any]:
    """A repository as the interface sees it: the REST password stays on the server."""
    out = {k: v for k, v in repo.items() if k != "rest_password"}
    out["has_rest_password"] = bool(repo.get("rest_password"))
    out["same_disk"] = same_disk(repo.get("location") or "", repo.get("paths") or [])
    return out


def list_repos() -> list[dict[str, Any]]:
    return [_public(r) for r in _repos().values()]


def _check_location(location: str) -> None:
    if location.startswith("rest:"):
        if not _REST.match(location):
            raise ValueError(
                "A REST server address looks like rest:http://friend-nas:8000/yourname/ "
                "(put the user name and password in their own fields)."
            )
        return
    if not location or not location.startswith(("/", "rclone:")):
        raise ValueError(
            "The destination is a folder (/mnt/disks/usb/backup), an rclone remote (rclone:name:path) "
            "or a restic REST server (rest:http://host:8000/name/)."
        )
    if location.startswith("/") and not _in_storage(location):
        raise ValueError("A folder destination must be on the storage (for example a USB disk under /mnt/disks).")


def _rest_fields(location: str, old: dict[str, Any], user: str, password: str) -> dict[str, Any]:
    """The REST sign-in kept with a repository: the password sealed, an empty one keeps the last."""
    if not location.startswith("rest:"):
        return {}
    from backend import secret_box

    user = (user or "").strip()
    if user and not re.fullmatch(r"[A-Za-z0-9._@-]{1,64}", user):
        raise ValueError("Use letters, digits, dots, dashes and @ for the REST user name.")
    sealed = secret_box.seal(password) if password else old.get("rest_password", "")
    return {"rest_user": user, "rest_password": sealed}


def get_repo(repo_id: str) -> dict[str, Any]:
    repo = _repos().get(repo_id)
    if not repo:
        raise KeyError("No such backup.")
    return repo


def save_repo(
    repo_id: str,
    name: str,
    location: str,
    paths: list[str],
    keep: dict[str, int] | None = None,
    hour: int | None = 2,
    rest_user: str = "",
    rest_password: str = "",
) -> dict[str, Any]:
    if not _ID.match(repo_id or ""):
        raise ValueError("Use lowercase letters, digits and dashes for the id.")
    _check_location(location or "")
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
            # the server refused deletes once (append-only); a new address is asked again
            "append_only": bool(old.get("append_only")) and old.get("location") == location,
            **_rest_fields(location, old, rest_user, rest_password),
        }
        _save(repos)
    return _public(repos[repo_id])


def reseal_rest_passwords() -> int:
    """Seals the REST passwords again with a new secret key (services/key_rotation.py)."""
    from backend import secret_box

    with _LOCK:
        repos = _repos()
        count = 0
        for repo in repos.values():
            value = str(repo.get("rest_password") or "")
            if secret_box.is_sealed(value):
                repo["rest_password"] = secret_box.seal(secret_box.unseal(value))
                count += 1
        if count:
            _save(repos)
    return count


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
            "RESTIC_PROGRESS_FPS": "0.5",
        }
    )
    env.pop("RESTIC_PASSWORD", None)
    for name in ("RESTIC_REST_USERNAME", "RESTIC_REST_PASSWORD"):
        env.pop(name, None)
    if repo["location"].startswith("rest:"):
        from backend import secret_box

        if repo.get("rest_user"):
            env["RESTIC_REST_USERNAME"] = repo["rest_user"]
        if repo.get("rest_password"):
            env["RESTIC_REST_PASSWORD"] = secret_box.unseal(repo["rest_password"])
    return env


def _stream(proc: subprocess.Popen, timeout: int, on_line: Callable[[str], Any]) -> tuple[str, str]:
    """Hands each output line to on_line as restic prints it; keeps all but the progress lines."""
    err: list[str] = []
    reader = threading.Thread(target=lambda: err.append(proc.stderr.read() if proc.stderr else ""), daemon=True)
    reader.start()
    timed_out = threading.Event()

    def _kill() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, _kill)
    timer.start()
    kept: list[str] = []
    try:
        for line in proc.stdout or []:
            if '"message_type":"status"' not in line:
                kept.append(line)
            try:
                on_line(line)
            except Exception:
                logger.debug("offsite: progress line not understood", exc_info=True)
        proc.wait()
    finally:
        timer.cancel()
    reader.join(5)
    if timed_out.is_set():
        raise subprocess.TimeoutExpired(proc.args, timeout)
    return "".join(kept), "".join(err)


def _run(
    repo: dict[str, Any],
    args: list[str],
    timeout: int = 6 * 3600,
    track: bool = False,
    ok: tuple[int, ...] = (0,),
    on_line: Callable[[str], Any] | None = None,
) -> tuple[int, str]:
    """Runs restic; returns its exit code (one of `ok`) and output."""
    code, out, _err = _run_full(repo, args, timeout=timeout, track=track, ok=ok, on_line=on_line)
    return code, out


def _run_full(
    repo: dict[str, Any],
    args: list[str],
    timeout: int = 6 * 3600,
    track: bool = False,
    ok: tuple[int, ...] = (0,),
    on_line: Callable[[str], Any] | None = None,
) -> tuple[int, str, str]:
    """Runs restic; returns its exit code (one of `ok`), output and error output."""
    if not restic_available():
        raise ResticError("restic is not installed in this image.")
    cmd = ["restic", *args]
    proc = subprocess.Popen(cmd, env=_env(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if track:
        _RUNNING[repo["id"]] = proc
    try:
        out, err = _stream(proc, timeout, on_line) if on_line else proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise ResticError("restic took too long and was stopped.") from None
    finally:
        _RUNNING.pop(repo["id"], None)
    if proc.returncode not in ok:
        raise ResticError((err or out or f"restic exited with {proc.returncode}").strip().splitlines()[-1][:300])
    return proc.returncode, out, err or ""


def run_restic(repo: dict[str, Any], args: list[str], timeout: int = 6 * 3600, track: bool = False) -> str:
    return _run(repo, args, timeout=timeout, track=track)[1]


def _unlock(repo: dict[str, Any]) -> None:
    """Removes locks left by a restic that was killed (a restart, an update, a power cut), which
    would otherwise block every later run. Locks of a running restic stay."""
    try:
        run_restic(repo, ["unlock"], timeout=300)
    except ResticError as e:
        logger.info(f"[Offsite] unlock of {repo['id']} skipped: {e}")


def _message(line: str) -> dict[str, Any]:
    line = line.strip()
    if not line.startswith("{"):
        return {}
    try:
        msg = json.loads(line)
    except ValueError:
        return {}
    return msg if isinstance(msg, dict) else {}


def _progress(job_id: str, msg: dict[str, Any], done_key: str) -> None:
    from backend.services.jobs import job_manager

    pct = msg.get("percent_done")
    if msg.get("message_type") != "status" or pct is None:
        return
    total = msg.get("total_files")
    detail = f"{msg.get(done_key) or 0} of {total} files" if total else ""
    job_manager.update(job_id, percent=round(float(pct) * 100, 1), detail=detail)


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
    if loc.startswith("rest:") and repo.get("rest_user"):
        from backend import secret_box

        password = secret_box.unseal(repo["rest_password"]) if repo.get("rest_password") else ""
        lines += [
            f"  {step}. export RESTIC_REST_USERNAME='{repo['rest_user']}' RESTIC_REST_PASSWORD='{password}'",
        ]
        step += 1
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


def _backup_job(repo: dict[str, Any], owner: str | None) -> Any:
    from backend.services.jobs import job_manager

    rid = repo["id"]
    return job_manager.register("backup", f"Offsite backup: {repo['name']}", owner=owner, cancel=lambda: cancel(rid))


def backup(repo_id: str, owner: str | None = None, job: Any = None) -> dict[str, Any]:
    """Backs up the repository's folders, then applies the retention rules. Files that could not
    be read (restic exit 3) leave a backup of everything else and a warning, not a failure."""
    repo = get_repo(repo_id)
    if not repo.get("initialized"):
        init(repo_id)
    from backend.services.jobs import job_manager

    job = job or _backup_job(repo, owner)
    summary: dict[str, Any] = {}
    unreadable: list[str] = []
    count = [0]

    def line(text: str) -> None:
        msg = _message(text)
        kind = msg.get("message_type")
        if kind == "status":
            _progress(job.id, msg, "files_done")
        elif kind == "error":
            count[0] += 1
            if len(unreadable) < 20:
                unreadable.append(str(msg.get("item") or (msg.get("error") or {}).get("message") or "")[:300])
        elif kind == "summary":
            summary.update(msg)

    try:
        from backend.services import backup_hooks

        job_manager.update(job.id, detail="Writing database dumps")
        dumps = backup_hooks.run_dumps(repo["paths"])  # a consistent copy of each database (REL-20)
        _unlock(repo)
        code, _out = _run(
            repo,
            ["backup", "--json", "--host", host_id(), "--tag", "zettnas", "--exclude", ".RecycleBin", *repo["paths"]],
            track=True,
            ok=(0, WARN_EXIT),
            on_line=line,
        )
        if code == WARN_EXIT and not count[0]:
            count[0] = 1
        k = repo["keep"]
        from backend.services.ransomware_guard import get_guard

        if get_guard().frozen:  # REL-9: during an attack no good version is pruned away
            logger.warning(f"[Offsite] {repo['name']}: writes are frozen, old versions are kept")
        else:
            _forget(repo, k)
        result = {
            "snapshot": summary.get("snapshot_id", "")[:8],
            "files_new": summary.get("files_new", 0),
            "files_changed": summary.get("files_changed", 0),
            "data_added": summary.get("data_added", 0),
            "unreadable": count[0],
            "unreadable_files": unreadable,
            "dumps": dumps,
        }
        _update(
            repo_id, last_backup=time.time(), last_result="ok", last_unreadable=count[0], unreadable_files=unreadable
        )
        if count[0]:
            job_manager.update(job.id, detail=f"{count[0]} files could not be read")
        job_manager.finish(job.id, "done")
        return result
    except ResticError as e:
        _update(repo_id, last_result=f"failed: {e}"[:300])
        job_manager.finish(job.id, "error", error=str(e))
        raise


def _forget(repo: dict[str, Any], k: dict[str, int]) -> None:
    """Applies the retention rules. An append-only server (FEAT-08) refuses every delete with
    HTTP 403: restic exits 0 when only snapshots were to go and fails when packs were, so the
    refusal is read from its messages either way. The backup is then marked append-only and
    later runs leave pruning to the server's owner."""
    if repo.get("append_only"):
        return
    try:
        err = _run_full(repo, _forget_args(k))[2]
    except ResticError as e:
        if "(403)" not in str(e):
            raise
        err = str(e)
    if "(403)" in err:
        logger.info("[Offsite] %s: the server is append-only; old versions stay there", repo["name"])
        _update(repo["id"], append_only=True)


def _forget_args(k: dict[str, int]) -> list[str]:
    return [
        "forget",
        "--prune",
        "--tag",
        "zettnas",
        "--group-by",
        "paths,tags",
        "--keep-daily",
        str(k["daily"]),
        "--keep-weekly",
        str(k["weekly"]),
        "--keep-monthly",
        str(k["monthly"]),
    ]


def _start(repo_id: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    with _LOCK:
        if repo_id in _BUSY or repo_id in _RUNNING:
            raise BusyError("A backup or restore of this repository is already running.")
        _BUSY.add(repo_id)

    def run() -> None:
        try:
            _safe(fn, *args, **kwargs)
        finally:
            _BUSY.discard(repo_id)

    threading.Thread(target=run, daemon=True, name=f"offsite-{fn.__name__}-{repo_id}").start()


def start_backup(repo_id: str, owner: str | None = None) -> dict[str, Any]:
    """A backup as a job (REL-16): returns at once; progress and the result show in Jobs."""
    repo = get_repo(repo_id)
    job = _backup_job(repo, owner)
    try:
        _start(repo_id, backup, repo_id, owner=owner, job=job)
    except BusyError:
        from backend.services.jobs import job_manager

        job_manager.finish(job.id, "cancelled")
        raise
    return {"status": "started", "job": job.id}


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


def browse(repo_id: str, snapshot_id: str, path: str = "/", principal: Any = None) -> list[dict[str, Any]]:
    """Entries directly inside `path` of a backup version. With a principal, only what that
    person may open today (REL-23)."""
    repo = get_repo(repo_id)
    if not re.fullmatch(r"[0-9a-f]{6,64}|latest", snapshot_id):
        raise ValueError("Pick a backup version.")
    path = "/" + path.strip("/")
    can: Callable[[str, bool], bool] | None = None
    if principal is not None:
        from backend.services.path_access import user_can_access_path

        if path != "/" and not user_can_access_path(path, principal, allow_list=True):
            raise PermissionError("You don't have access to this folder.")

        def _can(p: str, is_dir: bool) -> bool:
            return user_can_access_path(p, principal, allow_list=is_dir)

        can = _can

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
        if can is not None and not can(p, node.get("type") == "dir"):
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


def _restore_plan(repo_id: str, snapshot_id: str, path: str, target: str) -> tuple[dict[str, Any], list[str], str]:
    repo = get_repo(repo_id)
    if not re.fullmatch(r"[0-9a-f]{6,64}|latest", snapshot_id):
        raise ValueError("Pick a backup version.")
    if not target.startswith("/") or ".." in target.split("/") or not _in_storage(target):
        raise ValueError("Restore into a folder on the storage.")
    args = ["restore", "--json", snapshot_id, "--target", target, "--include", "/" + path.strip("/")]
    return repo, args, os.path.join(target, path.strip("/"))


def _run_restore(repo: dict[str, Any], args: list[str], target: str, job: Any = None) -> None:
    from backend.services.jobs import job_manager

    os.makedirs(target, exist_ok=True)
    if job is None:
        _run(repo, args)
        return
    try:
        _run(repo, args, track=True, on_line=lambda text: _progress(job.id, _message(text), "files_restored"))
    except ResticError as e:
        job_manager.finish(job.id, "error", error=str(e))
        raise
    job_manager.finish(job.id, "done")


def restore(repo_id: str, snapshot_id: str, path: str, target: str) -> dict[str, Any]:
    """Restores one file or folder of a backup version into `target` (a folder that gets the
    original path below it), never over the live files."""
    repo, args, restored_to = _restore_plan(repo_id, snapshot_id, path, target)
    _run_restore(repo, args, target)
    return {"restored_to": restored_to}


def start_restore(repo_id: str, snapshot_id: str, path: str, target: str, owner: str | None = None) -> dict[str, Any]:
    """A restore as a job (REL-16): checked first, then run in the background with progress."""
    from backend.services.jobs import job_manager

    repo, args, restored_to = _restore_plan(repo_id, snapshot_id, path, target)
    rid = repo["id"]
    name = os.path.basename(path.rstrip("/")) or "/"
    job = job_manager.register(
        "restore", f"Restore {name} from {repo['name']}", owner=owner, cancel=lambda: cancel(rid)
    )
    try:
        _start(rid, _run_restore, repo, args, target, job=job)
    except BusyError:
        job_manager.finish(job.id, "cancelled")
        raise
    return {"status": "started", "job": job.id, "restored_to": restored_to}


def check(repo_id: str, read_percent: int = 5) -> dict[str, Any]:
    """Verifies the repository's structure and reads back a sample of the data."""
    repo = get_repo(repo_id)
    pct = max(1, min(int(read_percent), 100))
    try:
        _unlock(repo)
        run_restic(repo, ["check", f"--read-data-subset={pct}%"])
    except ResticError as e:
        _update(repo_id, last_check=time.time(), last_result=f"check failed: {e}"[:300])
        raise
    _update(repo_id, last_check=time.time(), last_result="ok")
    return {"ok": True, "read_percent": pct}


DRILL_EVERY_SECS = 30 * 86400
DRILL_MAX_FILE_BYTES = 20 * 1024 * 1024


def _pick_file(out: str) -> dict[str, Any] | None:
    """One file picked at random among the small ones (reservoir sampling, one pass)."""
    pick, seen = None, 0
    for line in out.splitlines():
        node = _message(line)
        if (
            node.get("struct_type") == "node"
            and node.get("type") == "file"
            and 0 < int(node.get("size") or 0) <= DRILL_MAX_FILE_BYTES
        ):
            seen += 1
            if secrets.randbelow(seen) == 0:
                pick = node
    return pick


def _sha256(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _mtime(value: Any) -> float | None:
    """restic's RFC 3339 time (nanoseconds) as a timestamp."""
    from datetime import datetime

    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value or "")).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _unchanged(live: str, node: dict[str, Any]) -> bool:
    """The live file still is what the backup holds (same size and modification time)."""
    when = _mtime(node.get("mtime"))
    try:
        st = os.stat(live)
    except OSError:
        return False
    return when is not None and st.st_size == int(node.get("size") or -1) and abs(st.st_mtime - when) < 1


def drill(repo_id: str) -> dict[str, Any]:
    """A restore drill: brings back one small file, picked at random, of the newest version into a
    scratch folder. Its SHA-256 is compared with the live file when that has not changed since the
    backup, otherwise its size is checked; this proves the backup can actually be restored."""
    import shutil
    import tempfile

    repo = get_repo(repo_id)
    out = run_restic(repo, ["ls", "--json", "latest"], timeout=900)
    pick = _pick_file(out)
    if not pick:
        _update(repo_id, last_drill=time.time(), last_drill_result="no file small enough to test")
        return {"ok": False, "reason": "no file small enough to test"}
    scratch = tempfile.mkdtemp(prefix="zettnas-drill-")
    try:
        run_restic(repo, ["restore", "latest", "--target", scratch, "--include", pick["path"]], timeout=1800)
        restored = os.path.join(scratch, pick["path"].lstrip("/"))
        ok = os.path.isfile(restored) and os.path.getsize(restored) == int(pick["size"])
        digest = _sha256(restored) if ok else ""
        verified = "size"
        if ok and _unchanged(pick["path"], pick):
            verified = "sha256"
            ok = digest == _sha256(pick["path"])
    except ResticError as e:
        _update(repo_id, last_drill=time.time(), last_drill_result=f"failed: {e}"[:300])
        raise
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    _update(
        repo_id,
        last_drill=time.time(),
        last_drill_result="ok" if ok else "failed: restored file differs",
        last_drill_verified=verified,
    )
    if not ok:
        raise ResticError("the restored test file differs from the backup")
    return {"ok": True, "file": pick["path"], "size": int(pick["size"]), "sha256": digest, "verified": verified}


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
        if repo.get("hour") is None or repo["id"] in _RUNNING or repo["id"] in _BUSY:
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


def _safe(fn: Any, repo_or_id: Any, *args: Any, **kwargs: Any) -> None:
    repo_id = repo_or_id["id"] if isinstance(repo_or_id, dict) else repo_or_id
    try:
        fn(repo_or_id, *args, **kwargs)
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
