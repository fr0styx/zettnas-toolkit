"""
One-time hardening for installs upgrading to v1.9.2.

Before v1.9.2 a revoked or disabled user's session could turn into a
superadmin session (SEC-01) and WebDAV accepted admin/admin (SEC-02). Anything
issued while those holes were open can't be trusted, so on the first start of
this version:

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
        "[SecurityUpgrade] v1.9.2 one-time hardening: revoked %(sessions)s sessions and %(api_tokens)s API "
        "tokens, %(admins_flagged)s admin account(s) must set a new password, WebDAV %(webdav)s." % result
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
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            json.dump({"applied_at": time.time(), **result}, f)
        os.chmod(marker, 0o600)
    except OSError as e:
        logger.error(f"[SecurityUpgrade] Could not write marker {marker}: {e}")
    return True
