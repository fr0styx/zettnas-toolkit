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
    import platform

    if platform.machine().lower() not in ("x86_64", "amd64"):
        logger.debug("[button_listener] Non-x86_64 architecture detected; skipping MMIO hardware button mapping.")
        return

    from backend.hardware.fans import is_zettlab_appliance

    if not is_zettlab_appliance():
        logger.debug("[button_listener] Non-appliance hardware detected; skipping hardware button mapping.")
        return

    try:
        from backend.hardware.storage import detect_chassis_model

        model = detect_chassis_model(allow_fallback=False)
        if model in ("d4", "generic", "diy"):
            logger.debug(f"[button_listener] Chassis {model} does not use MMIO button mapping.")
            return
    except Exception:
        logger.debug("backend.services.button_listener.button_listener_daemon: ignored error", exc_info=True)

    MMIO_BASE = 0xE0D20000
    COPY_OFFSET = 0x6C0

    try:
        mem_cands = [
            "/dev/mem",
            os.path.join(HOST_DEV, "mem"),
            "/host/dev/mem",
        ]
        fd = None
        last_err = None
        for p in mem_cands:
            if os.path.exists(p):
                try:
                    fd = os.open(p, os.O_RDWR | os.O_SYNC)
                    break
                except Exception as err:
                    last_err = err
                    continue
        if fd is None:
            if last_err:
                raise last_err
            fd = os.open(os.path.join(HOST_DEV, "mem"), os.O_RDWR | os.O_SYNC)
        mem = mmap.mmap(fd, 4096, offset=MMIO_BASE)
        logger.info(f"[ZettNAS] Successfully initialized MMIO hardware copy button listener on chassis {model}")
    except PermissionError as pe:
        logger.warning(
            f"[ZettNAS] Hardware button mapping failed: {pe}. "
            "Docker container lacks cgroup access to /dev/mem. "
            "Add --device-cgroup-rule='c 1:1 rwm' to container Extra Parameters in Unraid."
        )
        return
    except Exception as e:
        logger.info(f"[ZettNAS] Hardware button mapping failed: {e}")
        return

    last_state = 1
    while True:
        try:
            copy_val = struct.unpack("<I", mem[COPY_OFFSET : COPY_OFFSET + 4])[0]
            current_state = (copy_val & 2) >> 1

            if current_state == 0 and last_state == 1:
                # Hardware button mechanical debounce delay
                time.sleep(0.05)
                copy_val_check = struct.unpack("<I", mem[COPY_OFFSET : COPY_OFFSET + 4])[0]
                if (copy_val_check & 2) >> 1 != 0:
                    last_state = 1
                    continue

                cfg = {
                    "enabled": False,
                    "source": "sd",
                    "dest": "/mnt/user/",
                    "use_exif": True,
                    "verify_checksum": True,
                    "on_collision": "skip",
                    "action": "copy",
                }
                if os.path.exists(BUTTON_CFG_FILE):
                    try:
                        with open(BUTTON_CFG_FILE) as f:
                            saved = json.load(f)
                            if isinstance(saved, dict):
                                cfg.update(saved)
                    except (json.JSONDecodeError, OSError) as read_err:
                        logger.warning(f"[ButtonListener] Could not read {BUTTON_CFG_FILE}: {read_err}")

                is_enabled = bool(cfg.get("enabled", False))
                # Action defaults to "copy" if enabled, or "cycle_lcd" if disabled
                btn_action = cfg.get("action")
                if not btn_action:
                    btn_action = "copy" if is_enabled else "cycle_lcd"

                logger.info(
                    f"[ButtonListener] Physical front button pressed: enabled={is_enabled}, "
                    f"action={btn_action}, copy_active={Z_STATE.copy_active}"
                )

                if is_enabled and not Z_STATE.copy_active and btn_action == "copy":
                    from backend.services.copy_engine import read_media_slots

                    slots = read_media_slots()
                    src_slot = str(cfg.get("source", "sd")).lower().strip()
                    slot_info = slots.get(src_slot, {})
                    card_size = slot_info.get("size", 0)

                    if card_size > 0:
                        Z_STATE.pending_ingest = None
                        Z_STATE.copy_active = True
                        Z_STATE.copy_status = "copying"
                        Z_STATE.ui_wake.set()
                        slot_label = "SD Card" if src_slot == "sd" else "TF Card (MicroSD)"
                        target_dir = cfg.get("dest", "/mnt/user/")
                        add_event(
                            "info",
                            "Copy Started",
                            f"Physical COPY button pressed. Starting ingest from {slot_label} to {target_dir}...",
                        )
                        logger.info(f"[ButtonListener] Dispatched copy ingest thread for {slot_label} -> {target_dir}")
                        threading.Thread(
                            target=lambda c: asyncio.run(_do_copy(c)),
                            args=(dict(cfg),),
                            daemon=True,
                            name="CopyWorker",
                        ).start()
                    else:
                        add_event(
                            "warning",
                            "No Media Detected",
                            f"Front-panel COPY button pressed, but no media card is detected in {src_slot.upper()} slot.",
                        )
                        new_page = Z_STATE.cycle_lcd_page()
                        add_event(
                            "info",
                            "LCD Page Switched",
                            f"Display cycled to Page {new_page} via front hardware button.",
                        )
                else:
                    new_page = Z_STATE.cycle_lcd_page()
                    add_event(
                        "info", "LCD Page Switched", f"Display cycled to Page {new_page} via front hardware button."
                    )

                # Debounce to prevent multi-triggering while holding button down
                time.sleep(0.3)
        except Exception as e:
            logger.debug(f"Silenced exception: {e}")
        time.sleep(0.1)
