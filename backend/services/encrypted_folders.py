"""Encrypted folders inside a share (FEAT-13), with gocryptfs.

The encrypted files live in the share, in a hidden folder (".zettnas-encrypted/<name>"), so
snapshots, backups and SMB from the host only ever see encrypted names and contents. When the
folder is unlocked with its password, its readable files appear in ZettNAS at
/mnt/encrypted/<name>: in Files, WebDAV and SFTP, for the people who may use the share it is in.
Locking it, or restarting ZettNAS, takes them away again. Deleting a file there puts it in the
folder's own Recycle Bin, which is inside the encryption.

The password is never stored, unless "unlock when ZettNAS starts" is on: then it is kept sealed
with the data key (secret_box), which is convenient and weaker, and said so. Creating a folder
shows its recovery key once; with it the files can be read even if the password is lost.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from typing import Any

from backend.config import logger
from backend.fsutil import ENCRYPTED_HIDDEN, atomic_write_json, json_locked
from backend.services import encrypted_index as ei
from backend.services.encrypted_index import bin_for, grant_paths, plain_path

__all__ = ["bin_for", "grant_paths", "plain_path"]  # kept here too, beside the rest

HIDDEN = ENCRYPTED_HIDDEN  # in the share: the encrypted files
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,47}$")
MASTER_KEY_RE = re.compile(r"((?:[0-9a-f]{8}-){7}[0-9a-f]{8})")
TOOL_SECS = 120  # gocryptfs derives the key with scrypt: a few seconds on a slow CPU


class EncryptedFolderError(Exception):
    """gocryptfs refused or failed; the message says why, for the person."""


def tool() -> str | None:
    return shutil.which("gocryptfs")


def _settings() -> dict[str, Any]:
    return {"folders": ei.folders()}


def cipher_path(share_path: str, name: str) -> str:
    return os.path.join(share_path, HIDDEN, name)


def _mounted() -> set[str]:
    """Mount points of gocryptfs folders that are open now."""
    from backend.fsutil import open_encrypted

    return open_encrypted()


def is_unlocked(name: str) -> bool:
    return plain_path(name) in _mounted()


def _share_path(share: str) -> str:
    from backend.hardware.pal_storage import get_storage_platform

    path = next(
        (str(getattr(sh, "mountpoint", "") or "") for sh in get_storage_platform().list_shares() if sh.name == share),
        "",
    )
    if path and not os.path.isdir(path):
        path = ""
    if not path:
        raise ValueError(f"There is no share called {share} on this server.")
    return path


def listing() -> list[dict[str, Any]]:
    """Every encrypted folder: where it is, and whether it is open now."""
    open_now = _mounted()
    return [
        {
            "name": name,
            "share": f.get("share", ""),
            "path": plain_path(name),
            "unlocked": plain_path(name) in open_now,
            "unlock_at_start": bool(f.get("password")),
            "created": f.get("created", 0),
        }
        for name, f in sorted(_settings()["folders"].items())
    ]


def share_of(name: str) -> str | None:
    f = _settings()["folders"].get(name)
    return f.get("share") if f else None


def _run(args: list[str], password: str) -> tuple[int, str]:
    from backend.proc import run_bounded

    exe = tool()
    if not exe:
        raise EncryptedFolderError("This ZettNAS image has no gocryptfs, so it can't open encrypted folders.")
    # the password goes in on stdin, never on the command line or on disk
    r = run_bounded([exe, *args], timeout=TOOL_SECS, input=password + "\n", capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _mount(cipher: str, plain: str, password: str, read_only: bool = False) -> None:
    os.makedirs(plain, exist_ok=True)
    # no -nosyslog: the mount runs on in the background, and with it the background process would
    # keep our output pipes open, so this call would wait out its time limit (NREL-4)
    code, out = _run(["-q", *(["-ro"] if read_only else []), cipher, plain], password)
    if code == 12:
        raise EncryptedFolderError("That password is wrong.")
    if code != 0:
        raise EncryptedFolderError(f"The folder couldn't be opened: {out.strip()[:200] or code}")


def _check_password(password: str) -> None:
    from backend.password_policy import password_problem

    problem = password_problem(password)
    if problem:
        raise ValueError(problem)


@json_locked(lambda *a, **k: ei.SETTINGS_FILE)
def create(share: str, name: str, password: str, unlock_at_start: bool = False) -> dict[str, Any]:
    """Makes an encrypted folder in a share and opens it. Returns its recovery key, shown once."""
    from backend import secret_box

    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError("Use a name of up to 48 letters, digits, spaces, dots, dashes or underscores.")
    _check_password(password)
    s = _settings()
    if name in s["folders"]:
        raise ValueError(f"There is already an encrypted folder called {name}.")
    cipher = cipher_path(_share_path(share), name)
    if os.path.exists(cipher) and os.listdir(cipher):
        raise ValueError(f"{share} already has encrypted files for {name}; add it back instead.")
    os.makedirs(cipher, exist_ok=True)
    code, out = _run(["-init", cipher], password)  # not -q: it prints the master key
    if code != 0:
        raise EncryptedFolderError(f"The folder couldn't be made: {out.strip()[:200] or code}")
    key = MASTER_KEY_RE.search(re.sub(r"\s+", "", out))  # it is printed over two lines (NREL-1)
    s["folders"][name] = {
        "share": share,
        "created": time.time(),
        "password": secret_box.seal(password) if unlock_at_start else "",
    }
    atomic_write_json(ei.SETTINGS_FILE, s)
    _mount(cipher, plain_path(name), password)
    logger.info("[Encrypted folders] %s made in %s", name, share)
    return {"name": name, "path": plain_path(name), "recovery_key": key.group(1) if key else ""}


@json_locked(lambda *a, **k: ei.SETTINGS_FILE)
def adopt(share: str, name: str, password: str) -> dict[str, Any]:
    """Adds back an encrypted folder whose files are in a share (after a reinstall or a restore)."""
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError("That isn't an encrypted folder's name.")
    s = _settings()
    if name in s["folders"]:
        raise ValueError(f"There is already an encrypted folder called {name}.")
    cipher = cipher_path(_share_path(share), name)
    if not os.path.isfile(os.path.join(cipher, "gocryptfs.conf")):
        raise ValueError(f"{share} has no encrypted folder called {name}.")
    _mount(cipher, plain_path(name), password)  # the password is checked by opening it
    s["folders"][name] = {"share": share, "created": time.time(), "password": ""}
    atomic_write_json(ei.SETTINGS_FILE, s)
    return {"name": name, "path": plain_path(name)}


def unlock(name: str, password: str) -> dict[str, Any]:
    f = _settings()["folders"].get(name)
    if not f:
        raise KeyError(name)
    if not is_unlocked(name):
        _mount(cipher_path(_share_path(f["share"]), name), plain_path(name), password)
    return {"name": name, "unlocked": True}


def lock(name: str) -> dict[str, Any]:
    from backend.proc import run_bounded

    if name not in _settings()["folders"]:
        raise KeyError(name)
    if is_unlocked(name):
        r = run_bounded(["fusermount3", "-u", plain_path(name)], timeout=30, capture_output=True, text=True)
        if r.returncode != 0:
            raise EncryptedFolderError("Something still has a file open in it. Close it and lock the folder again.")
    _drop_mount_point(name)
    return {"name": name, "unlocked": False}


def _drop_mount_point(name: str) -> None:
    """No folder is left where a locked one was, so nothing can be written there (NREL-3)."""
    try:
        os.rmdir(plain_path(name))
    except OSError:
        logger.debug("encrypted_folders: %s mount point not removed", name, exc_info=True)


@json_locked(lambda *a, **k: ei.SETTINGS_FILE)
def set_unlock_at_start(name: str, password: str | None) -> dict[str, Any]:
    """With a password: keep it sealed and open the folder when ZettNAS starts. None: forget it."""
    from backend import secret_box

    s = _settings()
    f = s["folders"].get(name)
    if not f:
        raise KeyError(name)
    if password is not None:
        if is_unlocked(name):
            # check it: opening the same encrypted files a second time, read-only, says yes or no
            probe = os.path.join(ei.ROOT, f".check-{name}")
            try:
                _mount(cipher_path(_share_path(f["share"]), name), probe, password, read_only=True)
            finally:
                lock_path(probe)
        else:
            unlock(name, password)
    f["password"] = secret_box.seal(password) if password is not None else ""
    atomic_write_json(ei.SETTINGS_FILE, s)
    return {"name": name, "unlock_at_start": password is not None}


def lock_path(path: str) -> None:
    from backend.proc import run_bounded

    run_bounded(["fusermount3", "-u", path], timeout=30, capture_output=True, text=True)
    try:
        os.rmdir(path)
    except OSError:
        logger.debug("encrypted_folders: %s left behind", path, exc_info=True)


@json_locked(lambda *a, **k: ei.SETTINGS_FILE)
def forget(name: str) -> dict[str, Any]:
    """Takes a locked folder off ZettNAS. Its encrypted files stay in the share; adding it back
    with its password opens them again."""
    s = _settings()
    if name not in s["folders"]:
        raise KeyError(name)
    if is_unlocked(name):
        raise ValueError("Lock the folder first.")
    del s["folders"][name]
    atomic_write_json(ei.SETTINGS_FILE, s)
    try:
        os.rmdir(plain_path(name))
    except OSError:
        logger.debug("encrypted_folders: empty mount point %s left", name, exc_info=True)
    return {"name": name, "forgotten": True}


def unlock_at_start() -> int:
    """At startup: opens the folders whose password is kept. Returns how many opened."""
    from backend import secret_box

    opened = 0
    for name, f in _settings()["folders"].items():
        if not is_unlocked(name):
            _drop_mount_point(name)  # an empty folder left from before a restart
        if not f.get("password") or is_unlocked(name):
            continue
        try:
            unlock(name, secret_box.unseal(f["password"]))
            opened += 1
        except (OSError, ValueError, KeyError, EncryptedFolderError) as e:
            logger.warning("[Encrypted folders] %s didn't open at start: %s", name, e)
    return opened


def reseal() -> int:
    """Seals the kept passwords again with a new data key (services/key_rotation.py)."""
    from backend import secret_box

    s = _settings()
    n = 0
    for f in s["folders"].values():
        if secret_box.is_sealed(f.get("password") or ""):
            f["password"] = secret_box.seal(secret_box.unseal(f["password"]))
            n += 1
    if n:
        atomic_write_json(ei.SETTINGS_FILE, s)
    return n
