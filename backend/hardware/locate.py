"""
ZettNAS Toolkit - Universal Multi-Tier Drive Locator
Tier 1: SCSI Enclosure Services (SES / ledmon)
Tier 2: Microcontroller ARGB (/dev/ttyACM0)
Tier 3: Universal Software-Triggered Rhythmic Block Read Strobe
"""

import os
import subprocess
import threading
import time
from typing import Any, Dict

from backend.config import logger
from backend.hardware.led import find_led_port, send_led_packet


def locate_drive_multitier(dev_name: str, dev_path: str, duration_sec: int = 5) -> Dict[str, Any]:
    """
    Triggers physical drive identification across 3 hardware tiers:
    - Tier 1: Hardware backplane SES fault LED via ledctl (ledmon).
    - Tier 2: Dedicated chassis ARGB LED via USB CDC serial (/dev/ttyACM0).
    - Tier 3: Universal software-triggered gentle block read strobe (4KB sector 0
              pulsed at 120ms intervals) flashing standard physical activity LEDs safely without writes.
    """
    duration = max(1, min(int(duration_sec or 5), 15))

    # Tier 1: SCSI Enclosure Services (SES) via ledctl
    if os.path.exists("/usr/sbin/ledctl"):
        try:
            res = subprocess.run(["ledctl", f"locate={dev_path}"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:

                def _turn_off_ses():
                    time.sleep(duration)
                    try:
                        subprocess.run(["ledctl", f"locate_off={dev_path}"], capture_output=True)
                    except Exception:
                        pass

                threading.Thread(target=_turn_off_ses, daemon=True, name=f"ses-off-{dev_name}").start()
                return {"success": True, "tier": "ses", "method": "ledctl", "dev": dev_name, "duration": duration}
        except Exception as e:
            logger.debug(f"[DiskLocate] Tier 1 SES failed: {e}")

    # Tier 2: Microcontroller ARGB (/dev/ttyACM0)
    led_port = find_led_port()
    if led_port:
        try:
            # Mode 6 = Rapid Strobe / Identify Pulse
            send_led_packet(6, 56, 189, 248, speed=25)

            def _reset_argb():
                time.sleep(duration)
                try:
                    send_led_packet(1, 255, 255, 255, speed=5)  # Return to static calm
                except Exception:
                    pass

            threading.Thread(target=_reset_argb, daemon=True, name=f"argb-reset-{dev_name}").start()
            return {"success": True, "tier": "argb", "method": "microcontroller", "dev": dev_name, "duration": duration}
        except Exception as e:
            logger.debug(f"[DiskLocate] Tier 2 ARGB failed: {e}")

    # Tier 3: Universal Software-Triggered Direct Read Strobe
    # Reads 4KB block 0 in a gentle 120ms rhythm. Flashes hardware activity LED safely on any standard chassis!
    def _read_strobe():
        end_time = time.time() + duration
        try:
            with open(dev_path, "rb") as fp:
                while time.time() < end_time:
                    fp.seek(0)
                    _ = fp.read(4096)
                    time.sleep(0.12)
        except Exception as e:
            logger.debug(f"[DiskLocate] Tier 3 Strobe read error: {e}")

    threading.Thread(target=_read_strobe, daemon=True, name=f"locate-strobe-{dev_name}").start()
    return {
        "success": True,
        "tier": "strobe",
        "method": "direct_read_activity",
        "dev": dev_name,
        "duration": duration,
    }
