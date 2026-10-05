import json
import hashlib
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from backend.config import (
    logger, SECURITY_FILE, STORED_PASSWORD_HASH, ZETTNAS_USERNAME,
    ZETTNAS_EMAIL, is_using_default_password
)
import backend.config as config
from backend.auth import create_session, invalidate_all_sessions
from backend.models.schemas import LoginRequest, SecurityUpdateRequest

router = APIRouter(tags=["Authentication & Security"])

@router.post("/auth/login")
async def login(req: LoginRequest):
    pwd = req.password
    if hashlib.sha256(pwd.encode()).hexdigest() == config.STORED_PASSWORD_HASH:
        logger.info("Successful login to WebUI.")
        token = create_session(config.ZETTNAS_USERNAME)
        return JSONResponse(content={
            "status": "ok",
            "token": token,
            "is_default_password": is_using_default_password()
        })
    else:
        logger.warning("Failed login attempt.")
        return JSONResponse(status_code=401, content={"detail": "Invalid password"})

@router.get("/security")
async def get_security():
    return {
        "username": config.ZETTNAS_USERNAME,
        "email": config.ZETTNAS_EMAIL,
        "is_default_password": is_using_default_password()
    }

@router.post("/security")
async def post_security(data: SecurityUpdateRequest):
    current_pwd = data.current_password or ""
    if hashlib.sha256(current_pwd.encode()).hexdigest() != config.STORED_PASSWORD_HASH:
        return JSONResponse(status_code=403, content={"detail": "Invalid current password"})

    new_pwd = data.new_password
    if new_pwd:
        if len(new_pwd) < 4:
            return JSONResponse(status_code=400, content={"detail": "Password must be at least 4 characters."})
        config.STORED_PASSWORD_HASH = hashlib.sha256(new_pwd.encode()).hexdigest()
        invalidate_all_sessions()

    if data.username:
        config.ZETTNAS_USERNAME = data.username.strip()
    if data.email is not None:
        config.ZETTNAS_EMAIL = data.email.strip()

    try:
        with open(SECURITY_FILE, "w") as f:
            json.dump({
                "password_hash": config.STORED_PASSWORD_HASH,
                "username": config.ZETTNAS_USERNAME,
                "email": config.ZETTNAS_EMAIL
            }, f)
    except OSError as e:
        logger.error(f"Failed to write security.json: {e}")

    return {
        "status": "ok",
        "is_default_password": is_using_default_password()
    }
