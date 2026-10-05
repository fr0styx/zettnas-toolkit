import os
import json
import asyncio
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from backend.config import ENABLE_FB, LCD_FPS
from backend.state import Z_STATE
from backend.services.stats_collector import collect
from backend.db import query_history

router = APIRouter(tags=["Telemetry & Stats"])

@router.get("/lcd_status")
async def get_lcd_status():
    return {
        "enabled": ENABLE_FB,
        "fb_present": os.path.exists("/dev/fb0"),
        "fps": LCD_FPS,
        "active": Z_STATE.lcd_renderer_active
    }

@router.get("/stats")
async def get_stats():
    return collect()

@router.get("/stats/stream")
async def stats_stream(request: Request):
    async def event_generator():
        while True:
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
        raise HTTPException(status_code=500, detail=str(e))
