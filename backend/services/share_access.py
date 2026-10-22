"""
Per-share access for non-admin users (SEC-10).

The file manager used to let any signed-in user act anywhere under the browse
roots except a short deny-list. Now a non-admin user can reach only:

- their home folder (read and write);
- shares the platform knows about (host shares on Unraid/TrueNAS, ZettNAS Samba
  shares), at the level set for them: "none", "read" or "write";
- the folders above those, to list them (nothing else is shown in them).

Levels live in data/share_access.json:
    {"default_level": "write",
     "shares": {"media": {"default": "read", "users": {"alice": "write"}}}}
A user's level for a share is, in order: their entry under "users", the
share's Samba user lists (valid users / read list / write list), the share's
"default", then the global "default_level". The global default stays "write" so
upgrading changes nothing for existing shares; admins tighten it from here.
"""

import logging
import os
import re
import threading
import time
from typing import Any, Optional

from backend import config
from backend.fsutil import atomic_write_json, read_json

logger = logging.getLogger("ZettNAS")

LEVELS = ("none", "read", "write")
_CACHE_TTL = 30.0
_cache: dict[str, Any] = {"ts": 0.0, "shares": []}
_lock = threading.Lock()


def _file() -> str:
    return os.path.join(config.DATA_DIR, "share_access.json")


def load_config() -> dict[str, Any]:
    data = read_json(_file(), {}) or {}
    level = data.get("default_level", "write")
    return {
        "default_level": level if level in LEVELS else "write",
        "shares": {k: v for k, v in (data.get("shares") or {}).items() if isinstance(v, dict)},
    }


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {"default_level": cfg.get("default_level", "write"), "shares": {}}
    if clean["default_level"] not in LEVELS:
        raise ValueError("default_level must be none, read or write")
    for name, entry in (cfg.get("shares") or {}).items():
        if not re.match(r"^[A-Za-z0-9 ._-]{1,80}$", str(name)):
            raise ValueError(f"Invalid share name: {name!r}")
        users = {}
        for user, lvl in (entry.get("users") or {}).items():
            if lvl not in LEVELS or not re.match(r"^[A-Za-z0-9._-]{1,64}$", str(user)):
                raise ValueError(f"Invalid entry for {name}/{user}")
            users[str(user).lower()] = lvl
        default = entry.get("default")
        if default is not None and default not in LEVELS:
            raise ValueError(f"Invalid default for {name}")
        clean["shares"][name] = {"users": users, **({"default": default} if default else {})}
    atomic_write_json(_file(), clean)
    os.chmod(_file(), 0o600)
    invalidate()
    return clean


def invalidate() -> None:
    with _lock:
        _cache["ts"] = 0.0


def _split_users(value: str | None) -> set:
    return {u.lower() for u in re.split(r"[,\s]+", value or "") if u and not u.startswith(("@", "+", "&"))}


def known_shares() -> list[dict[str, Any]]:
    """[{name, path, samba: {valid, read, write, read_only, guest}}] for every share the platform reports."""
    now = time.time()
    with _lock:
        if now - _cache["ts"] < _CACHE_TTL:
            return list(_cache["shares"])
    shares: dict[str, dict[str, Any]] = {}
    try:
        from backend.hardware.pal_storage import get_storage_platform

        for s in get_storage_platform().list_shares():
            if s.mountpoint:
                shares[s.name] = {"name": s.name, "path": os.path.realpath(s.mountpoint), "samba": None}
    except Exception:
        logger.debug("backend.services.share_access.known_shares: ignored error", exc_info=True)
    try:
        from backend.services.samba_engine import get_samba_engine

        for s in get_samba_engine().list_shares():
            shares[s.name] = {
                "name": s.name,
                "path": os.path.realpath(s.path),
                "samba": {
                    "valid": _split_users(s.valid_users),
                    "read": _split_users(s.read_list),
                    "write": _split_users(s.write_list),
                    "read_only": bool(s.read_only),
                },
            }
    except Exception:
        logger.debug("backend.services.share_access.known_shares: ignored error", exc_info=True)
    result = list(shares.values())
    with _lock:
        _cache.update(ts=now, shares=result)
    return result


def _samba_level(samba: dict[str, Any] | None, username: str) -> str | None:
    if not samba or not (samba["valid"] or samba["read"] or samba["write"]):
        return None
    if username in samba["write"]:
        return "write"
    if username in samba["read"]:
        return "read"
    if samba["valid"] and username not in samba["valid"]:
        return "none"
    return "read" if samba["read_only"] else "write"


def _home_for(username: str) -> str | None:
    try:
        from backend.users_db import get_user_by_username

        user = get_user_by_username(username) or {}
        home = user.get("home_directory")
    except Exception:
        home = None
    home = home or os.path.join(getattr(config, "POOL_PATH", "/mnt/user"), "homes", username)
    return os.path.realpath(home)


def grants_for(username: str) -> list[tuple[str, str]]:
    """[(path, level)] the user may use, most specific first."""
    username = (username or "").lower()
    if not username:
        return []
    cfg = load_config()
    grants: list[tuple[str, str]] = []
    home = _home_for(username)
    if home:
        grants.append((home, "write"))
    for share in known_shares():
        entry = cfg["shares"].get(share["name"], {})
        level = (
            (entry.get("users") or {}).get(username)
            or _samba_level(share["samba"], username)
            or entry.get("default")
            or cfg["default_level"]
        )
        grants.append((share["path"], level))
    grants.sort(key=lambda g: len(g[0]), reverse=True)
    return grants


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def level_for(username: str, real_path: str) -> str:
    """ "write", "read", "list" (a folder above a granted share) or "none"."""
    real = os.path.realpath(real_path)
    # Any ".../homes/<username>" folder is the user's own (same rule as the home check).
    parts = [x for x in real.split("/") if x]
    user = (username or "").lower()
    for i, part in enumerate(parts[:-1]):
        if part == "homes" and parts[i + 1].lower() == user:
            return "write"
    if parts and parts[-1] == "homes" and os.path.isdir(real):
        return "list"
    grants = grants_for(username)
    for root, level in grants:
        if _inside(real, root):
            return level
    if any(_inside(root, real) for root, lvl in grants if lvl != "none") and os.path.isdir(real):
        return "list"
    return "none"
