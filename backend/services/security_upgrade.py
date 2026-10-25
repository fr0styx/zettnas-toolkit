"""
One-time hardening for installs upgrading to v1.9.2.

Before v1.9.2 a revoked or disabled user's session could turn into a
superadmin session (SEC-01), and WebDAV authentication has been tightened.
Credentials issued before this version can't be trusted, so on the first start
of this version:

- every session and API token is revoked, and sessions.json* is deleted;
- WebDAV is switched off unless it has a dedicated credential, and its
  "no authentication" option is turned off;
- every local admin account must choose a new password at next login.

A marker file in DATA_DIR makes this run once.
"""

import json
import logging
import os
import time

from backend import config
from backend.fsutil import atomic_write_json

logger = logging.getLogger("ZettNAS")

MARKER_NAME = ".security-upgrade-1.9.2"
ADMIN_ROLES = ("superadmin", "admin")


def _marker_path() -> str:
    return os.path.join(config.DATA_DIR, MARKER_NAME)


def _webdav_has_dedicated_credential(cfg: dict) -> bool:
    password = str(cfg.get("password") or "")
    return len(password) >= 8 and password.lower() != "admin"


def _harden_webdav() -> str:
    from backend.services.webdav_engine import get_webdav_engine

    engine = get_webdav_engine()
    cfg = engine.load_config()
    changes = {}
    if not cfg.get("auth_enabled", True):
        changes["auth_enabled"] = True
    if cfg.get("enabled") and not _webdav_has_dedicated_credential(cfg):
        changes["enabled"] = False
    if changes:
        engine.save_config(changes)
    if changes.get("enabled") is False:
        return "disabled"
    return "auth_forced" if changes else "unchanged"


def _revoke_credentials_and_flag_admins() -> dict:
    from backend.users_db import (
        _SESSION_CACHE,
        _SESSION_CACHE_LOCK,
        _TOKEN_CACHE,
        _TOKEN_CACHE_LOCK,
        users_db_session,
    )

    with users_db_session(None) as conn:
        sessions = conn.execute("DELETE FROM sessions").rowcount
        tokens = conn.execute("DELETE FROM api_tokens").rowcount
        placeholders = ",".join("?" for _ in ADMIN_ROLES)
        admins = conn.execute(
            f"UPDATE users SET must_change_password = 1 WHERE role_id IN ({placeholders}) "
            "AND COALESCE(idp_type, 'local') = 'local' AND status = 'active'",
            ADMIN_ROLES,
        ).rowcount
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.clear()
    return {"sessions": sessions, "api_tokens": tokens, "admins_flagged": admins}


def run_once() -> bool:
    """Applies the v1.9.2 hardening if it hasn't run on this install. Returns True if it ran."""
    marker = _marker_path()
    if os.path.exists(marker):
        return False

    from backend.auth import purge_legacy_session_files

    purge_legacy_session_files()
    result = _revoke_credentials_and_flag_admins()
    try:
        result["webdav"] = _harden_webdav()
    except Exception as e:  # never block startup on WebDAV config
        logger.error(f"[SecurityUpgrade] Could not harden WebDAV config: {e}")
        result["webdav"] = f"error: {e}"

    logger.warning(
        "[SecurityUpgrade] v1.9.2 one-time hardening: revoked {sessions} sessions and {api_tokens} API "
        "tokens, {admins_flagged} admin account(s) must set a new password, WebDAV {webdav}.".format(**result)
    )
    try:
        from backend.state import add_event

        msg = (
            "Security update applied: everyone was signed out, API tokens were revoked "
            "and admins must choose a new password."
        )
        if result["webdav"] == "disabled":
            msg += " WebDAV was turned off; re-enable it in Settings if you use it."
        add_event("warning", "Security update (v1.9.2)", msg, details=result)
    except Exception as e:
        logger.debug(f"[SecurityUpgrade] Could not record event: {e}")

    try:
        atomic_write_json(marker, {"applied_at": time.time(), **result})  # owner-only (0600)
    except OSError as e:
        logger.error(f"[SecurityUpgrade] Could not write marker {marker}: {e}")
    return True


# ---------------------------------------------------------------------------------------------
# v1.10.2: state left behind by the weaknesses fixed in this release (Batch 0)
# ---------------------------------------------------------------------------------------------
MARKER_1_10_2 = ".security-upgrade-1.10.2"
KNOWLEDGE_ROLES = ("storage_admin", "app_operator", "backup_operator", "share_user")


def _grant_knowledge_scope() -> int:
    """System roles that use Ask Zetty get ai:knowledge:read, now needed to read files over MCP."""
    from backend.users_db import users_db_session

    changed = 0
    with users_db_session(None) as conn:
        for role_id in KNOWLEDGE_ROLES:
            row = conn.execute("SELECT scopes_json FROM roles WHERE id = ? AND is_system = 1", (role_id,)).fetchone()
            if not row:
                continue
            scopes = json.loads(row["scopes_json"] or "[]")
            if "ai:knowledge:read" not in scopes:
                scopes.append("ai:knowledge:read")
                conn.execute("UPDATE roles SET scopes_json = ? WHERE id = ?", (json.dumps(scopes), role_id))
                changed += 1
    return changed


def _revoke_stale_wildcard_tokens() -> int:
    """'Everything' tokens whose owner is no longer a superadmin (they were never capped before)."""
    from backend.users_db import _TOKEN_CACHE, _TOKEN_CACHE_LOCK, users_db_session

    revoked = 0
    with users_db_session(None) as conn:
        rows = conn.execute(
            "SELECT t.token_id, t.scopes_json, r.scopes_json AS role_scopes FROM api_tokens t "
            "JOIN users u ON t.user_id = u.id LEFT JOIN roles r ON u.role_id = r.id"
        ).fetchall()
        for row in rows:
            token_scopes = json.loads(row["scopes_json"] or "[]")
            role_scopes = json.loads(row["role_scopes"] or "[]")
            if "*" in token_scopes and "*" not in role_scopes:
                conn.execute("DELETE FROM api_tokens WHERE token_id = ?", (row["token_id"],))
                revoked += 1
    if revoked:
        with _TOKEN_CACHE_LOCK:
            _TOKEN_CACHE.clear()
    return revoked


def _seal_backup_passphrases() -> int:
    from backend import secret_box
    from backend.services.backup_engine import BACKUP_JOBS_FILE, get_backup_jobs

    jobs = get_backup_jobs()
    sealed = 0
    for job in jobs:
        value = str(job.get("encryption_password") or "")
        if value and not secret_box.is_sealed(value):
            job["encryption_password"] = secret_box.seal(value)
            sealed += 1
    if sealed:
        atomic_write_json(BACKUP_JOBS_FILE, jobs)
    return sealed


def run_1_10_2_once() -> bool:
    """Cleans up after the Batch 0 fixes once per install. Returns True if it ran."""
    marker = os.path.join(config.DATA_DIR, MARKER_1_10_2)
    if os.path.exists(marker):
        return False
    result: dict = {}
    for key, step in (
        ("roles_granted_knowledge", _grant_knowledge_scope),
        ("wildcard_tokens_revoked", _revoke_stale_wildcard_tokens),
        ("backup_passphrases_sealed", _seal_backup_passphrases),
    ):
        try:
            result[key] = step()
        except Exception as e:  # one failed step must not block startup or the others
            logger.error(f"[SecurityUpgrade] 1.10.2 step {key} failed: {e}")
            result[key] = f"error: {e}"
    try:
        from backend.services.webdav_engine import get_webdav_engine

        get_webdav_engine().ensure_config_defaults()  # turns sign-in back on, resets an unsafe folder
    except Exception as e:
        logger.error(f"[SecurityUpgrade] 1.10.2 WebDAV check failed: {e}")
    logger.warning(f"[SecurityUpgrade] v1.10.2 one-time cleanup: {result}")
    try:
        from backend.state import add_event

        msg = (
            "Security update applied. If anyone other than you could manage shares or containers, "
            "review your API tokens and turn two-factor sign-in off and on again to get a new code."
        )
        if isinstance(result.get("wildcard_tokens_revoked"), int) and result["wildcard_tokens_revoked"]:
            msg += f" {result['wildcard_tokens_revoked']} API token(s) of accounts that are no longer superadmins were revoked."
        add_event("warning", "Security update (v1.10.2)", msg, details=result)
    except Exception as e:
        logger.debug(f"[SecurityUpgrade] Could not record event: {e}")
    try:
        atomic_write_json(marker, {"applied_at": time.time(), **result})
    except OSError as e:
        logger.error(f"[SecurityUpgrade] Could not write marker {marker}: {e}")
    return True
