"""The appliance's SD and TF card slots, as the hardware sees them: which reader is the card
reader, whether a card is in, its size, and the kernel's polling of the slots. The copy service
(services.copy_engine) acts on them: auto-import, eject and rescan."""

import glob
import os
import re
import subprocess
import time

from backend.config import HOST_SYS
from backend.hardware import media_events
from backend.ignored_errors import ignored
from backend.settings import test_mode

# Slots ejected by the person; shared with the copy service, which ejects and rescans them
EJECTED_SLOTS: set[str] = set()


_LAST_MEDIA_PROBE = 0.0
# a slot's last size and when it was read (time.monotonic()), for media_events (PERF-18)
_SIZES: dict[str, tuple[int, float]] = {}


def _ensure_slot_polling(block_path: str, dev: str, is_empty: bool):
    """
    Ensure the Linux kernel actively polls removable card reader slots.
    When a card is removed, the SCSI driver (drivers/scsi/sd.c) sets
    events_poll_msecs to -1. Without udisks2 on Unraid, polling remains stopped
    indefinitely, causing physical card insertions to be missed.
    """
    global _LAST_MEDIA_PROBE
    poll_file = os.path.join(block_path, "events_poll_msecs")
    try:
        if os.path.exists(poll_file):
            with open(poll_file, "r+") as f:
                val = f.read().strip()
                if val in ("-1", "0", ""):
                    f.seek(0)
                    f.write("2000\n")
                    f.truncate()
    except OSError:
        pass

    now = time.time()
    # with the kernel's events heard, its own polling finds a new card: no need to open the slot
    if is_empty and not media_events.listening() and (now - _LAST_MEDIA_PROBE) > 3.0:
        _LAST_MEDIA_PROBE = now
        for dev_prefix in ["/host/dev", "/dev"]:
            dev_path = os.path.join(dev_prefix, dev)
            if os.path.exists(dev_path):
                try:
                    fd = os.open(dev_path, os.O_RDONLY | os.O_NONBLOCK)
                    os.close(fd)
                except OSError:
                    pass
                break


def probe_media_slot_capacity(dev: str, fallback_sysfs_path: str | None = None) -> int:
    """
    Directly query the hardware media slot via SCSI READ CAPACITY (sg_readcap).
    Falls back to kernel sysfs if sg_readcap is not available.
    Avoids stale Linux kernel size cache when cards are physically ejected or inserted
    in USB multi-LUN card readers (like Genesys Logic GL3224).
    """
    for dev_prefix in ["/host/dev", "/dev"]:
        dev_path = os.path.join(dev_prefix, dev)
        if os.path.exists(dev_path):
            try:
                res = subprocess.run(
                    ["sg_readcap", dev_path],
                    capture_output=True,
                    text=True,
                    timeout=1.5,
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        if "Device size:" in line:
                            m = re.search(r"Device size:\s+(\d+)\s+bytes", line)
                            if m:
                                return int(m.group(1))
                # sg_readcap reported Device not ready / Unit not ready -> card is physically removed
                return 0
            except (subprocess.SubprocessError, OSError):
                pass

    if fallback_sysfs_path and os.path.exists(fallback_sysfs_path):
        try:
            return int(open(fallback_sysfs_path).read().strip()) * 512
        except (OSError, ValueError):
            pass
    return 0


CARD_READER_IDS = {("05e3", "0764")}  # the appliance's SD/TF reader (Genesys Logic)


_READER_CACHE: dict[str, bool] = {}


def is_card_reader(block_path: str) -> bool:
    """True when a block device sits behind the appliance's card reader (by its USB vendor and
    product ID), so other USB disks, such as Unraid's boot flash, are never probed (PERF-18)."""
    try:
        real = os.path.realpath(block_path)
    except OSError:
        return False
    if real in _READER_CACHE:
        return _READER_CACHE[real]
    found = False
    d = real
    while d and d != os.path.dirname(d):
        vid, pid = os.path.join(d, "idVendor"), os.path.join(d, "idProduct")
        if os.path.isfile(vid) and os.path.isfile(pid):
            try:
                with open(vid) as fv, open(pid) as fp:
                    found = (fv.read().strip().lower(), fp.read().strip().lower()) in CARD_READER_IDS
            except OSError:
                found = False
            break
        d = os.path.dirname(d)
    _READER_CACHE[real] = found
    return found


def _slot_size(block_path: str, dev: str) -> int:
    """The card's size in a slot, read again only after the kernel reported a change (or every
    half minute) once its events are heard (PERF-18)."""
    if not test_mode():
        media_events.start()
    size, when = _SIZES.get(dev, (0, 0.0))
    if media_events.should_probe(when):
        size = probe_media_slot_capacity(dev, fallback_sysfs_path=os.path.join(block_path, "size"))
        _SIZES[dev] = (size, time.monotonic())
    return size


def read_media_slots():
    slots = {
        "sd": {"size": 0, "dev": None, "ejected": "sd" in EJECTED_SLOTS},
        "tf": {"size": 0, "dev": None, "ejected": "tf" in EJECTED_SLOTS},
    }
    try:
        for p in glob.glob(os.path.join(HOST_SYS, "block/sd*")):
            try:
                target = os.readlink(p)
                if "usb" in target and is_card_reader(p):
                    lun_str = target.split("/")[-3]
                    dev = os.path.basename(p)
                    size = _slot_size(p, dev)
                    _ensure_slot_polling(p, dev, size == 0)
                    slot_name = "sd" if lun_str.endswith(":1") else ("tf" if lun_str.endswith(":0") else None)
                    if slot_name:
                        if size == 0:
                            EJECTED_SLOTS.discard(slot_name)
                        slots[slot_name]["size"] = size
                        slots[slot_name]["dev"] = dev
                        slots[slot_name]["ejected"] = slot_name in EJECTED_SLOTS
            except Exception:
                ignored("backend.hardware.media_slots.read_media_slots")
    except Exception:
        ignored("backend.hardware.media_slots.read_media_slots")
    return slots
