import json
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import backend.config as config
from backend.auth import (
    AuthenticatedPrincipal,
    create_session,
    extract_token,
    get_current_principal,
    get_current_session,
    invalidate_all_sessions,
    require_scope,
    revoke_session,
    validate_session,
)
from backend.config import SECURITY_FILE, is_using_default_password, logger
from backend.errors import error_response
from backend.fsutil import atomic_write_json
from backend.models.schemas import (
    LoginRequest,
    SecurityUpdateRequest,
    UserCreateRequest,
    UserPasswordChangeRequest,
    UserUpdateRequest,
)
from backend.passwords import hash_password, is_legacy_hash, needs_rehash, verify_password
from backend.users_db import (
    create_user,
    delete_user,
    get_user_by_id,
    get_user_by_username,
    list_user_sessions,
    list_users,
    log_security_event,
    query_security_audit_logs,
    record_successful_login,
    revoke_all_sessions_for_user,
    revoke_user_session,
    update_user_password,
    update_user_profile,
)

router = APIRouter(tags=["Authentication & Security"])

# ---- Brute-force protection (per client IP and per username, exponential backoff) ----
_FREE_ATTEMPTS = 5
_MAX_LOCKOUT_SECS = 15 * 60
_failures: Dict[str, Dict[str, Any]] = {}  # key -> {"count": int, "locked_until": float, "last_seen": float}
_failures_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _lockout_remaining(key: str) -> int:
    with _failures_lock:
        entry = _failures.get(key)
        if not entry:
            return 0
        return max(0, int(entry["locked_until"] - time.time()))


def _register_failure(key: str) -> None:
    now = time.time()
    with _failures_lock:
        if len(_failures) > 1000:
            expired = [
                k for k, v in _failures.items() if v["locked_until"] < now and now - v.get("last_seen", 0) > 3600
            ]
            for k in expired:
                _failures.pop(k, None)

        entry = _failures.setdefault(key, {"count": 0, "locked_until": 0.0, "last_seen": now})
        entry["count"] += 1
        entry["last_seen"] = now
        over = entry["count"] - _FREE_ATTEMPTS
        if over >= 0:
            entry["locked_until"] = now + min(_MAX_LOCKOUT_SECS, 2**over * 5)


def _clear_failures(key: str) -> None:
    with _failures_lock:
        _failures.pop(key, None)


def _rate_limited(remaining: int):
    return error_response(
        429,
        f"Too many failed attempts. Try again in {remaining}s.",
        headers={"Retry-After": str(remaining)},
        retry_after=remaining,
    )


def _persist_security() -> None:
    atomic_write_json(
        SECURITY_FILE,
        {
            "password_hash": config.STORED_PASSWORD_HASH,
            "username": config.ZETTNAS_USERNAME,
            "email": config.ZETTNAS_EMAIL,
        },
    )


def _get_authenticated_user(request: Request) -> Optional[Dict[str, Any]]:
    token = extract_token(request)
    if not token or not validate_session(token):
        return None
    sess = get_current_session(token)
    if not sess:
        return None
    return get_user_by_id(sess["user_id"])


# ==============================================================================
# Authentication Endpoints
# ==============================================================================


@router.post("/auth/login")
async def login(req: LoginRequest, request: Request):
    ip = _client_ip(request)
    username = (req.username or "").strip().lower()
    target_username = username or (getattr(config, "ZETTNAS_USERNAME", "admin") or "admin").lower()

    # Rate limit check on both IP and targeted username
    remaining_ip = _lockout_remaining(ip)
    if remaining_ip > 0:
        return _rate_limited(remaining_ip)

    remaining_user = _lockout_remaining(f"user:{target_username}")
    if remaining_user > 0:
        return _rate_limited(remaining_user)

    # 1. Lookup user in SQLite
    user = get_user_by_username(target_username)

    # 2. Verify password (against user's stored hash or fallback to config.STORED_PASSWORD_HASH for admin/legacy tests)
    ok = False
    if user and user.get("password_hash"):
        ok = await run_in_threadpool(verify_password, req.password, user["password_hash"])

    if not ok and target_username in ("admin", getattr(config, "ZETTNAS_USERNAME", "admin")):
        if await run_in_threadpool(verify_password, req.password, config.STORED_PASSWORD_HASH):
            ok = True
            if not user:
                try:
                    user = create_user(
                        username=target_username,
                        password=req.password,
                        display_name=config.NAS_NAME or "Administrator",
                        role_id="superadmin",
                    )
                except Exception:
                    user = get_user_by_username(target_username)
            else:
                update_user_password(user["id"], req.password)
                user = get_user_by_id(user["id"])

    if not ok or not user:
        _register_failure(ip)
        _register_failure(f"user:{target_username}")
        log_security_event(
            "auth.login.failure",
            "failure",
            actor_username=target_username,
            actor_ip=ip,
            actor_user_agent=request.headers.get("user-agent", ""),
            details={"reason": "invalid_credentials"},
        )
        logger.warning(f"Failed login attempt for '{target_username}' from {ip}.")
        return error_response(401, "Invalid username or password.", error="invalid_credentials")

    # 3. Check user active status
    if user.get("status") != "active":
        log_security_event(
            "auth.login.blocked",
            "blocked",
            actor_id=user["id"],
            actor_username=user["username"],
            actor_ip=ip,
            details={"status": user.get("status")},
        )
        return error_response(403, "Account is disabled or locked.", error="account_disabled")

    _clear_failures(ip)
    _clear_failures(f"user:{target_username}")

    # 4. Transparent zero-downtime hash upgrade to modern Argon2id
    if (user and needs_rehash(user.get("password_hash", ""))) or needs_rehash(config.STORED_PASSWORD_HASH):
        try:
            new_hash = await run_in_threadpool(hash_password, req.password)
            if user:
                update_user_password(user["id"], req.password)
            if (user and user.get("role_id") == "superadmin") or target_username in (
                "admin",
                getattr(config, "ZETTNAS_USERNAME", "admin"),
            ):
                config.STORED_PASSWORD_HASH = new_hash
                _persist_security()
            logger.info(f"Transparently upgraded password hash for '{target_username}' to modern Argon2id.")
        except Exception as e:
            logger.warning(f"Failed to upgrade password hash for '{target_username}': {e}")

    # 5. Create session
    ua = request.headers.get("user-agent", "")
    token = create_session(user["username"], is_remembered=req.remember_me, ip=ip, user_agent=ua)
    record_successful_login(user["id"], ip)

    log_security_event(
        "auth.login.success",
        "success",
        actor_id=user["id"],
        actor_username=user["username"],
        actor_ip=ip,
        actor_user_agent=ua,
    )
    logger.info(f"Successful login for '{user['username']}' from {ip}.")

    # Build response with both token and HttpOnly session cookie
    response_data = {
        "status": "ok",
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role_id"],
            "role_name": user.get("role_name", "User"),
            "scopes": user.get("scopes", []),
            "must_change_password": bool(user.get("must_change_password")),
            "avatar_url": user.get("avatar_url", ""),
            "home_directory": user.get("home_directory", ""),
        },
        "is_default_password": is_using_default_password(),
    }
    response = JSONResponse(content=response_data)

    # Set modern SameSite=Lax HttpOnly cookie
    ttl = 30 * 86400 if req.remember_me else config.SESSION_TTL
    response.set_cookie(
        key="zettnas_session",
        value=token,
        max_age=ttl,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@router.post("/auth/logout")
def logout(request: Request):
    token = extract_token(request)
    if token:
        sess = get_current_session(token)
        if sess:
            log_security_event(
                "auth.logout",
                "success",
                actor_id=sess.get("user_id"),
                actor_username=sess.get("username"),
                actor_ip=_client_ip(request),
            )
        revoke_session(token)

    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(key="zettnas_session", path="/")
    return response


@router.get("/auth/me")
def get_current_user_profile(request: Request):
    user = _get_authenticated_user(request)
    if not user:
        # Fallback for internal LCD token or legacy session
        return {
            "id": "admin-00000000-0000-0000-0000-000000000001",
            "username": config.ZETTNAS_USERNAME or "admin",
            "display_name": "Administrator",
            "role": "superadmin",
            "role_name": "SuperAdmin",
            "scopes": ["*"],
            "email": config.ZETTNAS_EMAIL,
            "status": "active",
            "is_default_password": is_using_default_password(),
            "preferences": {},
        }
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "email": user.get("email", ""),
        "role": user["role_id"],
        "role_name": user.get("role_name", "User"),
        "scopes": user.get("scopes", []),
        "status": user.get("status", "active"),
        "must_change_password": bool(user.get("must_change_password")),
        "avatar_url": user.get("avatar_url", ""),
        "home_directory": user.get("home_directory", ""),
        "storage_quota_bytes": user.get("storage_quota_bytes", 0),
        "preferences": user.get("preferences", {}),
        "is_default_password": is_using_default_password(),
    }


# ==============================================================================
# Multi-User Management Endpoints
# ==============================================================================


@router.get("/users", dependencies=[Depends(require_scope("users:read"))])
def get_users_list(request: Request):
    users = list_users()
    return {"users": users, "total": len(users)}


@router.post("/users", dependencies=[Depends(require_scope("users:write"))])
async def create_new_user(
    data: UserCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_scope("users:write")),
):
    existing = get_user_by_username(data.username)
    if existing:
        return error_response(409, f"User '{data.username}' already exists.", error="user_exists")

    try:
        new_user = create_user(
            username=data.username,
            display_name=data.display_name or data.username,
            password=data.password,
            email=data.email or "",
            role_id=data.role_id,
            storage_quota_bytes=data.storage_quota_bytes,
        )
        log_security_event(
            "user.created",
            "success",
            actor_id=principal.user_id,
            actor_username=principal.username,
            actor_ip=_client_ip(request),
            details={"created_user": data.username, "role": data.role_id},
        )
        return {"status": "ok", "user": new_user}
    except ValueError as e:
        return error_response(400, str(e), error="invalid_request")


@router.get("/users/{user_id}")
def get_user_detail(user_id: str, request: Request):
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    target.pop("password_hash", None)
    return target


@router.put("/users/{user_id}")
def update_user_endpoint(user_id: str, data: UserUpdateRequest, request: Request):
    current = _get_authenticated_user(request)
    if current and current["id"] != user_id and current.get("role_id") not in ("superadmin", "admin"):
        return error_response(403, "Permission denied.")

    # Non-admins cannot alter their own role or status
    role_to_set = data.role_id
    status_to_set = data.status
    if current and current.get("role_id") not in ("superadmin", "admin"):
        role_to_set = None
        status_to_set = None

    ok = update_user_profile(
        user_id=user_id,
        display_name=data.display_name,
        email=data.email,
        role_id=role_to_set,
        status=status_to_set,
        storage_quota_bytes=data.storage_quota_bytes,
        preferences=data.preferences,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"status": "ok", "user": get_user_by_id(user_id)}


@router.post("/users/{user_id}/password")
async def change_user_password(user_id: str, data: UserPasswordChangeRequest, request: Request):
    current = _get_authenticated_user(request)
    if current and current["id"] != user_id and current.get("role_id") not in ("superadmin", "admin"):
        return error_response(403, "Permission denied.")

    if len(data.new_password) < config.MIN_PASSWORD_LENGTH:
        return error_response(400, f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters.")

    ok = update_user_password(user_id, data.new_password)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found.")

    target = get_user_by_id(user_id)
    if target and target.get("role_id") == "superadmin":
        config.STORED_PASSWORD_HASH = hash_password(data.new_password)
        _persist_security()

    log_security_event(
        "user.password.changed",
        "success",
        actor_id=current["id"] if current else user_id,
        actor_username=current["username"] if current else "user",
        actor_ip=_client_ip(request),
        details={"target_user_id": user_id},
    )
    return {"status": "ok", "message": "Password updated successfully."}


@router.delete("/users/{user_id}", dependencies=[Depends(require_scope("users:delete"))])
def delete_user_endpoint(
    user_id: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_scope("users:delete")),
):
    if principal.user_id == user_id:
        return error_response(400, "Cannot delete your own active account.")

    try:
        ok = delete_user(user_id)
        if not ok:
            raise HTTPException(status_code=404, detail="User not found.")
        log_security_event(
            "user.deleted",
            "success",
            actor_id=principal.user_id,
            actor_username=principal.username,
            actor_ip=_client_ip(request),
            details={"deleted_user_id": user_id},
        )
        return {"status": "ok"}
    except ValueError as e:
        return error_response(400, str(e))


# ==============================================================================
# Active Sessions & Device Management
# ==============================================================================


@router.get("/auth/sessions")
def get_my_active_sessions(request: Request):
    user = _get_authenticated_user(request)
    if not user:
        return {"sessions": []}
    current_token = extract_token(request)
    from hashlib import sha256

    current_hash = sha256(current_token.encode("utf-8")).hexdigest() if current_token else ""

    sessions = list_user_sessions(user["id"])
    for s in sessions:
        s["is_current"] = s["session_id_hash"] == current_hash
        # Mask session hash for safety
        s["id"] = s["session_id_hash"][:12]

    return {"sessions": sessions}


@router.delete("/auth/sessions/{session_id_hash}")
def revoke_specific_session(session_id_hash: str, request: Request):
    user = _get_authenticated_user(request)
    if not user:
        return error_response(401, "Not authenticated.")

    from backend.users_db import users_db_session

    with users_db_session() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE session_id_hash LIKE ? AND user_id = ?", (f"{session_id_hash}%", user["id"])
        )
    return {"status": "ok"}


@router.delete("/auth/sessions")
def revoke_all_other_sessions(request: Request):
    user = _get_authenticated_user(request)
    if not user:
        return error_response(401, "Not authenticated.")
    current_token = extract_token(request)
    revoke_all_sessions_for_user(user["id"], except_token=current_token)
    return {"status": "ok", "message": "All other sessions have been revoked."}


@router.get("/auth/audit", dependencies=[Depends(require_scope("audit:read"))])
def get_security_audit_logs(request: Request, limit: int = 50, offset: int = 0):
    logs = query_security_audit_logs(limit=min(200, limit), offset=offset)
    return {"audit_logs": logs, "count": len(logs)}


# ==============================================================================
# Legacy Security Compatibility
# ==============================================================================


@router.get("/security")
def get_security():
    return {
        "username": config.ZETTNAS_USERNAME,
        "email": config.ZETTNAS_EMAIL,
        "is_default_password": is_using_default_password(),
        "min_password_length": config.MIN_PASSWORD_LENGTH,
    }


@router.post("/security")
async def post_security(data: SecurityUpdateRequest, request: Request):
    ip = _client_ip(request)
    remaining = _lockout_remaining(ip)
    if remaining > 0:
        return _rate_limited(remaining)

    current_ok = await run_in_threadpool(verify_password, data.current_password or "", config.STORED_PASSWORD_HASH)
    if not current_ok:
        _register_failure(ip)
        return error_response(403, "Invalid current password.", error="invalid_credentials")
    _clear_failures(ip)

    new_pwd = data.new_password
    if new_pwd:
        if len(new_pwd) < config.MIN_PASSWORD_LENGTH:
            return error_response(
                400, f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters.", error="weak_password"
            )
        if new_pwd.lower() == "admin":
            return error_response(400, "Please choose a password other than the default.", error="weak_password")
        config.STORED_PASSWORD_HASH = await run_in_threadpool(hash_password, new_pwd)
        invalidate_all_sessions()

        # Also update in users.db for the admin user
        admin = get_user_by_username(config.ZETTNAS_USERNAME) or get_user_by_username("admin")
        if admin:
            update_user_password(admin["id"], new_pwd)

    if data.username:
        config.ZETTNAS_USERNAME = data.username.strip()[:64]
    if data.email is not None:
        config.ZETTNAS_EMAIL = data.email.strip()[:254]

    try:
        _persist_security()
    except OSError as e:
        logger.error(f"Failed to write security.json: {e}")

    return {"status": "ok", "is_default_password": is_using_default_password()}
