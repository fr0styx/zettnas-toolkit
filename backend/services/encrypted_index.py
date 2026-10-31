"""Where encrypted folders are (FEAT-13), for the modules that only need to know that: access
(share_access) and the Recycle Bin. It imports nothing above the config, so they can use it
without depending on the code that opens and locks the folders (encrypted_folders)."""

import os
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import ENCRYPTED_ROOT, read_json

SETTINGS_FILE = f"{DATA_DIR}/encrypted_folders.json"
ROOT = ENCRYPTED_ROOT  # readable views, inside the container only
BIN = ".RecycleBin"


def folders() -> dict[str, dict[str, Any]]:
    data = read_json(SETTINGS_FILE, {}) or {}
    found = data.get("folders") if isinstance(data, dict) else None
    return found if isinstance(found, dict) else {}


def plain_path(name: str) -> str:
    return os.path.join(ROOT, name)


def people_of(name: str) -> list[str] | None:
    """Who may open a folder (NSEC-5): its own list, or None when everyone who may use its share
    may (folders made before the list existed, or set that way)."""
    found = (folders().get(name) or {}).get("people")
    return [str(p) for p in found] if isinstance(found, list) else None


def grant_people() -> dict[str, list[str] | None]:
    """{readable folder: who may open it, or None for the share's people}."""
    return {plain_path(n): people_of(n) for n in folders()}


def may_open(name: str, username: str) -> bool:
    """Whether this person is on the folder's list (always, when it has none)."""
    who = people_of(name)
    return who is None or (username or "").lower() in {p.lower() for p in who}


def grant_paths() -> dict[str, str]:
    """{readable folder: the share it is in}, so access to it follows the share's."""
    return {plain_path(n): str(f.get("share") or "") for n, f in folders().items()}


def bin_for(path: str) -> str | None:
    """The Recycle Bin for a file in an open encrypted folder: inside the folder, so a deleted
    file stays encrypted. None for paths elsewhere."""
    real = os.path.realpath(path)
    if not real.startswith(ROOT + "/"):
        return None
    parts = real[len(ROOT) + 1 :].split("/")
    if len(parts) < 2 or BIN in parts:
        return None
    return os.path.join(ROOT, parts[0], BIN)
