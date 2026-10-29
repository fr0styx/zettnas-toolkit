import asyncio
import json
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import ENABLE_FB, LCD_FPS, logger
from backend.db import query_history
from backend.fast_json import dumps as fast_dumps
from backend.hardware.screen import (
    find_fb_device,
    get_effective_brightness,
    get_screen_state,
)
from backend.services.broadcaster import broadcaster
from backend.services.stats_collector import collect
from backend.state import Z_STATE

router = APIRouter(tags=["Telemetry & Stats"])


@router.get("/lcd_status", dependencies=[Depends(require_scope("hardware:read", "system:view"))])
def get_lcd_status():
    fb_path = find_fb_device(writable_only=False)
    scr = get_screen_state()
    eff_bri = get_effective_brightness()
    return {
        "enabled": ENABLE_FB,
        "fb_present": bool(fb_path),
        "fb_path": fb_path,
        "fps": LCD_FPS,
        "active": Z_STATE.lcd_renderer_active,
        "renderer": Z_STATE.lcd_renderer_name or None,
        "power": bool(scr.get("power", True)),
        "screen_off": eff_bri <= 0,
    }


# SEC-33: people without the system view (kids and guests) see the desktop, not the machine:
# its name, status, storage use, uptime and their own layout and look. No addresses, disks,
# containers, events, the copy in progress or whether the default password is still set.
_FAMILY_KEYS = ("name", "status", "uptime", "layout", "client_preferences")
_FAMILY_STORAGE = ("used", "total", "pct")
_FAMILY_SYSTEM = ("uptime_str", "uptime_sec", "hostname")


def sees_full_stats(principal: AuthenticatedPrincipal) -> bool:
    return principal.is_system or principal.has_any_scope("system:view", "hardware:read")


def family_view(data: dict[str, Any]) -> dict[str, Any]:
    """The part of a stats payload (full or delta) a kid or guest may see."""
    out: dict[str, Any] = {k: data[k] for k in _FAMILY_KEYS if k in data}
    if isinstance(data.get("storage"), dict):
        out["storage"] = {k: data["storage"][k] for k in _FAMILY_STORAGE if k in data["storage"]}
    if isinstance(data.get("system"), dict):
        out["system"] = {k: data["system"][k] for k in _FAMILY_SYSTEM if k in data["system"]}
    if isinstance(data.get("remotes_event"), dict):
        # Only the signal that mounts changed, so the file manager refreshes
        out["remotes_event"] = {"timestamp": data["remotes_event"].get("timestamp")}
    return out


_last_family: tuple[str, str | None] = ("", None)


def family_payload(payload: str) -> str | None:
    """One SSE frame cut down to the family view; None when nothing in it is theirs."""
    global _last_family
    if not payload.startswith("data: "):
        return payload
    if _last_family[0] == payload:
        return _last_family[1]
    try:
        data = json.loads(payload[6:])
    except ValueError:
        return None
    view = family_view(data) if isinstance(data, dict) else {}
    out = f"data: {fast_dumps(view)}\n\n" if view else None
    _last_family = (payload, out)
    return out


@router.get("/stats")
def get_stats(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    data = collect()
    return data if sees_full_stats(principal) else family_view(data)


MAX_SSE_SUBSCRIBERS = 32


@router.get("/stats/stream")
async def stats_stream(request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    if broadcaster.get_subscriber_count() >= MAX_SSE_SUBSCRIBERS:
        raise HTTPException(
            status_code=429,
            detail="Maximum concurrent SSE telemetry connections reached. Try again later.",
        )

    try:
        loop = asyncio.get_running_loop()
        broadcaster.set_loop(loop)
    except RuntimeError:
        pass

    initial = Z_STATE.cached_stats
    if not initial:
        initial = await asyncio.to_thread(collect)
    full = sees_full_stats(principal)
    q = await broadcaster.subscribe(initial)
    from backend.auth import extract_token, is_internal_token
    from backend.hardware import docker_stats

    # The front LCD is always connected; only people looking count as viewers (PERF-6)
    is_viewer = not is_internal_token(extract_token(request))
    if is_viewer:
        docker_stats.viewer_joined()

    async def event_generator():
        try:
            # End the stream on server shutdown so uvicorn can exit cleanly.
            while not Z_STATE.shutting_down:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=10.0)
                    if payload is None:
                        break
                    if not full:
                        payload = family_payload(payload)
                        if payload is None:
                            continue
                    yield payload
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if is_viewer:
                docker_stats.viewer_left()
            await broadcaster.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history", dependencies=[Depends(require_scope("hardware:read", "system:view"))])
def get_history(range: str = "24h"):
    try:
        data = query_history(range)
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[HISTORY] Query failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to load history") from e
