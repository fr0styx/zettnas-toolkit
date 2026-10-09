"""
Enterprise Identity, Multi-User, and RBAC Persistence Layer.

Provides high-performance SQLite-backed storage operating in Write-Ahead Logging (WAL)
mode for users, roles, sessions, scoped API tokens, and security audit logs.
Includes transparent zero-downtime migration from legacy security.json, sessions.json,
and api_tokens.json files.
"""

from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from backend import config
from backend.config import DATA_DIR, logger
from backend.passwords import hash_password, needs_rehash, verify_password

USERS_DB_PATH = getattr(config, "USERS_DB_PATH", os.path.join(DATA_DIR, "users.db"))
_db_lock = threading.RLock()

# In-memory session cache: token_hash -> session_dict
_SESSION_CACHE: Dict[str, Dict[str, Any]] = {}
_SESSION_CACHE_LOCK = threading.RLock()

# In-memory API token cache: token_hash -> token_dict
_TOKEN_CACHE: Dict[str, Dict[str, Any]] = {}
_TOKEN_CACHE_LOCK = threading.RLock()


def get_users_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    target_path = db_path or USERS_DB_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    conn = sqlite3.connect(target_path, timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn


@contextmanager
def users_db_session(db_path: Optional[str] = None):
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
        "scopes": ["storage:*", "shares:*", "system:view", "hardware:read", "logs:read", "audit:read"],
        "is_system": 1,
    },
    {
        "id": "app_operator",
        "name": "AppOperator",
        "description": "Deploy, inspect, restart, and edit Docker containers and apps",
        "scopes": ["containers:*", "system:view", "logs:read"],
        "is_system": 1,
    },
    {
        "id": "backup_operator",
        "name": "BackupOperator",
        "description": "Trigger, view, and schedule configuration and data backups",
        "scopes": ["backup:*", "storage:read", "shares:read", "system:view", "logs:read"],
        "is_system": 1,
    },
    {
        "id": "share_user",
        "name": "ShareUser",
        "description": "Access permitted file shares, personal home directory, and media ingest",
        "scopes": ["shares:read", "shares:user_write", "system:view"],
        "is_system": 1,
    },
    {
        "id": "auditor",
        "name": "Auditor",
        "description": "Read-only access to system telemetry, metrics, event logs, and status",
        "scopes": ["*:read", "system:view"],
        "is_system": 1,
    },
]


def init_users_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite tables for users, roles, sessions, API tokens, and audit logs."""
    target_path = db_path or USERS_DB_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    with users_db_session(target_path) as conn:
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
                last_login_ip TEXT DEFAULT ''
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
                last_used_ip TEXT DEFAULT ''
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


def migrate_legacy_data(db_path: Optional[str] = None) -> None:
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
                    with open(sec_file, "r") as f:
                        data = json.load(f)
                        password_hash = data.get("password_hash") or password_hash
                        admin_username = data.get("username") or admin_username
                        email = data.get("email") or email
                except Exception as e:
                    logger.warning(f"Could not read legacy {sec_file}: {e}")

            if not password_hash:
                password_hash = hash_password("admin")

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
                    1 if password_hash == hash_password("admin") else 0,
                    f"/mnt/user/homes/{admin_username}",
                    now,
                    now,
                ),
            )

            # Ingest legacy active sessions from sessions.json
            sess_file = getattr(config, "SESSIONS_FILE", os.path.join(DATA_DIR, "sessions.json"))
            if os.path.exists(sess_file):
                try:
                    with open(sess_file, "r") as f:
                        raw_sessions = json.load(f)
                    migrated_sess = 0
                    for token, sdata in raw_sessions.items():
                        if isinstance(sdata, dict) and sdata.get("expires", 0) > now:
                            thash = hashlib.sha256(token.encode("utf-8")).hexdigest()
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO sessions (
                                    session_id_hash, user_id, username, created_at, expires_at,
                                    last_active_at, ip_address, user_agent, is_remembered
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                                (
                                    thash,
                                    admin_id,
                                    sdata.get("user", admin_username),
                                    sdata.get("created", now),
                                    sdata.get("expires", now + 86400),
                                    now,
                                    "127.0.0.1",
                                    "Migrated Legacy Session",
                                    0,
                                ),
                            )
                            migrated_sess += 1
                    logger.info(f"Migrated {migrated_sess} active sessions from {sess_file}")
                    # Safely backup legacy sessions file
                    shutil.copy2(sess_file, sess_file + ".bak")
                except Exception as e:
                    logger.warning(f"Failed to migrate legacy sessions: {e}")

            # Ingest legacy API tokens from api_tokens.json
            tok_file = os.path.join(DATA_DIR, "api_tokens.json")
            if os.path.exists(tok_file):
                try:
                    with open(tok_file, "r") as f:
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


def get_user_by_id(user_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with users_db_session(db_path) as conn:
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


def get_user_by_username(username: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not username:
        return None
    with users_db_session(db_path) as conn:
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


def list_users(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with users_db_session(db_path) as conn:
        rows = conn.execute("""
            SELECT u.id, u.username, u.display_name, u.email, u.role_id, r.name AS role_name,
                   u.status, u.must_change_password, u.avatar_url, u.home_directory,
                   u.storage_quota_bytes, u.created_at, u.last_login_at, u.last_login_ip
            FROM users u
            JOIN roles r ON u.role_id = r.id
            ORDER BY u.created_at ASC
        """).fetchall()
        return [dict(r) for r in rows]


def create_user(
    username: str,
    display_name: str,
    password: str,
    email: str = "",
    role_id: str = "share_user",
    storage_quota_bytes: int = 0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    username_clean = username.strip().lower()
    if len(username_clean) < 2 or len(username_clean) > 32:
        raise ValueError("Username must be between 2 and 32 characters.")

    now = time.time()
    user_id = str(uuid.uuid4())
    pwd_hash = hash_password(password)

    with users_db_session(db_path) as conn:
        # Check role exists
        role = conn.execute("SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
        if not role:
            role_id = "share_user"

        conn.execute(
            """
            INSERT INTO users (
                id, username, display_name, email, password_hash, role_id, status,
                must_change_password, home_directory, storage_quota_bytes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                f"/mnt/user/homes/{username_clean}",
                storage_quota_bytes,
                now,
                now,
            ),
        )

    return get_user_by_id(user_id, db_path)


def update_user_password(user_id: str, new_password: str, db_path: Optional[str] = None) -> bool:
    new_hash = hash_password(new_password)
    now = time.time()
    with users_db_session(db_path) as conn:
        res = conn.execute(
            """
            UPDATE users SET password_hash = ?, updated_at = ?, must_change_password = 0 WHERE id = ?
        """,
            (new_hash, now, user_id),
        )
        # Also invalidate all active sessions for this user on password change
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    # Clear in-memory cache
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()
    return res.rowcount > 0


def update_user_profile(
    user_id: str,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    role_id: Optional[str] = None,
    status: Optional[str] = None,
    storage_quota_bytes: Optional[int] = None,
    preferences: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> bool:
    now = time.time()
    with users_db_session(db_path) as conn:
        updates = ["updated_at = ?"]
        params: List[Any] = [now]

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

        params.append(user_id)
        res = conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        return res.rowcount > 0


def delete_user(user_id: str, db_path: Optional[str] = None) -> bool:
    """Deletes a user. Prevents deleting the last superadmin."""
    with users_db_session(db_path) as conn:
        user = conn.execute("SELECT role_id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return False
        if user["role_id"] == "superadmin":
            admin_count = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE role_id = 'superadmin' AND status = 'active'"
            ).fetchone()["c"]
            if admin_count <= 1:
                raise ValueError("Cannot delete the only active SuperAdmin account.")

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True


def record_successful_login(user_id: str, ip: str, db_path: Optional[str] = None) -> None:
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
    db_path: Optional[str] = None,
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
            SELECT u.role_id, r.scopes_json
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.id = ?
        """,
            (user_id,),
        ).fetchone()

        role_id = u_row["role_id"] if u_row else "share_user"
        scopes = json.loads(u_row["scopes_json"]) if u_row and u_row["scopes_json"] else []

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
    }
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE[token_hash] = session_data

    return raw_token


def validate_user_session(raw_token: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = time.time()

    # Fast in-memory check
    with _SESSION_CACHE_LOCK:
        if token_hash in _SESSION_CACHE:
            s = _SESSION_CACHE[token_hash]
            if s["expires_at"] > now:
                return s
            else:
                del _SESSION_CACHE[token_hash]
                return None

    # SQLite lookup
    with users_db_session(db_path) as conn:
        row = conn.execute(
            """
            SELECT s.*, u.status, u.role_id, r.scopes_json
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            JOIN roles r ON u.role_id = r.id
            WHERE s.session_id_hash = ?
        """,
            (token_hash,),
        ).fetchone()

        if not row:
            return None

        if row["status"] != "active" or row["expires_at"] <= now:
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
        }

        with _SESSION_CACHE_LOCK:
            _SESSION_CACHE[token_hash] = session_data

        return session_data


def revoke_user_session(raw_token: str, db_path: Optional[str] = None) -> None:
    if not raw_token:
        return
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.pop(token_hash, None)
    with users_db_session(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE session_id_hash = ?", (token_hash,))


def revoke_all_sessions_for_user(
    user_id: str, except_token: Optional[str] = None, db_path: Optional[str] = None
) -> None:
    except_hash = hashlib.sha256(except_token.encode("utf-8")).hexdigest() if except_token else ""
    with users_db_session(db_path) as conn:
        if except_hash:
            conn.execute("DELETE FROM sessions WHERE user_id = ? AND session_id_hash != ?", (user_id, except_hash))
        else:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()


def list_user_sessions(user_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with users_db_session(db_path) as conn:
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
    scopes: Optional[List[str]] = None,
    expires_in_days: Optional[int] = None,
    db_path: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    raw_token = "zat_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    masked = raw_token[:8] + "..." + raw_token[-4:]
    token_id = str(uuid.uuid4())
    now = time.time()
    expires_at = (now + (expires_in_days * 86400)) if expires_in_days else None

    granted_scopes = scopes or ["*"]

    with users_db_session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO api_tokens (
                token_id, user_id, name, token_hash, masked_token, scopes_json,
                created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (token_id, user_id, name.strip(), token_hash, masked, json.dumps(granted_scopes), now, expires_at),
        )

    token_meta = {
        "token_id": token_id,
        "name": name,
        "masked_token": masked,
        "scopes": granted_scopes,
        "created_at": now,
        "expires_at": expires_at,
    }
    return raw_token, token_meta


def validate_scoped_api_token(raw_token: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
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

    with users_db_session(db_path) as conn:
        row = conn.execute(
            """
            SELECT t.*, u.username, u.status, u.role_id
            FROM api_tokens t
            JOIN users u ON t.user_id = u.id
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
            "scopes": json.loads(row["scopes_json"] or "[]"),
            "name": row["name"],
            "expires_at": row["expires_at"],
            "is_api_token": True,
        }

        with _TOKEN_CACHE_LOCK:
            _TOKEN_CACHE[token_hash] = token_data

        return token_data


def list_user_api_tokens(user_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with users_db_session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT token_id, name, masked_token, scopes_json, created_at, expires_at, last_used_at, last_used_ip
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
            res.append(d)
        return res


def revoke_api_token(token_id: str, user_id: Optional[str] = None, db_path: Optional[str] = None) -> bool:
    with users_db_session(db_path) as conn:
        if user_id:
            res = conn.execute("DELETE FROM api_tokens WHERE token_id = ? AND user_id = ?", (token_id, user_id))
        else:
            res = conn.execute("DELETE FROM api_tokens WHERE token_id = ?", (token_id,))
        with _TOKEN_CACHE_LOCK:
            _TOKEN_CACHE.clear()
        return res.rowcount > 0


# ==============================================================================
# 5. Security Audit Logging
# ==============================================================================


def log_security_event(
    event_type: str,
    status: str,
    actor_id: Optional[str] = None,
    actor_username: Optional[str] = None,
    actor_ip: Optional[str] = None,
    actor_user_agent: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
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
    except Exception as e:
        logger.error(f"Failed to record security audit event: {e}")


def query_security_audit_logs(limit: int = 100, offset: int = 0, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    with users_db_session(db_path) as conn:
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
