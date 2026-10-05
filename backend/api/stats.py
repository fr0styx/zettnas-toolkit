import asyncio
import json
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.config import ENABLE_FB, LCD_FPS, logger
from backend.db import query_history
from backend.services.stats_collector import collect
from backend.state import Z_STATE

router = APIRouter(tags=["Telemetry & Stats"])


@router.get("/lcd_status")
async def get_lcd_status():
    return {
        "enabled": ENABLE_FB,
        "fb_present": os.path.exists("/dev/fb0"),
        "fps": LCD_FPS,
        "active": Z_STATE.lcd_renderer_active,
    }


@router.get("/stats")
async def get_stats():
    return collect()


@router.get("/stats/stream")
async def stats_stream(request: Request):
    async def event_generator():
        # End the stream on server shutdown so uvicorn can exit cleanly.
        while not Z_STATE.shutting_down:
            if await request.is_disconnected():
                break
            data = collect()
            payload = json.dumps(data)
            yield f"data: {payload}\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/history")
async def get_history(range: str = "24h"):
    try:
        data = query_history(range)
        return JSONResponse(data)
    except Exception as e:
        logger.error(f"[HISTORY] Query failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to load history")
