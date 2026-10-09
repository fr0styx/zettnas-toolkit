"""
ZettNAS Toolkit - WebDAV API & Streaming Reverse Proxy
Provides WebDAV daemon controls and transparent HTTP proxying on /webdav.
"""

import asyncio
import logging
from typing import Any, Dict, Optional
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import backend.config as config
from backend.services.webdav_engine import get_webdav_engine

logger = logging.getLogger("ZettNAS.WebDAVApi")

router = APIRouter(tags=["WebDAV Storage"])
proxy_router = APIRouter(tags=["WebDAV Proxy"], include_in_schema=False)


class WebdavConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    port: Optional[int] = Field(None, ge=1024, le=65535)
    root_path: Optional[str] = None
    read_only: Optional[bool] = None
    username: Optional[str] = None
    password: Optional[str] = None
    auth_enabled: Optional[bool] = None


class WebdavToggleRequest(BaseModel):
    enabled: bool


@router.get("/webdav/status")
async def get_webdav_status():
    """Returns WebDAV daemon operational status, port, URLs, and quick-connect commands."""
    engine = get_webdav_engine()
    return engine.get_status()


@router.post("/webdav/toggle")
async def toggle_webdav(req: WebdavToggleRequest):
    """Enables or disables the WebDAV service."""
    engine = get_webdav_engine()
    engine.save_config({"enabled": req.enabled})
    if req.enabled:
        return await asyncio.to_thread(engine.start)
    else:
        return await asyncio.to_thread(engine.stop)


@router.post("/webdav/config")
async def update_webdav_config(req: WebdavConfigRequest):
    """Updates WebDAV configuration and restarts the daemon if running."""
    engine = get_webdav_engine()
    updates = req.model_dump(exclude_unset=True)
    engine.save_config(updates)
    if engine.is_running():
        return await asyncio.to_thread(engine.restart)
    return engine.get_status()


@router.post("/webdav/restart")
async def restart_webdav():
    """Restarts the WebDAV daemon."""
    engine = get_webdav_engine()
    return await asyncio.to_thread(engine.restart)


# Transparent Reverse Proxy for /webdav
WEBDAV_METHODS = [
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "HEAD",
    "OPTIONS",
    "PROPFIND",
    "PROPPATCH",
    "MKCOL",
    "COPY",
    "MOVE",
    "LOCK",
    "UNLOCK",
]


async def _proxy_webdav(request: Request, path: str = ""):
    engine = get_webdav_engine()
    if not engine.is_running():
        # Try auto-starting if enabled
        cfg = engine.load_config()
        if cfg.get("enabled", True):
            await asyncio.to_thread(engine.start)
        if not engine.is_running():
            raise HTTPException(
                status_code=503,
                detail="WebDAV server is currently stopped or unavailable.",
            )

    cfg = engine.load_config()
    port = int(cfg.get("port", config.WEBDAV_PORT))
    clean_path = path.lstrip("/")
    target_url = f"http://127.0.0.1:{port}/{clean_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = dict(request.headers)
    headers["host"] = f"127.0.0.1:{port}"

    # Handle Destination header rewriting for COPY / MOVE
    if "destination" in headers:
        dest = headers["destination"]
        if "/webdav/" in dest:
            dest_suffix = dest.split("/webdav/", 1)[1]
            headers["destination"] = f"http://127.0.0.1:{port}/{dest_suffix}"

    client = httpx.AsyncClient(timeout=None)
    try:
        req = client.build_request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=request.stream(),
        )
        resp = await client.send(req, stream=True)

        resp_headers = {}
        hop_by_hop = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
        for k, v in resp.headers.items():
            if k.lower() not in hop_by_hop:
                resp_headers[k] = v

        async def body_stream():
            try:
                async for chunk in resp.aiter_raw():
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(
            body_stream(),
            status_code=resp.status_code,
            headers=resp_headers,
        )
    except httpx.ConnectError:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Unable to connect to internal WebDAV daemon.")
    except Exception as e:
        await client.aclose()
        logger.error(f"[WEBDAV PROXY] Error proxying {request.method} {path}: {e}")
        raise HTTPException(status_code=500, detail=f"WebDAV proxy error: {e}")


@proxy_router.api_route("/webdav", methods=WEBDAV_METHODS)
async def webdav_proxy_root(request: Request):
    return await _proxy_webdav(request, "")


@proxy_router.api_route("/webdav/{path:path}", methods=WEBDAV_METHODS)
async def webdav_proxy_subpath(request: Request, path: str):
    return await _proxy_webdav(request, path)
