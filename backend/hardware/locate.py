"""
Kiboto - find a drive by its light.

Two methods, each for one drive: the enclosure's own bay light where the chassis has one, else the
drive's activity light, made to flicker by small reads that really reach the drive. The answer
names the method, so the page can say which light to look at (SET-09).

The chassis light bar is no longer flashed: it flashed the same for every drive, which finds none,
and was left white instead of the saved setting.
"""

import mmap
import os
import subprocess
import threading
import time
from typing import Any

from backend.config import logger
from backend.ignored_errors import ignored
from backend.proc import run_bounded

BLOCK = 4096
SPAN_BLOCKS = 16384  # the reads walk over the first 64 MB, so none is answered from a cache


def _flicker(dev_path: str, duration: float) -> int:
    """Reads small blocks straight from the drive (past the system's cache) for `duration`
    seconds and returns how many reads reached it. Through the cache, block 0 of a drive in use
    was read from memory and no light moved."""
    reads = 0
    fd = os.open(dev_path, os.O_RDONLY | getattr(os, "O_DIRECT", 0))
    try:
        buf = mmap.mmap(-1, BLOCK)  # page-aligned, as reading past the cache needs
        end = time.monotonic() + duration
        while time.monotonic() < end:
            os.preadv(fd, [buf], (reads % SPAN_BLOCKS) * BLOCK)
            reads += 1
            time.sleep(0.12)
    finally:
        os.close(fd)
    return reads


def locate_drive_multitier(
    dev_name: str, dev_path: str, duration_sec: int = 5, allow_read_strobe: bool = True
) -> dict[str, Any]:
    """Blinks a light that belongs to this one drive and says which: "bay_light" (the enclosure's,
    through ledctl) or "activity_light" (the drive's own, through reads)."""
    duration = max(1, min(int(duration_sec or 5), 15))

    if os.path.exists("/usr/sbin/ledctl"):
        try:
            res = subprocess.run(["ledctl", f"locate={dev_path}"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:

                def _turn_off_ses():
                    time.sleep(duration)
                    try:
                        run_bounded(["ledctl", f"locate_off={dev_path}"], timeout=15, capture_output=True)
                    except Exception:
                        ignored("backend.hardware.locate.locate_drive_multitier._turn_off_ses")

                threading.Thread(target=_turn_off_ses, daemon=True, name=f"ses-off-{dev_name}").start()
                return {
                    "success": True,
                    "tier": "ses",
                    "method": "bay_light",
                    "dev": dev_name,
                    "duration": duration,
                }
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug("[DiskLocate] the enclosure light did not answer: %s", e)

    # reading the drive wakes a sleeping one: only with the person's confirmation
    if not allow_read_strobe:
        return {"success": False, "needs_wake": True, "dev": dev_name}

    # the first read is made here, so a drive that cannot be read is said, not assumed to flicker
    try:
        os.close(os.open(dev_path, os.O_RDONLY))
    except OSError as e:
        return {"success": False, "dev": dev_name, "error": f"The drive could not be read: {e.strerror or e}"}

    def _read_strobe():
        try:
            _flicker(dev_path, duration)
        except OSError as e:
            logger.debug("[DiskLocate] reading %s stopped: %s", dev_name, e)

    threading.Thread(target=_read_strobe, daemon=True, name=f"locate-strobe-{dev_name}").start()
    return {
        "success": True,
        "tier": "strobe",
        "method": "activity_light",
        "dev": dev_name,
        "duration": duration,
    }
