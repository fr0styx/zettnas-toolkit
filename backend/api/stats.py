import asyncio
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.config import ENABLE_FB, LCD_FPS, logger
from backend.db import query_history
from backend.hardware.screen import (
    find_fb_device,
    get_effective_brightness,
    get_screen_state,
)
from backend.services.broadcaster import broadcaster
from backend.services.stats_collector import collect
from backend.state import Z_STATE

router = APIRouter(tags=["Telemetry & Stats"])


@router.get("/lcd_status")
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
        "power": bool(scr.get("power", True)),
        "screen_off": eff_bri <= 0,
    }


@router.get("/stats")
def get_stats():
    return collect()


MAX_SSE_SUBSCRIBERS = 32


@router.get("/stats/stream")
async def stats_stream(request: Request):
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


@router.get("/history")
def get_history(range: str = "24h"):
    try:
        data = query_history(range)
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[HISTORY] Query failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to load history") from e
