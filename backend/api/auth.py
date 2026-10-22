import base64
import hashlib
import hmac
import ipaddress
import json
import os
import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import backend.config as config
from backend.auth import (
    AuthenticatedPrincipal,
    create_session,
    extract_token,
    get_current_principal,
    get_current_session,
    has_scope,
    invalidate_all_sessions,
    require_scope,
    revoke_session,
    validate_session,
)
from backend.config import SECURITY_FILE, is_using_default_password, logger
from backend.confirmations import require_confirmation
from backend.errors import error_response
from backend.fsutil import atomic_write_json, read_json
from backend.models.schemas import (
    LoginRequest,
    MfaChallengeRequest,
    MfaDisableRequest,
    MfaEnableRequest,
    SecurityUpdateRequest,
    UserCreateRequest,
    UserPasswordChangeRequest,
    UserUpdateRequest,
)
from backend.passwords import hash_password, is_legacy_hash, needs_rehash, verify_password
from backend.totp import (
    generate_qr_svg,
    generate_recovery_codes,
    generate_totp_code,
    generate_totp_secret,
    get_otpauth_uri,
    hash_recovery_code,
    verify_totp_code,
)
from backend.users_db import (
    consume_user_recovery_code,
    create_user,
    delete_user,
    disable_user_mfa,
    enable_user_mfa,
    get_user_by_id,
    get_user_by_username,
    get_user_mfa,
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
_FREE_ATTEMPTS_USER = 5
_FREE_ATTEMPTS_IP = 30
_MAX_LOCKOUT_SECS = 15 * 60
_failures: dict[str, dict[str, Any]] = {}  # key -> {"count": int, "locked_until": float, "last_seen": float}
_failures_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    from backend.auth import client_ip

    return client_ip(request)


def _failures_file() -> str:
    return os.path.join(config.DATA_DIR, "auth_failures.json")


def _save_failures() -> None:
    """Counters survive restarts (SEC-20); caller holds _failures_lock."""
    try:
        now = time.time()
        live = {
            k: v for k, v in _failures.items() if v.get("locked_until", 0) > now or now - v.get("last_seen", 0) < 3600
        }
        atomic_write_json(_failures_file(), live)
        os.chmod(_failures_file(), 0o600)
    except OSError as e:
        logger.debug(f"[Auth] Could not persist login failure counters: {e}")


def _load_failures() -> None:
    try:
        data = read_json(_failures_file(), {}) or {}
        now = time.time()
        with _failures_lock:
            for k, v in data.items():
                if isinstance(v, dict) and (v.get("locked_until", 0) > now or now - v.get("last_seen", 0) < 3600):
                    _failures.setdefault(k, v)
    except Exception as e:
        logger.debug(f"[Auth] Could not load login failure counters: {e}")


def _lockout_remaining(key: str) -> int:
    with _failures_lock:
        entry = _failures.get(key)
        if not entry:
            return 0
        return max(0, int(entry["locked_until"] - time.time()))


def _register_failure(key: str, is_ip: bool = False) -> None:
    now = time.time()
    try:
        ipaddress.ip_address(key)
        from backend.services import ip_block

        ip_block.record_auth_failure(key, "web")  # M5
    except ValueError:
        logger.debug("auth: failure key is not an address", exc_info=False)
    threshold = _FREE_ATTEMPTS_IP if is_ip else _FREE_ATTEMPTS_USER
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
        over = entry["count"] - threshold
        if over >= 0:
            entry["locked_until"] = now + min(_MAX_LOCKOUT_SECS, 2**over * 5)
        _save_failures()
    if over == 0:
        try:
            log_security_event("auth.lockout", "warning", details={"key": key, "failures": entry["count"]})
        except Exception:
            logger.debug("backend.api.auth._register_failure: ignored error", exc_info=True)


def _clear_failures(key: str) -> None:
    with _failures_lock:
        if _failures.pop(key, None) is not None:
            _save_failures()


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


def _get_authenticated_user(request: Request) -> dict[str, Any] | None:
    sess = getattr(request.state, "session", None)
    if sess and sess.get("user_id"):
        if sess.get("is_system"):
            return {
                "id": sess["user_id"],
                "username": sess["username"],
                "display_name": "System Console",
                "role_id": "superadmin",
                "role_name": "SuperAdmin",
                "scopes": ["*"],
                "email": config.ZETTNAS_EMAIL,
                "status": "active",
            }
        return get_user_by_id(sess["user_id"])
    token = extract_token(request)
    if not token or not validate_session(token):
        return None
    sess = get_current_session(token)
    if not sess:
        return None
    if sess.get("is_system"):
        return {
            "id": sess["user_id"],
            "username": sess["username"],
            "display_name": "System Console",
            "role_id": "superadmin",
            "role_name": "SuperAdmin",
            "scopes": ["*"],
            "email": config.ZETTNAS_EMAIL,
            "status": "active",
        }
    return get_user_by_id(sess["user_id"])


def create_mfa_token(user_id: str, username: str, remember_me: bool) -> str:
    payload = {
        "uid": user_id,
        "u": username,
        "rm": remember_me,
        "exp": time.time() + 300,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    key = (
        getattr(config, "SECRET_KEY", "") or getattr(config, "STORED_PASSWORD_HASH", "") or "zettnas-mfa-default-key"
    ).encode("utf-8")
    sig = hmac.new(key, b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"mfa_{b64}.{sig}"


def verify_mfa_token(token: str) -> dict | None:
    if not token or not token.startswith("mfa_") or "." not in token:
        return None
    try:
        body = token[4:]
        b64, sig = body.split(".", 1)
        key = (
            getattr(config, "SECRET_KEY", "")
            or getattr(config, "STORED_PASSWORD_HASH", "")
            or "zettnas-mfa-default-key"
        ).encode("utf-8")
        expected_sig = hmac.new(key, b64.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        missing = len(b64) % 4
        if missing:
            b64 += "=" * (4 - missing)
        data = json.loads(base64.urlsafe_b64decode(b64.encode("ascii")).decode("utf-8"))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def _build_session_response(
    user: dict[str, Any], remember_me: bool, request: Request, method: str = "password"
) -> JSONResponse:
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")
    token = create_session(user["username"], is_remembered=remember_me, ip=ip, user_agent=ua)
    record_successful_login(user["id"], ip)

    log_security_event(
        "auth.login.success",
        "success",
        actor_id=user["id"],
        actor_username=user["username"],
        actor_ip=ip,
        actor_user_agent=ua,
        details={"method": method},
    )
    logger.info(f"Successful login for '{user['username']}' from {ip} via {method}.")

    is_def_pwd = is_using_default_password()
    must_change = bool(user.get("must_change_password")) or is_def_pwd
    response_data = {
        "status": "ok",
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role_id"],
            "role_id": user["role_id"],
            "role_name": user.get("role_name", "User"),
            "scopes": user.get("scopes", []),
            "mfa_enabled": bool(user.get("mfa_enabled")),
            "idp_type": user.get("idp_type", "local"),
            "must_change_password": must_change,
            "avatar_url": user.get("avatar_url", ""),
            "home_directory": user.get("home_directory", ""),
        },
        "must_change_password": must_change,
        "is_default_password": is_def_pwd,
    }
    response = JSONResponse(content=response_data)

    ttl = 30 * 86400 if remember_me else config.SESSION_TTL
    from backend.auth import request_is_https

    is_https = request_is_https(request)
    response.set_cookie(
        key="zettnas_session",
        value=token,
        max_age=ttl,
        httponly=True,
        samesite="lax",
        secure=is_https,
        path="/",
    )
    return response


# ==============================================================================
# Authentication Endpoints
# ==============================================================================


@router.post("/auth/login")
async def login(req: LoginRequest, request: Request):
    ip = _client_ip(request)

    # 0. Handle direct MFA token challenge completion
    if req.mfa_token:
        challenge_req = MfaChallengeRequest(
            mfa_token=req.mfa_token,
            mfa_code=req.mfa_code,
            recovery_code=req.recovery_code,
        )
        return await mfa_challenge(challenge_req, request)

    username = (req.username or "").strip().lower()
    target_username = username or (getattr(config, "ZETTNAS_USERNAME", "admin") or "admin").lower()

    # Rate limit check on both IP and targeted username
    remaining_ip = _lockout_remaining(ip)
    if remaining_ip > 0:
        return _rate_limited(remaining_ip)

    remaining_user = _lockout_remaining(f"user:{target_username}@{ip}")
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
                        display_name=getattr(config, "NAS_NAME", None) or "Administrator",
                        role_id="superadmin",
                    )
                except Exception:
                    user = get_user_by_username(target_username)
            else:
                update_user_password(user["id"], req.password)
                user = get_user_by_id(user["id"])

    if not ok or not user:
        _register_failure(ip, is_ip=True)
        _register_failure(f"user:{target_username}@{ip}", is_ip=False)
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
    _clear_failures(f"user:{target_username}@{ip}")

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

    # 5. Check Multi-Factor Authentication (MFA / 2FA)
    if bool(user.get("mfa_enabled")):
        # If user passed MFA code or recovery code directly with credentials
        if req.mfa_code or req.recovery_code:
            user_mfa = get_user_mfa(user["id"])
            mfa_ok = False
            method = "totp"
            if req.mfa_code and user_mfa and user_mfa.get("mfa_secret"):
                mfa_ok = verify_totp_code(user_mfa["mfa_secret"], req.mfa_code, user_id=user["id"])
            if not mfa_ok and req.recovery_code:
                mfa_ok = consume_user_recovery_code(user["id"], req.recovery_code)
                method = "recovery_code"

            if not mfa_ok:
                _register_failure(ip)
                _register_failure(f"user:{target_username}@{ip}")
                log_security_event(
                    "auth.mfa.failure",
                    "failure",
                    actor_id=user["id"],
                    actor_username=user["username"],
                    actor_ip=ip,
                    details={"reason": "invalid_code"},
                )
                return error_response(401, "Invalid verification code or recovery code.", error="invalid_mfa_code")

            return _build_session_response(user, req.remember_me, request, method=method)

        # Issue intermediate MFA token
        mfa_tok = create_mfa_token(user["id"], user["username"], req.remember_me)
        return JSONResponse(
            content={
                "status": "mfa_required",
                "mfa_token": mfa_tok,
                "user_id": user["id"],
                "username": user["username"],
            }
        )

    # 6. MFA not required, issue full session
    return _build_session_response(user, req.remember_me, request, method="password")


@router.post("/auth/mfa/challenge")
async def mfa_challenge(req: MfaChallengeRequest, request: Request):
    ip = _client_ip(request)
    remaining_ip = _lockout_remaining(ip)
    if remaining_ip > 0:
        return _rate_limited(remaining_ip)

    token_data = verify_mfa_token(req.mfa_token)
    if not token_data:
        return error_response(401, "Invalid or expired MFA session. Please log in again.", error="invalid_mfa_token")

    target_username = token_data.get("u", "")
    remaining_user = _lockout_remaining(f"user:{target_username}@{ip}")
    if remaining_user > 0:
        return _rate_limited(remaining_user)

    user = get_user_by_id(token_data.get("uid", ""))
    if not user or user.get("status") != "active":
        return error_response(403, "Account is disabled or locked.", error="account_disabled")

    user_mfa = get_user_mfa(user["id"])
    mfa_ok = False
    method = "totp"
    code = req.mfa_code or req.code
    if code and user_mfa and user_mfa.get("mfa_secret"):
        mfa_ok = verify_totp_code(user_mfa["mfa_secret"], code, user_id=user["id"])
    if not mfa_ok and req.recovery_code:
        mfa_ok = consume_user_recovery_code(user["id"], req.recovery_code)
        method = "recovery_code"

    if not mfa_ok:
        _register_failure(ip)
        _register_failure(f"user:{target_username}@{ip}")
        log_security_event(
            "auth.mfa.failure",
            "failure",
            actor_id=user["id"],
            actor_username=user["username"],
            actor_ip=ip,
            details={"reason": "invalid_code"},
        )
        return error_response(401, "Invalid verification code or recovery code.", error="invalid_mfa_code")

    _clear_failures(ip)
    _clear_failures(f"user:{target_username}@{ip}")
    return _build_session_response(user, token_data.get("rm", False), request, method=method)


@router.post("/auth/mfa/setup")
def setup_mfa(request: Request):
    user = _get_authenticated_user(request)
    if not user:
        return error_response(401, "Not authenticated.")

    secret = generate_totp_secret()
    recovery_codes = generate_recovery_codes()
    issuer_name = getattr(config, "NAS_NAME", "ZettNAS") or "ZettNAS"
    otpauth_uri = get_otpauth_uri(user["username"], secret, issuer=issuer_name)
    qr_svg = generate_qr_svg(otpauth_uri)

    return {
        "status": "ok",
        "secret": secret,
        "totp_secret": secret,
        "otpauth_uri": otpauth_uri,
        "qr_svg": qr_svg,
        "recovery_codes": recovery_codes,
    }


@router.post("/auth/mfa/enable")
def enable_mfa(data: MfaEnableRequest, request: Request):
    user = _get_authenticated_user(request)
    if not user:
        return error_response(401, "Not authenticated.")

    if not verify_totp_code(data.secret, data.code):
        return error_response(400, "Invalid verification code. Please check your authenticator app and try again.")

    rec_codes = data.recovery_codes or generate_recovery_codes()
    hashed_codes = [hash_recovery_code(c) for c in rec_codes]

    ok = enable_user_mfa(user["id"], data.secret, hashed_codes)
    if not ok:
        return error_response(500, "Failed to enable two-factor authentication.")

    log_security_event(
        "auth.mfa.enabled",
        "success",
        actor_id=user["id"],
        actor_username=user["username"],
        actor_ip=_client_ip(request),
    )
    return {
        "status": "ok",
        "message": "Two-factor authentication enabled successfully.",
        "recovery_codes": rec_codes,
    }


@router.post("/auth/mfa/disable")
def disable_mfa(data: MfaDisableRequest, request: Request):
    user = _get_authenticated_user(request)
    if not user:
        return error_response(401, "Not authenticated.")

    user_mfa = get_user_mfa(user["id"])
    if not user_mfa or not user_mfa.get("mfa_enabled"):
        return {"status": "ok", "message": "Two-factor authentication is already disabled."}

    valid = False
    if data.password:
        valid = verify_password(data.password, user.get("password_hash", ""))
        if not valid and user["username"] in ("admin", getattr(config, "ZETTNAS_USERNAME", "admin")):
            valid = verify_password(data.password, config.STORED_PASSWORD_HASH)
    elif data.code and user_mfa.get("mfa_secret"):
        valid = verify_totp_code(user_mfa["mfa_secret"], data.code, user_id=user["id"])

    if not valid:
        return error_response(401, "Invalid password or verification code to disable 2FA.")

    ok = disable_user_mfa(user["id"])
    if not ok:
        return error_response(500, "Failed to disable two-factor authentication.")

    log_security_event(
        "auth.mfa.disabled",
        "success",
        actor_id=user["id"],
        actor_username=user["username"],
        actor_ip=_client_ip(request),
    )
    return {"status": "ok", "message": "Two-factor authentication disabled successfully."}


@router.get("/auth/mfa/status")
def get_mfa_status(request: Request):
    user = _get_authenticated_user(request)
    if not user:
        return error_response(401, "Not authenticated.")
    user_mfa = get_user_mfa(user["id"])
    return {
        "mfa_enabled": bool(user_mfa.get("mfa_enabled")) if user_mfa else False,
        "recovery_codes_count": user_mfa.get("recovery_codes_count", 0) if user_mfa else 0,
    }


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


# Stream Tickets (Single-Use, Short-Lived SSE/WebSocket tickets to prevent token leakage in query strings)
_STREAM_TICKETS: dict[str, dict[str, Any]] = {}
_STREAM_TICKETS_LOCK = threading.RLock()


def create_stream_ticket(user_id: str, username: str, scopes: list[str], role_id: str) -> str:
    import secrets

    ticket = f"zst_{secrets.token_urlsafe(32)}"
    now = time.time()
    with _STREAM_TICKETS_LOCK:
        expired = [k for k, v in _STREAM_TICKETS.items() if v["expires_at"] < now]
        for k in expired:
            _STREAM_TICKETS.pop(k, None)

        _STREAM_TICKETS[ticket] = {
            "user_id": user_id,
            "username": username,
            "scopes": scopes,
            "role_id": role_id,
            "expires_at": now + 60,
        }
    return ticket


def validate_and_consume_stream_ticket(ticket: str) -> dict[str, Any] | None:
    if not ticket or not ticket.startswith("zst_"):
        return None
    now = time.time()
    with _STREAM_TICKETS_LOCK:
        entry = _STREAM_TICKETS.pop(ticket, None)
        if entry and entry.get("expires_at", 0) > now:
            return {
                "user_id": entry["user_id"],
                "username": entry["username"],
                "role_id": entry["role_id"],
                "scopes": entry["scopes"],
                "is_stream_ticket": True,
            }
    return None


@router.post("/auth/ticket")
def request_stream_ticket(request: Request):
    """Generate a single-use, 60-second ticket for SSE or WebSocket connections."""
    user = _get_authenticated_user(request)
    if not user:
        return error_response(401, "Not authenticated.")

    ticket = create_stream_ticket(
        user_id=user["id"],
        username=user["username"],
        scopes=user.get("scopes", []),
        role_id=user.get("role_id", "share_user"),
    )
    return {"status": "ok", "ticket": ticket, "expires_in": 60}


class ConfirmationTokenRequest(BaseModel):
    action: str
    target: str = ""


@router.post("/confirmations")
def create_confirmation_token(
    req: ConfirmationTokenRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Issues a single-use token for one destructive action (see backend/confirmations.py)."""
    from backend.confirmations import ACTIONS, TOKEN_TTL_SECS, issue

    try:
        token = issue(principal, req.action, req.target)
    except ValueError as e:
        return error_response(400, str(e), error="bad_action")
    summary = ACTIONS[req.action].format(target=req.target or "").strip()
    return {"token": token, "expires_in": TOKEN_TTL_SECS, "summary": summary}


@router.get("/auth/me")
def get_current_user_profile(request: Request):
    user = _get_authenticated_user(request)
    is_def_pwd = is_using_default_password()
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
            "mfa_enabled": False,
            "idp_type": "local",
            "must_change_password": is_def_pwd,
            "is_default_password": is_def_pwd,
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
        "mfa_enabled": bool(user.get("mfa_enabled")),
        "idp_type": user.get("idp_type", "local"),
        "must_change_password": bool(user.get("must_change_password")) or is_def_pwd,
        "avatar_url": user.get("avatar_url", ""),
        "home_directory": user.get("home_directory", ""),
        "storage_quota_bytes": user.get("storage_quota_bytes", 0),
        "preferences": user.get("preferences", {}),
        "is_default_password": is_def_pwd,
    }


@router.get("/auth/users-list")
def list_public_users():
    """User tiles for the login screen, only when the admin turned them on (SEC-19).

    Off by default: anyone who can reach the login page could otherwise list every
    account name. Even when on, roles and 2FA status are not disclosed.
    """
    if not getattr(config, "LOGIN_USER_CHOOSER", False):
        return []
    try:
        users = list_users()
        return [
            {
                "username": u["username"],
                "display_name": u.get("display_name") or u["username"],
                "avatar_url": u.get("avatar_url") or "",
            }
            for u in users
            if u.get("status") == "active"
        ]
    except Exception as e:
        logger.warning(f"Could not list public users for chooser: {e}")
        return [
            {
                "username": "admin",
                "display_name": "Administrator",
                "role_id": "superadmin",
                "avatar_url": "",
                "has_mfa": False,
            }
        ]


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
    principal: AuthenticatedPrincipal = Depends(require_scope("users:write")),  # noqa: B008
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


def _sanitize_user_dict(u: dict[str, Any] | None) -> dict[str, Any] | None:
    if not u:
        return None
    res = dict(u)
    res.pop("password_hash", None)
    res.pop("mfa_secret", None)
    res.pop("mfa_recovery_codes_json", None)
    res.pop("token_hash", None)
    return res


@router.get("/users/{user_id}")
def get_user_detail(user_id: str, request: Request):
    current = _get_authenticated_user(request)
    if not current:
        return error_response(401, "Authentication required.", error="unauthorized")
    if current["id"] != user_id and current.get("role_id") not in ("superadmin", "admin"):
        return error_response(403, "Permission denied.", error="forbidden")
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    return _sanitize_user_dict(target)


@router.put("/users/{user_id}")
def update_user_endpoint(user_id: str, data: UserUpdateRequest, request: Request):
    current = _get_authenticated_user(request)
    if not current:
        return error_response(401, "Authentication required.", error="unauthorized")
    if current["id"] != user_id and current.get("role_id") not in ("superadmin", "admin"):
        return error_response(403, "Permission denied.", error="forbidden")

    # Non-admins cannot alter their own role, status, or storage quota
    role_to_set = data.role_id
    status_to_set = data.status
    quota_to_set = data.storage_quota_bytes
    if current.get("role_id") not in ("superadmin", "admin"):
        role_to_set = None
        status_to_set = None
        quota_to_set = None

    before = get_user_by_id(user_id) or {}
    ok = update_user_profile(
        user_id=user_id,
        display_name=data.display_name,
        email=data.email,
        role_id=role_to_set,
        status=status_to_set,
        storage_quota_bytes=quota_to_set,
        preferences=data.preferences,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="User not found.")
    if role_to_set and role_to_set != before.get("role_id"):
        log_security_event(
            "user.role.changed",
            "success",
            actor_id=current["id"],
            actor_username=current["username"],
            actor_ip=_client_ip(request),
            details={"username": before.get("username"), "role": before.get("role_id"), "new_role": role_to_set},
        )
    if status_to_set and status_to_set != before.get("status"):
        log_security_event(
            "user.status.changed",
            "success",
            actor_id=current["id"],
            actor_username=current["username"],
            actor_ip=_client_ip(request),
            details={"username": before.get("username"), "status": status_to_set},
        )
    return {"status": "ok", "user": _sanitize_user_dict(get_user_by_id(user_id))}


@router.post("/users/{user_id}/password")
async def change_user_password(user_id: str, data: UserPasswordChangeRequest, request: Request):
    sess_role = (getattr(request.state, "session", None) or {}).get("role_id")
    if sess_role == "auditor":
        return error_response(403, "Auditors are read-only and cannot change passwords.")
    current = _get_authenticated_user(request)
    if not current:
        return error_response(401, "Authentication required.")
    if current.get("role_id") == "auditor":
        return error_response(403, "Auditors are read-only and cannot change passwords.")
    is_self = current["id"] == user_id
    if not is_self:
        # Resetting someone else's password is an admin action.
        sess = getattr(request.state, "session", None) or {}
        scopes = sess.get("scopes") or current.get("scopes") or []
        if current.get("role_id") not in ("superadmin", "admin") or not any(
            has_scope(scopes, s) for s in ("users:write", "users:manage")
        ):
            return error_response(403, "Permission denied.")

    if len(data.new_password) < config.MIN_PASSWORD_LENGTH:
        return error_response(400, f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters.")
    if data.new_password.lower() == "admin":
        return error_response(400, "Please choose a password other than the default.", error="weak_password")

    if is_self:
        # Re-authenticate: a stolen session alone must not be able to take over the account (SEC-13).
        lock_key = f"pwchange:{user_id}"
        wait = _lockout_remaining(lock_key)
        if wait > 0:
            return _rate_limited(wait)
        target_user = get_user_by_id(user_id)
        stored = (target_user or {}).get("password_hash", "")
        if not data.current_password or not await run_in_threadpool(verify_password, data.current_password, stored):
            _register_failure(lock_key, is_ip=False)
            return error_response(403, "Current password is incorrect.", error="invalid_credentials")
        _clear_failures(lock_key)

    # Ends every other session of the target user; keeps the caller's own when changing their own.
    ok = update_user_password(
        user_id, data.new_password, keep_token=getattr(request.state, "token", None) if is_self else None
    )
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


@router.delete(
    "/users/{user_id}",
    dependencies=[Depends(require_scope("users:delete")), Depends(require_confirmation("users.delete"))],
)
def delete_user_endpoint(
    user_id: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_scope("users:delete")),  # noqa: B008
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


@router.post("/users/admin/disable", dependencies=[Depends(require_scope("users:manage", "users:write"))])
def disable_default_admin_endpoint(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """
    1-click action to disable the default admin account.
    Enforces the inviolable last-active-superadmin guardrail.
    """
    if principal.role_id != "superadmin":
        raise HTTPException(status_code=403, detail="Only an active SuperAdmin can disable the default admin account.")

    from backend.users_db import disable_admin_user

    try:
        res = disable_admin_user("admin")
        is_self = principal.username.lower() == "admin"
        return {
            "status": "ok",
            "message": "Default admin account has been disabled.",
            "is_self": is_self,
            "result": res,
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/security/advisor", dependencies=[Depends(require_scope("system:view", "users:read"))])
def get_security_advisor_checklist():
    """
    Runs automated zero-wake security checks across identity, passwords, and sessions.
    """
    from backend.config import is_using_default_password
    from backend.users_db import list_users

    users = list_users()
    admin_user = next((u for u in users if u["username"].lower() == "admin"), None)
    active_superadmins = [u for u in users if u.get("role_id") == "superadmin" and u.get("status") == "active"]

    admin_is_disabled = bool(admin_user and admin_user.get("status") != "active")
    admin_disabled_check = {
        "id": "sec_default_admin",
        "title": "Default 'admin' Account Status",
        "status": "pass" if admin_is_disabled else "warn",
        "severity": "high",
        "message": (
            "Default 'admin' account is disabled."
            if admin_is_disabled
            else "Default 'admin' account is still active. Recommendation: Disable it once an alternative SuperAdmin is created."
        ),
        "can_disable": len(active_superadmins) >= (2 if not admin_is_disabled else 1),
        "action_type": "disable_admin",
    }

    default_pwd = is_using_default_password()
    password_check = {
        "id": "sec_default_password",
        "title": "Master / Default Password",
        "status": "fail" if default_pwd else "pass",
        "severity": "critical",
        "message": (
            "System is currently using default credentials!"
            if default_pwd
            else "Custom secure password has been configured."
        ),
    }

    mfa_admins = [u for u in active_superadmins if u.get("mfa_enabled")]
    mfa_check = {
        "id": "sec_superadmin_mfa",
        "title": "SuperAdmin Multi-Factor Authentication",
        "status": "pass" if len(mfa_admins) == len(active_superadmins) else "warn",
        "severity": "medium",
        "message": f"{len(mfa_admins)} of {len(active_superadmins)} active SuperAdmin(s) have TOTP 2FA enabled.",
    }

    redundancy_check = {
        "id": "sec_superadmin_redundancy",
        "title": "SuperAdmin Redundancy",
        "status": "pass" if len(active_superadmins) >= 2 else "info",
        "severity": "low",
        "message": f"{len(active_superadmins)} active SuperAdmin account(s) configured.",
    }

    checks = [password_check, admin_disabled_check, mfa_check, redundancy_check]
    score = 100
    if default_pwd:
        score -= 40
    if not admin_is_disabled:
        score -= 20
    if len(mfa_admins) < len(active_superadmins):
        score -= 15

    return {
        "score": max(10, score),
        "verdict": "critical" if default_pwd else ("warning" if not admin_is_disabled else "healthy"),
        "active_superadmins_count": len(active_superadmins),
        "admin_is_disabled": admin_is_disabled,
        "checks": checks,
    }


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

    from backend.users_db import revoke_session_by_hash

    revoke_session_by_hash(session_id_hash, user["id"])
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


@router.get(
    "/security",
    dependencies=[Depends(require_scope("system:view", "users:read", "system:config"))],
)
def get_security():
    return {
        "username": config.ZETTNAS_USERNAME,
        "email": config.ZETTNAS_EMAIL,
        "is_default_password": is_using_default_password(),
        "min_password_length": config.MIN_PASSWORD_LENGTH,
    }


@router.post(
    "/security",
    dependencies=[Depends(require_scope("users:manage", "system:config"))],
)
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


_load_failures()
