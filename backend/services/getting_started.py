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


def _host_managed() -> str:
    """The host's name when it makes shares itself (Unraid, TrueNAS…), else ""."""
    from backend.hardware.pal_storage import get_storage_platform

    adapter = get_storage_platform()
    return adapter.get_platform_type().value if adapter.get_capabilities().is_observer_mode else ""


def _has_share() -> bool:
    from backend.services.nfs_engine import get_nfs_engine
    from backend.services.samba_engine import get_samba_engine

    if get_samba_engine().list_shares() or get_nfs_engine().list_exports():
        return True
    from backend.hardware.pal_storage import get_storage_platform

    return bool(get_storage_platform().list_shares())  # shares the host made count too


def _has_app() -> bool:
    from backend.hardware.docker_stats import read_docker_containers

    return any(not str(c.get("name") or "").startswith("zettnas") for c in read_docker_containers())


OFF_BOX_ROOTS = ("/mnt/disks/", "/mnt/remotes/", "/mnt/addons/")  # USB and network disks


def _off_box(where: str) -> bool:
    where = str(where or "")
    return where.startswith("rclone:") or where.startswith(OFF_BOX_ROOTS)


def _has_backup() -> bool:
    """Done once a backup has actually reached somewhere other than this box (REL-27): a cloud
    remote or a USB / network disk, with a successful run. Setting one up is not enough."""
    from backend.services.backup_engine import get_backup_jobs

    for j in get_backup_jobs():
        ok = j.get("last_success_at") or j.get("last_status") == "success"
        if ok and (
            j.get("destination_type") == "remote" or _off_box(j.get("destination_path") or j.get("local_path") or "")
        ):
            return True
    try:
        from backend.services.offsite_backup import list_repos

        for r in list_repos():
            if r.get("last_backup") and str(r.get("last_result") or "") == "ok" and _off_box(r.get("location") or ""):
                return True
    except Exception:
        logger.debug("[GettingStarted] off-site backups unreadable", exc_info=True)
    return False


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


def _invited_someone() -> bool:
    """Someone besides the owner has an account, or an invite is waiting (UX-26)."""
    from backend.users_db import list_invites, users_db_session

    with users_db_session(readonly=True) as conn:
        people = conn.execute("SELECT count(*) FROM users WHERE status = 'active'").fetchone()[0]
    return people > 1 or bool(list_invites())


def _phone_backs_up(username: str) -> bool:
    from backend.services.immich_photos import phone_done

    return phone_done(username)


# What each item needs the person to be able to do (UX-26): an item is shown only to someone who
# can open the place it leads to. None: everyone.
NEEDS: dict[str, tuple[str, ...] | None] = {
    "password": None,
    "two_factor": None,
    "share": ("shares:manage",),
    "share_host": ("shares:manage",),
    "invite": ("users:write",),
    "app": ("containers:manage",),
    "backup": ("backup:write",),
    "alerts": ("system:config",),
    "ai_folder": ("system:config", "ai:manage"),
    "phone_backup": None,
}


def checklist(username: str, is_admin: bool = False, scopes: list[str] | None = None) -> dict[str, Any]:
    """Items in the order a new owner should do them. `open` is a Mission Control section key.
    With `scopes` each item is shown to whoever can open it; without, admins see everything."""
    try:
        host = _host_managed()
    except Exception:
        logger.debug("[GettingStarted] platform unknown", exc_info=True)
        host = ""
    items = [
        ("password", "system", _safe(_password_changed), True),
        ("two_factor", "system", _safe(lambda: _two_factor(username)), False),
        ("share_host" if host else "share", "mgmt-pane-storage-shares", _safe(_has_share), True),
        ("invite", "mgmt-pane-users", _safe(_invited_someone), True),
        ("app", "catalog", _safe(_has_app), True),
        ("backup", "mgmt-pane-backups", _safe(_has_backup), True),
        ("alerts", "mgmt-pane-notifications", _safe(_alerts_set_up), True),
        ("ai_folder", "ai", _safe(_ai_has_files), True),
        ("phone_backup", "mgmt-pane-backups", _safe(lambda: _phone_backs_up(username)), False),
    ]

    def shown(item_id: str, admin_only: bool) -> bool:
        if scopes is not None:
            from backend.auth import has_scope

            needs = NEEDS.get(item_id)
            return not needs or any(has_scope(scopes, s) for s in needs)
        return is_admin or not admin_only or item_id in ("password", "phone_backup")

    rows = [
        {"id": item_id, "open": where, "done": done, "host": host if item_id == "share_host" else ""}
        for item_id, where, done, admin_only in items
        if shown(item_id, admin_only)
    ]
    done = sum(1 for r in rows if r["done"])
    return {"items": rows, "done": done, "total": len(rows), "complete": done == len(rows)}
