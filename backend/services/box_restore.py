"""Restore a whole box from its off-site backup's recovery kit (RES-7).

Every off-site backup run also stores a copy of Kiboto's settings, encrypted with the backup's
recovery key, as its own small snapshot (offsite_backup.backup_settings). On new hardware the recovery kit is
then enough: `connect` reads the kit and adds the backup, `restore_settings` brings the settings
back (applied at the next start), and `start_files_restore` puts the backed-up folders back where
they were, never over a file that is already there.
"""

from __future__ import annotations

import configparser
import os
import re
import shutil
import signal
import tempfile
import threading
import time
from typing import Any

from backend.config import RCLONE_CONFIG_FILE, logger
from backend.fsutil import atomic_write_text
from backend.services import offsite_backup as ob

_KIT_TITLE = "off-site backup: recovery kit"
_FIELD = re.compile(r"^(Name|Backup location|Recovery key|Folders in it):\s*(.*)$")
_EXPORT = re.compile(r"\b(RESTIC_REST_USERNAME|RESTIC_REST_PASSWORD|RESTIC_PASSWORD)='([^']*)'")


class KitError(ValueError):
    """The text is not a usable recovery kit."""


def parse_kit(text: str) -> dict[str, Any]:
    """Reads a recovery kit (offsite_backup.recovery_kit): name, location, key, folders, the REST
    sign-in and the rclone settings it carries."""
    text = (text or "").replace("\r\n", "\n")
    if len(text) > 64 * 1024:
        raise KitError("This file is too big to be a recovery kit.")
    kit: dict[str, Any] = {"name": "", "location": "", "key": "", "paths": [], "rest_user": "", "rest_password": ""}
    rclone: list[str] = []
    in_rclone = False
    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("----- rclone.conf"):
            in_rclone = True
            continue
        if in_rclone:
            if line.startswith("-----"):
                in_rclone = False
            elif line:
                rclone.append(line)
            continue
        m = _FIELD.match(line)
        if m:
            label, value = m.group(1), m.group(2).strip()
            if label == "Name":
                kit["name"] = value
            elif label == "Backup location":
                kit["location"] = value
            elif label == "Recovery key":
                kit["key"] = value
            else:
                kit["paths"] = [p.strip() for p in value.split(",") if p.strip()]
            continue
        for var, value in _EXPORT.findall(line):
            if var == "RESTIC_REST_USERNAME":
                kit["rest_user"] = value
            elif var == "RESTIC_REST_PASSWORD":
                kit["rest_password"] = value
            elif not kit["key"]:
                kit["key"] = value
    if not kit["location"] or not kit["key"]:
        if _KIT_TITLE not in text:
            raise KitError("This is not a Kiboto recovery kit: it has no backup location and key.")
        raise KitError("The recovery kit is missing its backup location or key.")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{16,128}", kit["key"]):
        raise KitError("The recovery key in this kit looks damaged.")
    kit["rclone"] = "\n".join(rclone)
    return kit


def _repo_id(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:30] or "restored"
    taken = {r["id"] for r in ob.list_repos()}
    rid = base if base[0].isalnum() else f"r{base}"
    n = 2
    while rid in taken:
        rid = f"{base}-{n}"
        n += 1
    return rid


def _add_rclone_remote(conf: str, location: str) -> None:
    """Adds the kit's rclone remote to Kiboto's rclone settings. A remote of the same name that is
    already there and different is not replaced."""
    if not location.startswith("rclone:"):
        return
    if not conf:
        raise KitError("This kit is for a cloud backup but holds no rclone settings.")
    new = configparser.RawConfigParser()
    try:
        new.read_string(conf)
    except configparser.Error as e:
        raise KitError("The rclone settings in this kit are damaged.") from e
    remote = location.split(":", 2)[1]
    if not new.has_section(remote):
        raise KitError(f"The kit's rclone settings have no remote called {remote}.")
    cur = configparser.RawConfigParser()
    try:
        cur.read(RCLONE_CONFIG_FILE, encoding="utf-8")
    except (OSError, configparser.Error):
        cur = configparser.RawConfigParser()
    if cur.has_section(remote):
        if dict(cur.items(remote)) != dict(new.items(remote)):
            raise KitError(f"An rclone remote called {remote} already exists with other settings.")
        return
    cur.add_section(remote)
    for k, v in new.items(remote):
        cur.set(remote, k, v)
    os.makedirs(os.path.dirname(RCLONE_CONFIG_FILE) or ".", exist_ok=True)
    lines: list[str] = []
    for section in cur.sections():
        lines.append(f"[{section}]")
        lines += [f"{k} = {v}" for k, v in cur.items(section)]
        lines.append("")
    atomic_write_text(RCLONE_CONFIG_FILE, "\n".join(lines))
    os.chmod(RCLONE_CONFIG_FILE, 0o600)


def _write_key(repo_id: str, key: str) -> None:
    os.makedirs(ob.KEY_DIR, mode=0o700, exist_ok=True)
    fd = os.open(ob._key_file(repo_id), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)


def connect(kit_text: str) -> dict[str, Any]:
    """Adds the backup a recovery kit describes, without a schedule, and reads its versions.
    The backup is only read here; nothing is written to it."""
    kit = parse_kit(kit_text)
    for repo in ob.list_repos():
        if repo.get("location") == kit["location"]:
            raise KitError(f"This backup is already connected as {repo.get('name') or repo['id']}.")
    _add_rclone_remote(kit["rclone"], kit["location"])
    rid = _repo_id(kit["name"])
    paths = [p for p in kit["paths"] if ob._in_storage(p)] or [p for p in kit["paths"] if p.startswith("/")]
    _write_key(rid, kit["key"])
    done = False
    try:
        repo = ob.save_repo(
            rid,
            kit["name"] or rid,
            kit["location"],
            paths or ["/mnt/user"],
            hour=None,  # no backups into it until someone turns the schedule on again
            rest_user=kit["rest_user"],
            rest_password=kit["rest_password"],
        )
        ob._update(rid, initialized=True, kit_saved_at=time.time(), restored_from_kit=time.time())
        versions = ob.snapshots(rid)
        settings = ob.settings_copies(rid)
        done = True
    finally:
        if not done:  # a kit that does not open its backup leaves nothing behind
            ob.delete_repo(rid)
            try:
                os.remove(ob._key_file(rid))
            except OSError:
                logger.debug("[Restore] no key file to remove for %s", rid, exc_info=True)
    return {"repo": repo, "versions": versions, "settings": settings}


def restore_settings(repo_id: str, snapshot_id: str = "latest") -> dict[str, Any]:
    """Brings back the settings copy of a backup. Like an uploaded settings backup it is checked,
    then staged and applied at the next start (backup_engine.restore_backup_archive)."""
    from backend.services.backup_engine import restore_backup_archive

    repo = ob.get_repo(repo_id)
    if not re.fullmatch(r"[0-9a-f]{6,64}|latest", snapshot_id):
        raise ValueError("Pick a settings copy.")
    copies = ob.settings_copies(repo_id)
    if not copies:
        raise ValueError("This backup holds no copy of the settings yet.")
    chosen = copies[0] if snapshot_id == "latest" else next((c for c in copies if c["id"] == snapshot_id[:8]), None)
    if not chosen:
        raise KeyError("No such settings copy.")
    folder = (chosen.get("paths") or [""])[0]
    scratch = tempfile.mkdtemp(prefix="kiboto-settings-")
    try:
        ob.run_restic(repo, ["restore", chosen["id"], "--target", scratch], timeout=1800)
        found = os.path.join(scratch, folder.lstrip("/"), ob.SETTINGS_FILE)
        if not os.path.isfile(found):
            raise ValueError("The settings copy could not be read from the backup.")
        with open(found, "rb") as f:
            result = restore_backup_archive(f, passphrase=ob.recovery_key(repo_id), staged=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"restored": (result or {}).get("restored"), "from": chosen["time"], **restart_to_apply()}


def restart_to_apply(delay: float = 2.0) -> dict[str, Any]:
    """Restarts Kiboto so a staged restore is applied, when Docker will start it again by itself
    (restart policy always or unless-stopped). Otherwise says that someone has to."""
    from backend.services import nas_name

    policy = ((nas_name._self().get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name", "")
    if policy not in ("always", "unless-stopped"):
        return {"restarting": False}

    def _later() -> None:
        time.sleep(delay)
        from backend.services import vm_qemu

        vm_qemu.machines_first()  # running virtual machines end with Kiboto: they are asked first
        logger.warning("[Restore] Restarting to apply the restored settings")
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_later, name="restore-restart", daemon=True).start()
    return {"restarting": True}


# ---- the files ----


def _files_plan(repo_id: str, snapshot_id: str) -> tuple[dict[str, Any], list[list[str]], list[str]]:
    """One restic restore per folder, each into that same folder (snapshot:folder --target folder),
    so nothing outside the folders is touched, not even their parents' permissions."""
    repo = ob.get_repo(repo_id)
    if not re.fullmatch(r"[0-9a-f]{6,64}|latest", snapshot_id):
        raise ValueError("Pick a backup version.")
    versions = ob.snapshots(repo_id)
    if snapshot_id == "latest":
        chosen = versions[0] if versions else None
    else:
        chosen = next((v for v in versions if v["id"] == snapshot_id[:8]), None)
    if not chosen:
        raise KeyError("No such backup version.")
    paths = [p.rstrip("/") for p in chosen.get("paths") or [] if ob._in_storage(p)]
    if not paths:
        raise ValueError("None of this version's folders are on this NAS's storage. Create the shares first.")
    runs = [["restore", "--json", f"{chosen['id']}:{p}", "--target", p, "--overwrite", "never"] for p in paths]
    return repo, runs, paths


def start_files_restore(repo_id: str, snapshot_id: str = "latest", owner: str | None = None) -> dict[str, Any]:
    """Puts every folder of a backup version back where it was, as a job. Files that are already
    there are left as they are (restic --overwrite never), so a half-done restore can run again."""
    from backend.services.jobs import job_manager

    repo, runs, paths = _files_plan(repo_id, snapshot_id)
    rid = repo["id"]
    job = job_manager.register(
        "restore",
        f"Bring back all files from {repo['name']}",
        owner=owner,
        cancel=lambda: ob.cancel(rid),
        title_id="jobs.t.restore_all",
        title_params={"repo": repo["name"]},
    )

    def restore_all(_repo: dict[str, Any]) -> None:
        try:
            for path, args in zip(paths, runs, strict=True):
                job_manager.update(job.id, detail=path)
                os.makedirs(path, exist_ok=True)
                ob._run(
                    repo,
                    args,
                    track=True,
                    on_line=lambda text: ob._progress(job.id, ob._message(text), "files_restored"),
                )
        except (ob.ResticError, OSError) as e:
            job_manager.finish(job.id, "error", error=str(e))
            raise
        job_manager.finish(job.id, "done")

    try:
        ob._start(rid, restore_all, repo)
    except ob.BusyError:
        job_manager.finish(job.id, "cancelled")
        raise
    return {"status": "started", "job": job.id, "paths": paths}
