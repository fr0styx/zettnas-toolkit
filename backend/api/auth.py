import threading
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend import config
from backend.auth import (
    create_session,
    extract_token,
    invalidate_all_sessions,
    revoke_session,
)
from backend.config import SECURITY_FILE, is_using_default_password, logger
from backend.errors import error_response
from backend.fsutil import atomic_write_json
from backend.models.schemas import LoginRequest, SecurityUpdateRequest
from backend.passwords import hash_password, is_legacy_hash, verify_password

router = APIRouter(tags=["Authentication & Security"])

# ---- Brute-force protection (per client IP, exponential backoff) ----
_FREE_ATTEMPTS = 5
_MAX_LOCKOUT_SECS = 15 * 60
_failures = {}  # ip -> {"count": int, "locked_until": float}
_failures_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _lockout_remaining(ip: str) -> int:
    with _failures_lock:
        entry = _failures.get(ip)
        if not entry:
            return 0
        return max(0, int(entry["locked_until"] - time.time()))


def _register_failure(ip: str) -> None:
    with _failures_lock:
        entry = _failures.setdefault(ip, {"count": 0, "locked_until": 0.0})
        entry["count"] += 1
        over = entry["count"] - _FREE_ATTEMPTS
        if over >= 0:
            entry["locked_until"] = time.time() + min(_MAX_LOCKOUT_SECS, 2**over * 5)


def _clear_failures(ip: str) -> None:
    with _failures_lock:
        _failures.pop(ip, None)


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


@router.post("/auth/login")
async def login(req: LoginRequest, request: Request):
    ip = _client_ip(request)
    remaining = _lockout_remaining(ip)
    if remaining > 0:
        return _rate_limited(remaining)

    ok = await run_in_threadpool(verify_password, req.password, config.STORED_PASSWORD_HASH)
    if not ok:
        _register_failure(ip)
        logger.warning(f"Failed login attempt from {ip}.")
        return error_response(401, "Invalid password.", error="invalid_credentials")

    _clear_failures(ip)

    # Transparent upgrade of legacy unsalted SHA-256 hashes to scrypt.
    if is_legacy_hash(config.STORED_PASSWORD_HASH):
        try:
            config.STORED_PASSWORD_HASH = await run_in_threadpool(hash_password, req.password)
            _persist_security()
            logger.info("Upgraded stored password hash from SHA-256 to scrypt.")
        except OSError as e:
            logger.error(f"Failed to persist upgraded password hash: {e}")

    logger.info(f"Successful login to WebUI from {ip}.")
    token = create_session(config.ZETTNAS_USERNAME)
    return JSONResponse(content={"status": "ok", "token": token, "is_default_password": is_using_default_password()})


@router.post("/auth/logout")
async def logout(request: Request):
    revoke_session(extract_token(request))
    return {"status": "ok"}


@router.get("/security")
async def get_security():
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

    if data.username:
        config.ZETTNAS_USERNAME = data.username.strip()[:64]
    if data.email is not None:
        config.ZETTNAS_EMAIL = data.email.strip()[:254]

    try:
        _persist_security()
    except OSError as e:
        logger.error(f"Failed to write security.json: {e}")

    return {"status": "ok", "is_default_password": is_using_default_password()}
