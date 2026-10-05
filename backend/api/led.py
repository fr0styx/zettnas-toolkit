import os
import json
from fastapi import APIRouter
from backend.config import LED_STATE_FILE
from backend.models.schemas import LedConfigRequest
from backend.hardware.led import apply_led_state

router = APIRouter(tags=["ARGB Lighting"])

@router.get("/led")
async def get_led():
    cur_led = {}
    if os.path.exists(LED_STATE_FILE):
        try:
            with open(LED_STATE_FILE, "r") as f:
                cur_led = json.load(f)
        except (json.JSONDecodeError, OSError): pass
    return cur_led

@router.post("/led")
async def post_led(req: LedConfigRequest):
    data = req.model_dump(exclude_unset=True)
    cur_led = {}
    if os.path.exists(LED_STATE_FILE):
        try:
            with open(LED_STATE_FILE, "r") as f:
                cur_led = json.load(f)
        except (json.JSONDecodeError, OSError): pass
    cur_led.update(data)
    ok, msg = apply_led_state(cur_led)
    with open(LED_STATE_FILE, "w") as f:
        json.dump(cur_led, f)
    return {"status": "ok" if ok else "error", "message": msg, **cur_led}
