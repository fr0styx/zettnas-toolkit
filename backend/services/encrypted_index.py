"""Where encrypted folders are (FEAT-13), for the modules that only need to know that: access
(share_access) and the Recycle Bin. It imports nothing above the config, so they can use it
without depending on the code that opens and locks the folders (encrypted_folders)."""

import os
from typing import Any

from backend.config import DATA_DIR
from backend.fsutil import read_json

SETTINGS_FILE = f"{DATA_DIR}/encrypted_folders.json"
ROOT = "/mnt/encrypted"  # readable views, inside the container only
BIN = ".RecycleBin"


def folders() -> dict[str, dict[str, Any]]:
    data = read_json(SETTINGS_FILE, {}) or {}
    found = data.get("folders") if isinstance(data, dict) else None
    return found if isinstance(found, dict) else {}


def plain_path(name: str) -> str:
    return os.path.join(ROOT, name)


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
