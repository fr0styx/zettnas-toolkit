"""Security Advisor checks for settings that are now safer by default (B11, D1).

New installs start safe. Upgraded installs keep what they had, and each setting that is
looser than the new default shows here as a finding with a one-click fix. Every fix needs
the person to confirm it first (the "security.advisor_fix" confirmation).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from backend.config import logger

FAMILY_ROLES = ("kid", "guest")


def _family_users() -> list[str]:
    from backend.users_db import users_db_session

    marks = ",".join("?" for _ in FAMILY_ROLES)
    with users_db_session() as conn:
        rows = conn.execute(
            f"SELECT username FROM users WHERE role_id IN ({marks}) AND COALESCE(status, 'active') = 'active'",
            FAMILY_ROLES,
        ).fetchall()
    return [r["username"] for r in rows]


def _share_access_finding() -> dict[str, Any] | None:
    """Kids and guests reach every share because the install-wide default lets everyone in."""
    from backend.services.share_access import load_config

    cfg = load_config()
    if cfg["default_level"] == "none":
        return None
    open_roles = [r for r in FAMILY_ROLES if cfg["role_defaults"].get(r, cfg["default_level"]) != "none"]
    people = _family_users() if open_roles else []
    if not people:
        return None
    return {
        "id": "share_access_family",
        "name": "Kids and guests can open every shared folder",
        "penalty": 10,
        "severity": "medium",
        "details": f"{', '.join(sorted(people))} can use any shared folder nobody set access for.",
        "remediation": "Give kids and guests no access by default; then share folders with them one by one.",
        "fix": "share_access_family",
        "fix_label": "Give kids and guests only the folders I choose",
    }


def _fix_share_access_family() -> str:
    from backend.fsutil import locked_json
    from backend.services import share_access

    with locked_json(share_access._file()):
        cfg = share_access.load_config()
        cfg["role_defaults"] = {**cfg["role_defaults"], **{r: "none" for r in FAMILY_ROLES}}
        share_access.save_config(cfg)
    return "Kids and guests now open only the folders you share with them."


def _open_nfs_exports() -> list[Any]:
    from backend.services.nfs_engine import get_nfs_engine

    return [r for r in get_nfs_engine().list_exports() if r.clients.strip() == "*" or r.squash == "no_root_squash"]


def _nfs_finding() -> dict[str, Any] | None:
    rules = _open_nfs_exports()
    if not rules:
        return None
    parts = []
    for r in rules:
        why = [
            w for w, bad in (("any host", r.clients.strip() == "*"), ("root kept", r.squash == "no_root_squash")) if bad
        ]
        parts.append(f"{r.name} ({', '.join(why)})")
    return {
        "id": "nfs_open_exports",
        "name": "NFS exports open to every host or with root kept",
        "penalty": 15,
        "severity": "high",
        "details": "; ".join(parts),
        "remediation": "Limit each export to this home network and map remote root to an unprivileged user.",
        "fix": "nfs_open_exports",
        "fix_label": "Limit to this home network",
    }


def _fix_nfs_open_exports() -> str:
    from backend.services.nfs_engine import get_nfs_engine, home_network

    engine = get_nfs_engine()
    net = home_network()
    names = []
    for rule in _open_nfs_exports():
        update: dict[str, Any] = {}
        if rule.clients.strip() == "*":
            update["clients"] = net
        if rule.squash == "no_root_squash":
            update["squash"] = "root_squash"
        engine.add_or_update_export(rule.model_copy(update=update))
        names.append(rule.name)
    return f"Limited {', '.join(names)} to {net}." if names else "Nothing to change."


def _fix_smb_guest() -> str:
    from backend.services.samba_engine import get_samba_engine

    engine = get_samba_engine()
    fixed, failed = [], []
    for share in engine.list_shares():
        if not share.guest_ok:
            continue
        try:
            engine.add_or_update_share(share.model_copy(update={"guest_ok": False}))
            fixed.append(share.name)
        except Exception as e:
            logger.warning(f"[SecurityAdvisor] Could not make {share.name} private: {e}")
            failed.append(share.name)
    msg = f"{', '.join(fixed)} now need a sign-in." if fixed else "Nothing changed."
    return msg + (f" Not changed: {', '.join(failed)}." if failed else "")


def _auditor_scopes() -> list[str] | None:
    from backend.users_db import users_db_session

    with users_db_session() as conn:
        row = conn.execute("SELECT scopes_json FROM roles WHERE id = 'auditor'").fetchone()
    if not row:
        return None
    try:
        return list(json.loads(row["scopes_json"] or "[]"))
    except (TypeError, ValueError):
        return None


def _auditor_finding() -> dict[str, Any] | None:
    scopes = _auditor_scopes()
    if not scopes or "*:read" not in scopes:
        return None
    return {
        "id": "auditor_reads_everything",
        "name": "The Auditor role can read everyone's files and chats",
        "penalty": 5,
        "severity": "low",
        "details": "Auditor has *:read, which includes people's files, chats and backups, not only system status.",
        "remediation": "Limit Auditor to system status, hardware, logs, the audit log and storage health.",
        "fix": "auditor_reads_everything",
        "fix_label": "Limit Auditor to system status",
    }


def _fix_auditor() -> str:
    from backend.services.install_defaults import SAFE_AUDITOR_SCOPES
    from backend.users_db import _TOKEN_CACHE, _TOKEN_CACHE_LOCK, users_db_session

    with users_db_session() as conn:
        conn.execute("UPDATE roles SET scopes_json = ? WHERE id = 'auditor'", (json.dumps(SAFE_AUDITOR_SCOPES),))
    with _TOKEN_CACHE_LOCK:  # cached tokens carry the role's old scopes
        _TOKEN_CACHE.clear()
    return "Auditor now reads system status only."


def _ai_search_finding() -> dict[str, Any] | None:
    """Kids or guests can use AI search (kept on for installs upgraded from before AI-26)."""
    from backend.services import ai_access

    access = ai_access.role_access(feature="search")
    open_roles = [r for r in FAMILY_ROLES if access.get(r, True)]
    if not open_roles or not _family_users():
        return None
    return {
        "id": "ai_search_family",
        "name": "Kids and guests can use AI search",
        "penalty": 5,
        "severity": "low",
        "details": "AI search shows them what their folders hold by meaning, photos included.",
        "remediation": "Turn AI search off for kids and guests; turn it on per role in AI settings when wanted.",
        "fix": "ai_search_family",
        "fix_label": "Turn AI search off for kids and guests",
    }


def _fix_ai_search_family() -> str:
    from backend.services.rag_engine import get_rag_engine

    get_rag_engine().update_config({"ai_search_role_access": {r: False for r in FAMILY_ROLES}})
    return "AI search is off for kids and guests."


FINDERS: tuple[Callable[[], dict[str, Any] | None], ...] = (
    _share_access_finding,
    _nfs_finding,
    _auditor_finding,
    _ai_search_finding,
)

FIXES: dict[str, Callable[[], str]] = {
    "share_access_family": _fix_share_access_family,
    "nfs_open_exports": _fix_nfs_open_exports,
    "smb_guest_access": _fix_smb_guest,
    "auditor_reads_everything": _fix_auditor,
    "ai_search_family": _fix_ai_search_family,
}


def findings() -> list[dict[str, Any]]:
    out = []
    for find in FINDERS:
        try:
            item = find()
        except Exception as e:
            logger.debug(f"[SecurityAdvisor] {find.__name__} failed: {e}")
            continue
        if item:
            out.append(item)
    return out


def apply_fix(fix_id: str) -> str:
    fix = FIXES.get(fix_id)
    if fix is None:
        raise KeyError(fix_id)
    return fix()
