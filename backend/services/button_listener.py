import asyncio
import json
import mmap
import os
import struct
import threading
import time

from backend.config import BUTTON_CFG_FILE, HOST_DEV, logger
from backend.services.copy_engine import _do_copy
from backend.state import Z_STATE, add_event


def button_listener_daemon():
    MMIO_BASE = 0xE0D20000
    COPY_OFFSET = 0x6C0

    try:
        fd = os.open(os.path.join(HOST_DEV, "mem"), os.O_RDWR | os.O_SYNC)
        mem = mmap.mmap(fd, 4096, offset=MMIO_BASE)
    except Exception as e:
        logger.info(f"[ZettNAS] Hardware button mapping failed: {e}")
        return

    last_state = 1
    while True:
        try:
            copy_val = struct.unpack("<I", mem[COPY_OFFSET : COPY_OFFSET + 4])[0]
            current_state = (copy_val & 2) >> 1

            if current_state == 0 and last_state == 1:
                cfg = {
                    "enabled": False,
                    "source": "sd",
                    "dest": "/mnt/user/",
                    "use_exif": True,
                    "on_collision": "skip",
                    "action": "cycle_lcd",
                }
                if os.path.exists(BUTTON_CFG_FILE):
                    try:
                        with open(BUTTON_CFG_FILE) as f:
                            cfg.update(json.load(f))
                    except (json.JSONDecodeError, OSError):
                        pass

                btn_action = cfg.get("action", "cycle_lcd")
                if cfg.get("enabled") and not Z_STATE.copy_active and btn_action == "copy":
                    Z_STATE.copy_active = True
                    Z_STATE.copy_status = "copying"
                    Z_STATE.ui_wake.set()
                    add_event("info", "Copy Started", "Starting ingest from SD Card reader...")
                    threading.Thread(target=lambda c: asyncio.run(_do_copy(c)), args=(cfg,), daemon=True).start()
                else:
                    new_page = Z_STATE.cycle_lcd_page()
                    add_event("info", "LCD Page Switched", f"Display cycled to Page {new_page} via front hardware button.")

            last_state = current_state
        except Exception as e:
            logger.debug(f"Silenced exception: {e}")
        time.sleep(0.1)
