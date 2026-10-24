"""Getting started checklist (UX-1): what a new owner still has to do, worked out from the
system itself, with where to do it."""

from collections.abc import Callable
from typing import Any

from backend.config import logger


def _safe(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except Exception:
        logger.debug("[GettingStarted] check failed", exc_info=True)
        return False


def _password_changed() -> bool:
    from backend import config

    return not config.is_using_default_password()


def _has_share() -> bool:
    from backend.services.nfs_engine import get_nfs_engine
    from backend.services.samba_engine import get_samba_engine

    return bool(get_samba_engine().list_shares()) or bool(get_nfs_engine().list_exports())


def _has_app() -> bool:
    from backend.hardware.docker_stats import read_docker_containers

    return any(not str(c.get("name") or "").startswith("zettnas") for c in read_docker_containers())


def _has_backup() -> bool:
    from backend.services.backup_engine import get_backup_jobs

    return bool(get_backup_jobs())


def _two_factor(username: str) -> bool:
    from backend.users_db import get_user_by_username, get_user_mfa

    user = get_user_by_username(username or "")
    mfa = get_user_mfa(user["id"]) if user else None
    return bool(mfa and mfa.get("mfa_enabled"))


def _ai_has_files() -> bool:
    from backend.services.rag_engine import get_rag_engine

    return int(get_rag_engine().get_index_stats().get("total_files") or 0) > 0


def _alerts_set_up() -> bool:
    from backend.services.notifications import build_apprise_urls, load_notification_config

    cfg = load_notification_config()
    return bool(cfg.get("enabled")) and bool(build_apprise_urls(cfg))


def checklist(username: str, is_admin: bool) -> dict[str, Any]:
    """Items in the order a new owner should do them. `open` is a Mission Control section key."""
    items = [
        ("password", "system", _safe(_password_changed), True),
        ("two_factor", "system", _safe(lambda: _two_factor(username)), False),
        ("share", "mgmt-pane-storage-shares", _safe(_has_share), True),
        ("app", "catalog", _safe(_has_app), True),
        ("backup", "mgmt-pane-backups", _safe(_has_backup), True),
        ("alerts", "mgmt-pane-notifications", _safe(_alerts_set_up), True),
        ("ai_folder", "ai", _safe(_ai_has_files), True),
    ]
    rows = [
        {"id": item_id, "open": where, "done": done}
        for item_id, where, done, admin_only in items
        if is_admin or not admin_only or item_id == "password"
    ]
    done = sum(1 for r in rows if r["done"])
    return {"items": rows, "done": done, "total": len(rows), "complete": done == len(rows)}
