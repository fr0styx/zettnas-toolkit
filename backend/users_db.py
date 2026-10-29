"""
Enterprise Identity, Multi-User, and RBAC Persistence Layer.

Provides high-performance SQLite-backed storage operating in Write-Ahead Logging (WAL)
mode for users, roles, sessions, scoped API tokens, and security audit logs.
Includes transparent zero-downtime migration from legacy security.json, sessions.json,
and api_tokens.json files.
"""

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Optional

from backend import config
from backend.config import DATA_DIR, logger
from backend.ignored_errors import ignored
from backend.passwords import hash_password, needs_rehash, verify_password
from backend.settings import test_mode

USERS_DB_PATH = getattr(config, "USERS_DB_PATH", os.path.join(DATA_DIR, "users.db"))
_db_lock = threading.RLock()

# In-memory session cache: token_hash -> session_dict
_SESSION_CACHE: dict[str, dict[str, Any]] = {}
_SESSION_CACHE_LOCK = threading.RLock()

# In-memory API token cache: token_hash -> token_dict
_TOKEN_CACHE: dict[str, dict[str, Any]] = {}
_TOKEN_CACHE_LOCK = threading.RLock()


def get_users_db_connection(db_path: str | None = None) -> sqlite3.Connection:
    from backend.sqlite_conn import connect

    return connect("users", db_path or getattr(config, "USERS_DB_PATH", USERS_DB_PATH))


@contextmanager
def users_db_session(db_path: str | None = None, readonly: bool = False):
    if readonly:
        conn = get_users_db_connection(db_path)
        try:
            yield conn
        finally:
            conn.close()
    else:
        with _db_lock:
            conn = get_users_db_connection(db_path)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()


# ==============================================================================
# 1. Database Initialization & Schema Migration
# ==============================================================================

DEFAULT_ROLES = [
    {
        "id": "superadmin",
        "name": "SuperAdmin",
        "description": "Unrestricted access to all subsystems, hardware, security, and user management",
        "scopes": ["*"],
        "is_system": 1,
    },
    {
        "id": "storage_admin",
        "name": "StorageAdmin",
        "description": "Manage disks, pools, SMART tests, scrubs, shares, and filesystem quotas",
        "scopes": [
            "storage:*",
            "shares:*",
            "system:view",
            "hardware:read",
            "logs:read",
            "audit:read",
            "ai:knowledge:read",
        ],
        "is_system": 1,
    },
    {
        "id": "app_operator",
        "name": "AppOperator",
        "description": "Deploy, inspect, restart, and edit Docker containers and apps",
        "scopes": ["containers:*", "system:view", "logs:read", "ai:knowledge:read"],
        "is_system": 1,
    },
    {
        "id": "backup_operator",
        "name": "BackupOperator",
        "description": "Trigger, view, and schedule configuration and data backups",
        "scopes": ["backup:*", "storage:read", "shares:read", "system:view", "logs:read", "ai:knowledge:read"],
        "is_system": 1,
    },
    {
        "id": "share_user",
        "name": "ShareUser",
        "description": "Access permitted file shares, personal home directory, and media ingest",
        "scopes": ["shares:read", "shares:user_write", "system:view", "ai:knowledge:read"],
        "is_system": 1,
    },
    {
        "id": "guest",
        "name": "Guest",
        "description": "Read-only access to the shares granted to them; nothing else",
        "scopes": ["shares:read"],
        "is_system": 1,
    },
    {
        "id": "kid",
        "name": "Kid",
        "description": "Their own private folder and the family shares granted to them; no settings, no AI web access",
        "scopes": ["shares:read", "shares:user_write"],
        "is_system": 1,
    },
    {
        "id": "auditor",
        "name": "Auditor",
        "description": "Read-only access to system telemetry, metrics, event logs, and status",
        # B11 (SEC-30): not *:read, which also read people's chats, files and backups
        "scopes": ["system:view", "hardware:read", "logs:read", "audit:read", "storage:read"],
        "is_system": 1,
    },
]


def init_users_db(db_path: str | None = None) -> None:
    """Initialize SQLite tables for users, roles, sessions, API tokens, and audit logs."""
    target_path = db_path or USERS_DB_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    with users_db_session(target_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        # 1. Roles table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                scopes_json TEXT NOT NULL,
                is_system INTEGER DEFAULT 1,
                created_at REAL NOT NULL
            );
        """)

        # 2. Users table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                display_name TEXT NOT NULL,
                email TEXT DEFAULT '',
                password_hash TEXT NOT NULL,
                role_id TEXT NOT NULL REFERENCES roles(id),
                status TEXT DEFAULT 'active',
                must_change_password INTEGER DEFAULT 0,
                avatar_url TEXT DEFAULT '',
                home_directory TEXT DEFAULT '',
                storage_quota_bytes INTEGER DEFAULT 0,
                preferences_json TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_login_at REAL,
                last_login_ip TEXT DEFAULT '',
                signin_hours_json TEXT DEFAULT ''
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")

        # 3. Sessions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                username TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                last_active_at REAL NOT NULL,
                ip_address TEXT DEFAULT '',
                user_agent TEXT DEFAULT '',
                is_remembered INTEGER DEFAULT 0
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);")

        # 4. Scoped API tokens table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_tokens (
                token_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                masked_token TEXT NOT NULL,
                scopes_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL,
                last_used_at REAL,
                last_used_ip TEXT DEFAULT '',
                folders_json TEXT DEFAULT '[]',
                last_client TEXT DEFAULT ''
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_api_tokens_token_hash ON api_tokens(token_hash);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_api_tokens_user_id ON api_tokens(user_id);")

        # 5. Security audit log table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS security_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                actor_id TEXT,
                actor_username TEXT,
                actor_ip TEXT,
                actor_user_agent TEXT,
                status TEXT NOT NULL,
                details_json TEXT DEFAULT '{}',
                timestamp REAL NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_security_audit_ts ON security_audit_log(timestamp DESC);")

        # 6. Invite links (Batch 6): only a hash of each token is stored
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invites (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                role_id TEXT NOT NULL,
                quota_bytes INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                max_uses INTEGER NOT NULL DEFAULT 1,
                uses INTEGER NOT NULL DEFAULT 0,
                created_by TEXT,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
        """)

        # Columns added after the users table first shipped (MFA, IdP): see db_schema (ARC-8)
        from backend.db_schema import ensure_columns

        ensure_columns(conn, "users.db")

        # Seed default roles if missing
        now = time.time()
        for r in DEFAULT_ROLES:
            conn.execute(
                """
                INSERT OR IGNORE INTO roles (id, name, description, scopes_json, is_system, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (r["id"], r["name"], r["description"], json.dumps(r["scopes"]), r["is_system"], now),
            )

    # Perform zero-downtime migration from legacy files
    migrate_legacy_data(target_path)


def _shared_default_allowed() -> bool:
    """Only the test suite may bootstrap with the published 'admin' password."""
    return test_mode() and os.environ.get("ZETTNAS_ALLOW_DEFAULT_PASSWORD", "1") == "1"


def _first_time_password() -> str:
    """A per-install first sign-in password instead of the shared default 'admin'.

    Saved (mode 0600) in DATA_DIR and written to the log once, so only someone with
    access to the server or its logs can claim a fresh install.
    """
    import secrets

    path = config.initial_password_file()
    try:
        with open(path, encoding="utf-8") as f:
            existing = f.read().strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        return existing
    password = secrets.token_urlsafe(15)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(password + "\n")
    # SEC-35: never in the log (logs are shared, shipped and kept); read it from the file
    logger.warning(
        "First-time admin sign-in: user 'admin', with the password saved in %s (readable by root only). "
        "You will be asked to choose your own password.",
        path,
    )
    return password


def _forget_first_time_password() -> None:
    path = config.initial_password_file()
    if not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError as e:
        logger.warning(f"Could not remove the first-time password file: {e}")


def migrate_legacy_data(db_path: str | None = None) -> None:
    """Seamlessly migrates existing security.json, sessions.json, and api_tokens.json."""
    target_path = db_path or USERS_DB_PATH
    now = time.time()

    with users_db_session(target_path) as conn:
        user_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]

        admin_id = "admin-00000000-0000-0000-0000-000000000001"
        admin_username = getattr(config, "ZETTNAS_USERNAME", "admin") or "admin"

        if user_count == 0:
            logger.info("Migrating legacy single-user configuration into SQLite users.db...")

            password_hash = getattr(config, "STORED_PASSWORD_HASH", "")
            email = getattr(config, "ZETTNAS_EMAIL", "") or ""

            # Check if security.json exists on disk for freshest values
            sec_file = getattr(config, "SECURITY_FILE", os.path.join(DATA_DIR, "security.json"))
            if os.path.exists(sec_file):
                try:
                    with open(sec_file) as f:
                        data = json.load(f)
                        password_hash = data.get("password_hash") or password_hash
                        admin_username = data.get("username") or admin_username
                        email = data.get("email") or email
                except Exception as e:
                    logger.warning(f"Could not read legacy {sec_file}: {e}")

            if not password_hash:
                password_hash = hash_password("admin")
            generated = False
            if verify_password("admin", password_hash) and not _shared_default_allowed():
                password_hash = hash_password(_first_time_password())
                config.STORED_PASSWORD_HASH = password_hash
                generated = True

            # Insert primary SuperAdmin
            conn.execute(
                """
                INSERT INTO users (
                    id, username, display_name, email, password_hash, role_id, status,
                    must_change_password, home_directory, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    admin_id,
                    admin_username,
                    "Administrator",
                    email,
                    password_hash,
                    "superadmin",
                    "active",
                    1 if generated or verify_password("admin", password_hash) else 0,
                    f"/mnt/user/homes/{admin_username}",
                    now,
                    now,
                ),
            )

            # Legacy sessions.json is not imported: users sign in again (SEC-01).

            # Ingest legacy API tokens from api_tokens.json
            tok_file = os.path.join(DATA_DIR, "api_tokens.json")
            if os.path.exists(tok_file):
                try:
                    with open(tok_file) as f:
                        raw_tokens = json.load(f)
                    migrated_tok = 0
                    for tid, tdata in raw_tokens.items():
                        if isinstance(tdata, dict) and "hash" in tdata:
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO api_tokens (
                                    token_id, user_id, name, token_hash, masked_token,
                                    scopes_json, created_at, expires_at, last_used_at, last_used_ip
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                                (
                                    tid,
                                    admin_id,
                                    tdata.get("name", "Legacy API Token"),
                                    tdata.get("hash"),
                                    tdata.get("masked_token", "zat_..."),
                                    json.dumps(["*"]),
                                    tdata.get("created", now),
                                    None,
                                    None,
                                    "",
                                ),
                            )
                            migrated_tok += 1
                    logger.info(f"Migrated {migrated_tok} API tokens from {tok_file} with SuperAdmin scope")
                    shutil.copy2(tok_file, tok_file + ".bak")
                except Exception as e:
                    logger.warning(f"Failed to migrate legacy API tokens: {e}")

            # Log audit event
            conn.execute(
                """
                INSERT INTO security_audit_log (
                    event_type, actor_id, actor_username, actor_ip, actor_user_agent, status, details_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "auth.migration.completed",
                    admin_id,
                    admin_username,
                    "127.0.0.1",
                    "system",
                    "success",
                    json.dumps({"migrated_from": ["security.json", "sessions.json", "api_tokens.json"]}),
                    now,
                ),
            )
            logger.info("Zero-downtime user store migration complete.")


# ==============================================================================
# 2. User Management Operations
# ==============================================================================


def get_user_by_id(user_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    with users_db_session(db_path, readonly=True) as conn:
        row = conn.execute(
            """
            SELECT u.*, r.name AS role_name, r.scopes_json
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.id = ?
        """,
            (user_id,),
        ).fetchone()
        if not row:
            return None
        res = dict(row)
        res["scopes"] = json.loads(res.pop("scopes_json", "[]"))
        res["preferences"] = json.loads(res.pop("preferences_json", "{}"))
        return res


def get_user_by_username(username: str, db_path: str | None = None) -> dict[str, Any] | None:
    if not username:
        return None
    with users_db_session(db_path, readonly=True) as conn:
        row = conn.execute(
            """
            SELECT u.*, r.name AS role_name, r.scopes_json
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.username = ? COLLATE NOCASE
        """,
            (username.strip(),),
        ).fetchone()
        if not row:
            return None
        res = dict(row)
        res["scopes"] = json.loads(res.pop("scopes_json", "[]"))
        res["preferences"] = json.loads(res.pop("preferences_json", "{}"))
        return res


def get_user_by_idp(idp_type: str, idp_sub: str, db_path: str | None = None) -> dict[str, Any] | None:
    """The user linked to this identity-provider subject (M6)."""
    if not idp_sub:
        return None
    with users_db_session(db_path, readonly=True) as conn:
        row = conn.execute(
            "SELECT username FROM users WHERE idp_type = ? AND idp_sub = ?", (idp_type, idp_sub)
        ).fetchone()
    return get_user_by_username(row["username"], db_path) if row else None


def set_user_idp(user_id: str, idp_type: str, idp_sub: str, db_path: str | None = None) -> None:
    with users_db_session(db_path) as conn:
        conn.execute(
            "UPDATE users SET idp_type = ?, idp_sub = ?, updated_at = ? WHERE id = ?",
            (idp_type, idp_sub, time.time(), user_id),
        )


def list_users(db_path: str | None = None) -> list[dict[str, Any]]:
    with users_db_session(db_path, readonly=True) as conn:
        rows = conn.execute("""
            SELECT u.id, u.username, u.display_name, u.email, u.role_id, r.name AS role_name,
                   u.status, u.must_change_password, u.avatar_url, u.home_directory,
                   u.storage_quota_bytes, u.mfa_enabled, u.idp_type, u.created_at, u.last_login_at, u.last_login_ip
            FROM users u
            JOIN roles r ON u.role_id = r.id
            ORDER BY u.created_at ASC
        """).fetchall()
        res = []
        for r in rows:
            d = dict(r)
            d["mfa_enabled"] = bool(d.get("mfa_enabled", 0))
            res.append(d)
        return res


def unsafe_username(name: str) -> bool:
    """A username that can't be a folder name: every account gets <pool>/homes/<username>, so
    ".." would make the whole pool someone's private folder."""
    name = str(name or "")
    return name.startswith(".") or any(ch in name for ch in "/\\\x00") or any(ord(ch) < 32 for ch in name)


def create_user(
    username: str,
    display_name: str,
    password: str,
    email: str = "",
    role_id: str = "share_user",
    storage_quota_bytes: int = 0,
    idp_type: str = "local",
    idp_sub: str = "",
    db_path: str | None = None,
    home_directory: str | None = None,
) -> dict[str, Any]:
    username_clean = username.strip().lower()
    if len(username_clean) < 2 or len(username_clean) > 32:
        raise ValueError("Username must be between 2 and 32 characters.")
    if unsafe_username(username_clean):
        raise ValueError("A username can't start with a dot or contain slashes.")

    now = time.time()
    user_id = str(uuid.uuid4())
    pwd_hash = hash_password(password)

    resolved_home = home_directory or f"{getattr(config, 'POOL_PATH', '/mnt/user')}/homes/{username_clean}"

    with users_db_session(db_path) as conn:
        # Check role exists
        role = conn.execute("SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
        if not role:
            role_id = "share_user"

        conn.execute(
            """
            INSERT INTO users (
                id, username, display_name, email, password_hash, role_id, status,
                must_change_password, home_directory, storage_quota_bytes,
                idp_type, idp_sub, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                user_id,
                username_clean,
                display_name.strip() or username_clean,
                email.strip(),
                pwd_hash,
                role_id,
                "active",
                0,
                resolved_home,
                storage_quota_bytes,
                idp_type,
                idp_sub,
                now,
                now,
            ),
        )

    ret = get_user_by_id(user_id, db_path)
    if ret:
        try:
            from backend.services.samba_engine import get_samba_engine

            get_samba_engine().sync_samba_user(username=username_clean, password=password)
        except Exception:
            ignored("backend.users_db.create_user")
    return ret


def update_user_password(
    user_id: str,
    new_password: str,
    db_path: str | None = None,
    keep_token: str | None = None,
    revoke_tokens: bool = False,
) -> bool:
    """Sets a new password and ends the user's sessions (except `keep_token`, the caller's own).

    `revoke_tokens` also deletes the user's API tokens: an admin resetting someone's password
    (often after a compromise) must not leave working tokens behind (SEC-4)."""
    new_hash = hash_password(new_password)
    now = time.time()
    keep_hash = hashlib.sha256(keep_token.encode("utf-8")).hexdigest() if keep_token else ""
    with users_db_session(db_path) as conn:
        res = conn.execute(
            """
            UPDATE users SET password_hash = ?, updated_at = ?, must_change_password = 0 WHERE id = ?
        """,
            (new_hash, now, user_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND session_id_hash != ?", (user_id, keep_hash))
        if revoke_tokens:
            conn.execute("DELETE FROM api_tokens WHERE user_id = ?", (user_id,))
    # Clear in-memory cache
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()
    if revoke_tokens:
        _evict_user_caches(user_id)
    if res.rowcount > 0 and user_id == "admin-00000000-0000-0000-0000-000000000001":
        _forget_first_time_password()
    if res.rowcount > 0:
        try:
            user = get_user_by_id(user_id, db_path=db_path)
            if user:
                from backend.services.samba_engine import get_samba_engine

                get_samba_engine().sync_samba_user(username=user["username"], password=new_password)
        except Exception:
            ignored("backend.users_db.update_user_password")
    return res.rowcount > 0


def _evict_user_caches(user_id: str) -> None:
    """Drops one user's cached sessions and API tokens so the next request re-reads role and status."""
    with _SESSION_CACHE_LOCK:
        for k in [k for k, v in _SESSION_CACHE.items() if v.get("user_id") == user_id]:
            _SESSION_CACHE.pop(k, None)
    with _TOKEN_CACHE_LOCK:
        for k in [k for k, v in _TOKEN_CACHE.items() if v.get("user_id") == user_id]:
            _TOKEN_CACHE.pop(k, None)


def assert_remaining_superadmin_guard(
    conn: sqlite3.Connection, target_user_id: str, action: str = "disable, demote, or delete"
) -> None:
    """Ensures at least one OTHER active SuperAdmin exists before mutating or deleting target_user_id."""
    row = conn.execute("SELECT role_id, status FROM users WHERE id = ?", (target_user_id,)).fetchone()
    if row and row["role_id"] == "superadmin" and row["status"] == "active":
        other_admins = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE role_id = 'superadmin' AND status = 'active' AND id != ?",
            (target_user_id,),
        ).fetchone()["c"]
        if other_admins < 1:
            raise ValueError(f"Cannot {action} the only active SuperAdmin.")


def update_user_profile(
    user_id: str,
    display_name: str | None = None,
    email: str | None = None,
    role_id: str | None = None,
    status: str | None = None,
    storage_quota_bytes: int | None = None,
    preferences: dict[str, Any] | None = None,
    db_path: str | None = None,
    signin_hours: dict[str, Any] | None | bool = False,
) -> bool:
    """signin_hours: a dict sets them, None removes them, False (the default) leaves them as they are."""
    now = time.time()
    with users_db_session(db_path) as conn:
        if status is not None and status != "active":
            assert_remaining_superadmin_guard(conn, user_id, action="disable")
        elif role_id is not None and role_id != "superadmin":
            assert_remaining_superadmin_guard(conn, user_id, action="demote")

        updates = ["updated_at = ?"]
        params: list[Any] = [now]

        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name.strip())
        if email is not None:
            updates.append("email = ?")
            params.append(email.strip())
        if role_id is not None:
            updates.append("role_id = ?")
            params.append(role_id)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if storage_quota_bytes is not None:
            updates.append("storage_quota_bytes = ?")
            params.append(storage_quota_bytes)
        if preferences is not None:
            updates.append("preferences_json = ?")
            params.append(json.dumps(preferences))
        if signin_hours is not False:
            updates.append("signin_hours_json = ?")
            params.append(json.dumps(signin_hours) if signin_hours else "")

        params.append(user_id)
        res = conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        if status is not None and status != "active":
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        changed = res.rowcount > 0
    if role_id is not None or status is not None:
        _evict_user_caches(user_id)
    return changed


def delete_user(user_id: str, db_path: str | None = None) -> bool:
    """Deletes a user. Prevents deleting the last superadmin."""
    target_user = get_user_by_id(user_id, db_path=db_path)
    with users_db_session(db_path) as conn:
        user = conn.execute("SELECT role_id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return False
        assert_remaining_superadmin_guard(conn, user_id, action="delete")

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        with _SESSION_CACHE_LOCK:
            _SESSION_CACHE.clear()
        if target_user:
            try:
                from backend.services.samba_engine import get_samba_engine

                get_samba_engine().sync_samba_user(username=target_user["username"], delete=True)
            except Exception:
                ignored("backend.users_db.delete_user")
    _evict_user_caches(user_id)
    return True


def disable_admin_user(admin_identifier: str = "admin", db_path: str | None = None) -> dict[str, Any]:
    """
    Safely disables the default admin account:
    1. Verifies another active SuperAdmin exists (fails fast if invariant violated).
    2. Sets status = 'disabled'.
    3. Revokes all active sessions for admin in SQLite, memory cache, and auth.py SESSIONS.
    4. Logs structured security audit event.
    """
    with users_db_session(db_path) as conn:
        admin = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE OR id = ?",
            (admin_identifier, admin_identifier),
        ).fetchone()
        if not admin:
            raise ValueError(f"Admin account '{admin_identifier}' not found.")

        admin_id = admin["id"]
        assert_remaining_superadmin_guard(conn, admin_id, action="disable")

        now = time.time()
        conn.execute("UPDATE users SET status = 'disabled', updated_at = ? WHERE id = ?", (now, admin_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (admin_id,))

    _evict_user_caches(admin_id)

    log_security_event(
        "admin.account.disabled",
        "success",
        actor_id=admin_id,
        actor_username=admin["username"],
        details={"guardrail_validated": True, "action": "disable_default_admin"},
        db_path=db_path,
    )
    return {"status": "ok", "user_id": admin_id, "username": admin["username"], "disabled": True}


def record_successful_login(user_id: str, ip: str, db_path: str | None = None) -> None:
    now = time.time()
    with users_db_session(db_path) as conn:
        conn.execute(
            """
            UPDATE users SET last_login_at = ?, last_login_ip = ? WHERE id = ?
        """,
            (now, ip, user_id),
        )


# ==============================================================================
# 3. Session Management (Hybrid Opaque Token / Cookie)
# ==============================================================================


def create_user_session(
    user_id: str,
    username: str,
    ip: str = "",
    user_agent: str = "",
    is_remembered: bool = False,
    db_path: str | None = None,
) -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    now = time.time()
    ttl = 30 * 86400 if is_remembered else config.SESSION_TTL
    expires_at = now + ttl

    with users_db_session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id_hash, user_id, username, created_at, expires_at,
                last_active_at, ip_address, user_agent, is_remembered
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (token_hash, user_id, username, now, expires_at, now, ip, user_agent, 1 if is_remembered else 0),
        )

        u_row = conn.execute(
            """
            SELECT u.role_id, u.must_change_password, r.scopes_json
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.id = ?
        """,
            (user_id,),
        ).fetchone()

        role_id = u_row["role_id"] if u_row else "share_user"
        scopes = json.loads(u_row["scopes_json"]) if u_row and u_row["scopes_json"] else []
        must_change = bool(u_row["must_change_password"]) if u_row else False

    # Cache in memory
    session_data = {
        "user_id": user_id,
        "username": username,
        "role_id": role_id,
        "scopes": scopes,
        "created_at": now,
        "expires_at": expires_at,
        "last_active_at": now,
        "ip_address": ip,
        "user_agent": user_agent,
        "must_change_password": must_change,
        # without it a remembered session got the short idle limit until the next restart (SEC-36)
        "is_remembered": bool(is_remembered),
    }
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE[token_hash] = session_data

    return raw_token


def _update_session_activity_sync(token_hash: str, now: float, db_path: str | None = None) -> None:
    try:
        with users_db_session(db_path) as conn:
            conn.execute("UPDATE sessions SET last_active_at = ? WHERE session_id_hash = ?", (now, token_hash))
    except Exception as e:
        logger.debug(f"Failed to update session last_active_at: {e}")


def _idle_too_long(last_active: float, remembered: bool, now: float) -> bool:
    """A session nobody used for days ends, even before it expires (SEC-12)."""
    idle = config.REMEMBERED_SESSION_IDLE_SECS if remembered else config.SESSION_IDLE_SECS
    return bool(last_active) and now - float(last_active) > idle


def _signin_hours_of(row: Any) -> dict[str, Any] | None:
    from backend.signin_hours import from_json

    try:
        return from_json(row["signin_hours_json"])
    except (IndexError, KeyError):
        return None


def forget_cached_sessions(user_id: str) -> None:
    """Drops a person's cached sessions, so the next request reads their account again."""
    with _SESSION_CACHE_LOCK:
        for k in [k for k, v in _SESSION_CACHE.items() if v.get("user_id") == user_id]:
            _SESSION_CACHE.pop(k, None)


def validate_user_session(raw_token: str, db_path: str | None = None) -> dict[str, Any] | None:
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = time.time()

    # Fast in-memory check
    with _SESSION_CACHE_LOCK:
        if token_hash in _SESSION_CACHE:
            s = _SESSION_CACHE[token_hash]
            if s["expires_at"] > now and not _idle_too_long(
                s.get("last_active_at", 0), s.get("is_remembered", False), now
            ):
                if now - s.get("last_active_at", 0) > 60:
                    s["last_active_at"] = now
                    threading.Thread(
                        target=_update_session_activity_sync,
                        args=(token_hash, now, db_path),
                        daemon=True,
                    ).start()
                return s
            else:
                del _SESSION_CACHE[token_hash]
                return None

    # SQLite lookup
    with users_db_session(db_path) as conn:
        row = conn.execute(
            """
            SELECT s.*, u.status, u.role_id, u.must_change_password, u.signin_hours_json, r.scopes_json
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            JOIN roles r ON u.role_id = r.id
            WHERE s.session_id_hash = ?
        """,
            (token_hash,),
        ).fetchone()

        if not row:
            return None

        if (
            row["status"] != "active"
            or row["expires_at"] <= now
            or _idle_too_long(row["last_active_at"], bool(row["is_remembered"]), now)
        ):
            conn.execute("DELETE FROM sessions WHERE session_id_hash = ?", (token_hash,))
            return None

        # Update last_active timestamp periodically (every 5 minutes)
        if now - row["last_active_at"] > 300:
            conn.execute("UPDATE sessions SET last_active_at = ? WHERE session_id_hash = ?", (now, token_hash))

        session_data = {
            "user_id": row["user_id"],
            "username": row["username"],
            "role_id": row["role_id"],
            "scopes": json.loads(row["scopes_json"] or "[]"),
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "last_active_at": now,
            "ip_address": row["ip_address"],
            "user_agent": row["user_agent"],
            "must_change_password": bool(row["must_change_password"]),
            "is_remembered": bool(row["is_remembered"]),
            "signin_hours": _signin_hours_of(row),
        }

        with _SESSION_CACHE_LOCK:
            _SESSION_CACHE[token_hash] = session_data

        return session_data


def revoke_user_session(raw_token: str, db_path: str | None = None) -> None:
    if not raw_token:
        return
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.pop(token_hash, None)
    with users_db_session(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE session_id_hash = ?", (token_hash,))


def revoke_session_by_hash(session_id_hash_prefix: str, user_id: str, db_path: str | None = None) -> bool:
    """Revokes a session by hash prefix and immediately purges it from in-memory cache."""
    with users_db_session(db_path) as conn:
        res = conn.execute(
            "DELETE FROM sessions WHERE session_id_hash LIKE ? AND user_id = ?",
            (f"{session_id_hash_prefix}%", user_id),
        )
        deleted = res.rowcount > 0
    with _SESSION_CACHE_LOCK:
        to_del = [
            k for k, v in _SESSION_CACHE.items() if k.startswith(session_id_hash_prefix) and v.get("user_id") == user_id
        ]
        for k in to_del:
            _SESSION_CACHE.pop(k, None)
    return deleted


def revoke_all_sessions_for_user(user_id: str, except_token: str | None = None, db_path: str | None = None) -> None:
    except_hash = hashlib.sha256(except_token.encode("utf-8")).hexdigest() if except_token else ""
    with users_db_session(db_path) as conn:
        if except_hash:
            conn.execute("DELETE FROM sessions WHERE user_id = ? AND session_id_hash != ?", (user_id, except_hash))
        else:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()


def list_user_sessions(user_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    with users_db_session(db_path, readonly=True) as conn:
        rows = conn.execute(
            """
            SELECT session_id_hash, created_at, expires_at, last_active_at, ip_address, user_agent, is_remembered
            FROM sessions
            WHERE user_id = ? AND expires_at > ?
            ORDER BY last_active_at DESC
        """,
            (user_id, time.time()),
        ).fetchall()
        return [dict(r) for r in rows]


# ==============================================================================
# 4. Scoped API Token Operations
# ==============================================================================


def create_scoped_api_token(
    user_id: str,
    name: str,
    scopes: list[str] | None = None,
    expires_in_days: int | None = None,
    db_path: str | None = None,
    folders: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    raw_token = "zat_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    masked = raw_token[:8] + "..." + raw_token[-4:]
    token_id = str(uuid.uuid4())
    now = time.time()
    expires_at = (now + (expires_in_days * 86400)) if expires_in_days else None

    # A token says what it may do; it never silently becomes "everything" (SEC-4)
    granted_scopes = [s for s in (scopes or []) if isinstance(s, str) and s.strip()]
    if not granted_scopes:
        raise ValueError("Choose what the token may do (at least one scope).")
    allowed = normalize_token_folders(folders)

    with users_db_session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO api_tokens (
                token_id, user_id, name, token_hash, masked_token, scopes_json,
                created_at, expires_at, folders_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                token_id,
                user_id,
                name.strip(),
                token_hash,
                masked,
                json.dumps(granted_scopes),
                now,
                expires_at,
                json.dumps(allowed),
            ),
        )

    token_meta = {
        "token_id": token_id,
        "name": name,
        "masked_token": masked,
        "scopes": granted_scopes,
        "folders": allowed,
        "created_at": now,
        "expires_at": expires_at,
    }
    return raw_token, token_meta


MAX_TOKEN_FOLDERS = 20


def normalize_token_folders(folders: list[str] | None) -> list[str]:
    """A token's folder allow-list (COMP-06): absolute, normalised, no duplicates or nested repeats."""
    out: list[str] = []
    for raw in folders or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        p = raw.strip().replace("\\", "/")
        if not p.startswith("/") or ".." in p.split("/"):
            raise ValueError(f"Folders are absolute paths on the NAS, such as /mnt/user/Documents ({raw!r}).")
        p = os.path.normpath(p)
        if p == "/":
            raise ValueError("Leave the folder list empty to allow every folder the account may open.")
        out.append(p)
    out = sorted(set(out))
    # /a/b is already covered by /a
    out = [p for p in out if not any(p != q and p.startswith(q + "/") for q in out)]
    if len(out) > MAX_TOKEN_FOLDERS:
        raise ValueError(f"A token can be limited to at most {MAX_TOKEN_FOLDERS} folders.")
    return out


_TOKEN_USE: dict[str, float] = {}
_TOKEN_USE_EVERY = 60.0


def note_token_use(token_id: str, ip: str = "", client: str = "", db_path: str | None = None) -> bool:
    """Records when, from where and (for MCP) by which client a token was used; at most once a
    minute per token unless the client changes. Returns whether it wrote."""
    if not token_id:
        return False
    now = time.time()
    with _TOKEN_CACHE_LOCK:
        last = _TOKEN_USE.get(token_id, 0.0)
        if not client and now - last < _TOKEN_USE_EVERY:
            return False
        _TOKEN_USE[token_id] = now
    sets, args = ["last_used_at = ?", "last_used_ip = ?"], [now, (ip or "")[:64]]
    if client:
        sets.append("last_client = ?")
        args.append(client[:120])
    try:
        with users_db_session(db_path) as conn:
            conn.execute(f"UPDATE api_tokens SET {', '.join(sets)} WHERE token_id = ?", (*args, token_id))
    except sqlite3.Error:  # recording use never blocks the request it came with
        ignored("backend.users_db.note_token_use")
        return False
    return True


def cap_token_scopes(token_scopes: list[str], role_scopes: list[str]) -> list[str]:
    """What a token may do today: its own scopes, but never more than its owner's current role (SEC-4)."""
    from backend.auth import has_scope

    if not role_scopes:
        return []
    if "*" in token_scopes:
        return list(role_scopes)
    return [s for s in token_scopes if has_scope(role_scopes, s)]


def validate_scoped_api_token(raw_token: str, db_path: str | None = None) -> dict[str, Any] | None:
    if not raw_token or not raw_token.startswith("zat_"):
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = time.time()

    with _TOKEN_CACHE_LOCK:
        if token_hash in _TOKEN_CACHE:
            t = _TOKEN_CACHE[token_hash]
            if not t.get("expires_at") or t["expires_at"] > now:
                return t
            else:
                del _TOKEN_CACHE[token_hash]
                return None

    with users_db_session(db_path, readonly=True) as conn:
        row = conn.execute(
            """
            SELECT t.*, u.username, u.status, u.role_id, r.scopes_json AS role_scopes_json
            FROM api_tokens t
            JOIN users u ON t.user_id = u.id
            LEFT JOIN roles r ON u.role_id = r.id
            WHERE t.token_hash = ?
        """,
            (token_hash,),
        ).fetchone()

        if not row or row["status"] != "active":
            return None

        if row["expires_at"] and row["expires_at"] <= now:
            return None

        token_data = {
            "token_id": row["token_id"],
            "user_id": row["user_id"],
            "username": row["username"],
            "role_id": row["role_id"],
            "scopes": cap_token_scopes(
                json.loads(row["scopes_json"] or "[]"), json.loads(row["role_scopes_json"] or "[]")
            ),
            "name": row["name"],
            "expires_at": row["expires_at"],
            "folders": _folders_of(row),
            "is_api_token": True,
        }

        with _TOKEN_CACHE_LOCK:
            _TOKEN_CACHE[token_hash] = token_data

        return token_data


def _folders_of(row: Any) -> list[str]:
    try:
        value = json.loads(row["folders_json"] or "[]")
    except (IndexError, KeyError, ValueError, TypeError):
        return []
    return [p for p in value if isinstance(p, str)] if isinstance(value, list) else []


def list_user_api_tokens(user_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    with users_db_session(db_path, readonly=True) as conn:
        rows = conn.execute(
            """
            SELECT token_id, name, masked_token, scopes_json, created_at, expires_at, last_used_at, last_used_ip,
                   folders_json, last_client
            FROM api_tokens
            WHERE user_id = ?
            ORDER BY created_at DESC
        """,
            (user_id,),
        ).fetchall()

        res = []
        for r in rows:
            d = dict(r)
            d["scopes"] = json.loads(d.pop("scopes_json", "[]"))
            d["folders"] = _folders_of(r)
            d.pop("folders_json", None)
            res.append(d)
        return res


def revoke_api_token(token_id: str, user_id: str | None = None, db_path: str | None = None) -> bool:
    with users_db_session(db_path) as conn:
        if token_id.startswith("zat_"):
            token_hash = hashlib.sha256(token_id.encode("utf-8")).hexdigest()
            if user_id:
                res = conn.execute("DELETE FROM api_tokens WHERE token_hash = ? AND user_id = ?", (token_hash, user_id))
            else:
                res = conn.execute("DELETE FROM api_tokens WHERE token_hash = ?", (token_hash,))
        else:
            if user_id:
                res = conn.execute("DELETE FROM api_tokens WHERE token_id = ? AND user_id = ?", (token_id, user_id))
            else:
                res = conn.execute("DELETE FROM api_tokens WHERE token_id = ?", (token_id,))
        with _TOKEN_CACHE_LOCK:
            _TOKEN_CACHE.clear()
        return res.rowcount > 0


revoke_scoped_api_token = revoke_api_token


# ==============================================================================
# 5. Security Audit Logging
# ==============================================================================


_AUDIT_PRUNED = {"at": 0.0}


def _prune_security_log(conn: sqlite3.Connection, now: float) -> None:
    """Drops events older than AUDIT_RETENTION_DAYS, at most once an hour (SEC-32)."""
    days = int(getattr(config, "AUDIT_RETENTION_DAYS", 365) or 0)
    if days <= 0 or now - _AUDIT_PRUNED["at"] < 3600:
        return
    conn.execute("DELETE FROM security_audit_log WHERE timestamp < ?", (now - days * 86400,))
    _AUDIT_PRUNED["at"] = now


def pseudonymise_security_log(user_id: str, db_path: str | None = None) -> int:
    """Replaces a person's name, id, address and browser in the security log with a pseudonym
    (SEC-32): the events stay, so the log still adds up, but no longer say who."""
    if not user_id:
        return 0
    alias = "erased-" + hashlib.sha256(str(user_id).encode()).hexdigest()[:10]
    with users_db_session(db_path) as conn:
        cur = conn.execute(
            "UPDATE security_audit_log SET actor_id = ?, actor_username = ?, actor_ip = '', actor_user_agent = '' "
            "WHERE actor_id = ?",
            (alias, alias, user_id),
        )
        return max(0, cur.rowcount or 0)


def log_security_event(
    event_type: str,
    status: str,
    actor_id: str | None = None,
    actor_username: str | None = None,
    actor_ip: str | None = None,
    actor_user_agent: str | None = None,
    details: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> None:
    now = time.time()
    try:
        with users_db_session(db_path) as conn:
            conn.execute(
                """
                INSERT INTO security_audit_log (
                    event_type, actor_id, actor_username, actor_ip, actor_user_agent, status, details_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    event_type,
                    actor_id,
                    actor_username,
                    actor_ip or "",
                    actor_user_agent or "",
                    status,
                    json.dumps(details or {}),
                    now,
                ),
            )
            _prune_security_log(conn, now)
        try:
            from backend.services.security_alerts import maybe_alert

            maybe_alert(event_type, status, actor_username, actor_ip, details)
        except Exception:
            ignored("backend.users_db.log_security_event")
    except Exception as e:
        logger.error(f"Failed to record security audit event: {e}")


def query_security_audit_logs(limit: int = 100, offset: int = 0, db_path: str | None = None) -> list[dict[str, Any]]:
    with users_db_session(db_path, readonly=True) as conn:
        rows = conn.execute(
            """
            SELECT * FROM security_audit_log
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """,
            (limit, offset),
        ).fetchall()
        res = []
        for r in rows:
            d = dict(r)
            d["details"] = json.loads(d.pop("details_json", "{}"))
            res.append(d)
        return res


# ==============================================================================
# 6. Multi-Factor Authentication (MFA / 2FA) Operations
# ==============================================================================


def get_user_mfa(user_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    with users_db_session(db_path, readonly=True) as conn:
        row = conn.execute(
            "SELECT id, username, mfa_enabled, mfa_secret, mfa_recovery_codes_json FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        rec_codes = json.loads(row["mfa_recovery_codes_json"] or "[]")
        from backend.secret_box import SecretBoxError, unseal

        try:
            mfa_secret = unseal(row["mfa_secret"] or "")
        except SecretBoxError as e:
            logger.error(f"[Users] Two-factor secret for '{row['username']}' is unreadable: {e}")
            mfa_secret = ""
        return {
            "user_id": row["id"],
            "username": row["username"],
            "mfa_enabled": bool(row["mfa_enabled"]),
            "mfa_secret": mfa_secret,
            "recovery_codes_count": len(rec_codes),
        }


def _seal_secret(secret: str) -> str:
    from backend.secret_box import seal

    return seal(secret)


def enable_user_mfa(
    user_id: str,
    secret: str,
    recovery_code_hashes: list[str],
    db_path: str | None = None,
) -> bool:
    with users_db_session(db_path) as conn:
        res = conn.execute(
            """
            UPDATE users
            SET mfa_enabled = 1, mfa_secret = ?, mfa_recovery_codes_json = ?, updated_at = ?
            WHERE id = ?
        """,
            (_seal_secret(secret.strip()), json.dumps(recovery_code_hashes), time.time(), user_id),
        )
        return res.rowcount > 0


def disable_user_mfa(user_id: str, db_path: str | None = None) -> bool:
    with users_db_session(db_path) as conn:
        res = conn.execute(
            """
            UPDATE users
            SET mfa_enabled = 0, mfa_secret = '', mfa_recovery_codes_json = '[]', updated_at = ?
            WHERE id = ?
        """,
            (time.time(), user_id),
        )
        return res.rowcount > 0


def consume_user_recovery_code(
    user_id: str,
    candidate_code: str,
    db_path: str | None = None,
) -> bool:
    from backend.totp import verify_and_consume_recovery_code

    with users_db_session(db_path) as conn:
        row = conn.execute(
            "SELECT mfa_recovery_codes_json FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        stored_hashes = json.loads(row["mfa_recovery_codes_json"] or "[]")
        ok, updated = verify_and_consume_recovery_code(stored_hashes, candidate_code)
        if ok:
            conn.execute(
                "UPDATE users SET mfa_recovery_codes_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(updated), time.time(), user_id),
            )
            return True
        return False


# ---------------------------------------------------------------------------
# Roles and invite links (Batch 6)
# ---------------------------------------------------------------------------
def get_role(role_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    with users_db_session(db_path, readonly=True) as conn:
        row = conn.execute("SELECT id, name, description, scopes_json FROM roles WHERE id = ?", (role_id,)).fetchone()
    return dict(row) if row else None


def _invite_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_invite(
    role_id: str, days: int, max_uses: int, note: str, created_by: str, quota_bytes: int = 0, db_path: str | None = None
) -> tuple[str, dict[str, Any]]:
    import secrets as _secrets

    token = _secrets.token_urlsafe(24)
    now = time.time()
    inv = {
        "id": str(uuid.uuid4())[:8],
        "role_id": role_id,
        "quota_bytes": int(quota_bytes or 0),
        "note": note[:120],
        "max_uses": max(1, int(max_uses)),
        "uses": 0,
        "created_by": created_by,
        "created_at": now,
        "expires_at": now + max(1, int(days)) * 86400,
    }
    with users_db_session(db_path) as conn:
        conn.execute(
            "INSERT INTO invites (id, token_hash, role_id, quota_bytes, note, max_uses, uses, created_by, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                inv["id"],
                _invite_hash(token),
                role_id,
                inv["quota_bytes"],
                inv["note"],
                inv["max_uses"],
                created_by,
                now,
                inv["expires_at"],
            ),
        )
    return token, inv


def list_invites(db_path: str | None = None) -> list[dict[str, Any]]:
    with users_db_session(db_path, readonly=True) as conn:
        rows = conn.execute(
            "SELECT id, role_id, quota_bytes, note, max_uses, uses, created_by, created_at, expires_at FROM invites ORDER BY created_at DESC"
        ).fetchall()
    now = time.time()
    return [dict(r) | {"active": r["uses"] < r["max_uses"] and r["expires_at"] > now} for r in rows]


def lookup_invite(token: str, db_path: str | None = None) -> dict[str, Any] | None:
    """The invite for a token while it can still be used, else None."""
    if not token or len(token) > 100:
        return None
    with users_db_session(db_path, readonly=True) as conn:
        row = conn.execute("SELECT * FROM invites WHERE token_hash = ?", (_invite_hash(token),)).fetchone()
    if not row or row["uses"] >= row["max_uses"] or row["expires_at"] <= time.time():
        return None
    return dict(row)


def accept_invite(
    token: str, username: str, display_name: str, password: str, db_path: str | None = None
) -> dict[str, Any]:
    """Creates the account an invite allows and counts the use. LookupError when the invite is
    gone; ValueError for a taken or invalid username."""
    inv = lookup_invite(token, db_path)
    if not inv:
        raise LookupError("invite")
    if get_user_by_username(username, db_path=db_path):
        raise ValueError("That username is taken.")
    with users_db_session(db_path) as conn:
        cur = conn.execute(
            "UPDATE invites SET uses = uses + 1 WHERE id = ? AND uses < max_uses AND expires_at > ?",
            (inv["id"], time.time()),
        )
        if cur.rowcount != 1:
            raise LookupError("invite")
    user = create_user(
        username=username,
        display_name=display_name,
        password=password,
        role_id=inv["role_id"],
        storage_quota_bytes=int(inv.get("quota_bytes") or 0),
        db_path=db_path,
    )
    log_security_event(
        "user.created_by_invite",
        "success",
        actor_username=username,
        details={"invite": inv["id"], "role": inv["role_id"]},
        db_path=db_path,
    )
    return user


def delete_invite(invite_id: str, db_path: str | None = None) -> bool:
    with users_db_session(db_path) as conn:
        return conn.execute("DELETE FROM invites WHERE id = ?", (invite_id,)).rowcount == 1


def retire_weak_hashes(db_path: str | None = None) -> int:
    """Accounts still on an unsalted SHA-256 hash get it wrapped in Argon2id and are asked to
    choose a new password at their next sign-in (ARC-9). Directory accounts are left alone.
    Returns how many accounts changed."""
    from backend.passwords import is_unsalted_sha256, wrap_unsalted_sha256

    changed = 0
    with users_db_session(db_path) as conn:
        rows = conn.execute("SELECT id, username, password_hash, idp_type FROM users").fetchall()
        for row in rows:
            if (row["idp_type"] or "local") != "local" or not is_unsalted_sha256(row["password_hash"] or ""):
                continue
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 1, updated_at = ? WHERE id = ?",
                (wrap_unsalted_sha256(row["password_hash"]), time.time(), row["id"]),
            )
            changed += 1
    if changed:
        logger.warning(
            f"[Auth] {changed} account(s) still had an unsalted SHA-256 password hash; it is now wrapped in "
            "Argon2id and they will be asked to choose a new password at their next sign-in."
        )
    return changed
