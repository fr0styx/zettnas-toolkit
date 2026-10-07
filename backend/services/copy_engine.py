import asyncio
import datetime
import glob
import os
import shutil
import subprocess
import threading
import time

import aiofiles
import exifread
import hashlib
import re

from backend.config import ALLOWED_BROWSE_ROOTS, HOST_DEV, HOST_PROC, HOST_SYS, logger
from backend.db import log_copy_event
from backend.fsutil import resolve_within
from backend.hardware.led import send_led_packet
from backend.services.notifications import send_notification
from backend.state import Z_STATE, add_event

_PREV_MEDIA_SLOTS = {"sd": {"size": 0, "dev": None}, "tf": {"size": 0, "dev": None}}
_EJECTED_SLOTS: set[str] = set()
_AUTO_INGEST_LOCK = threading.Lock()


def reset_media_slot_state() -> None:
    """Reset edge-detection tracking for media slots (useful for testing)."""
    global _PREV_MEDIA_SLOTS, _EJECTED_SLOTS
    _PREV_MEDIA_SLOTS = {"sd": {"size": 0, "dev": None}, "tf": {"size": 0, "dev": None}}
    _EJECTED_SLOTS.clear()


def check_media_slot_transitions(slots: dict) -> list[dict]:
    """
    Detects edge transitions (insertion / removal) for SD and TF media slots.
    Dispatches notifications, logs events, and triggers auto-ingest if enabled.
    """
    global _PREV_MEDIA_SLOTS, _EJECTED_SLOTS
    transitions = []

    for slot in ("sd", "tf"):
        prev = _PREV_MEDIA_SLOTS.get(slot, {"size": 0, "dev": None})
        curr = slots.get(slot, {"size": 0, "dev": None})
        prev_sz = prev.get("size", 0)
        curr_sz = curr.get("size", 0)
        curr_dev = curr.get("dev")
        slot_label = "SD Card" if slot == "sd" else "TF Card (MicroSD)"

        # Physical removal transition: card was present, now size is 0
        if curr_sz == 0:
            if slot in _EJECTED_SLOTS:
                logger.info(f"[MEDIA] Ejected {slot_label} was physically removed from slot.")
                _EJECTED_SLOTS.discard(slot)

            if prev_sz > 0:
                logger.info(f"[MEDIA] {slot_label} removed")
                transitions.append({"event": "removed", "slot": slot})
                add_event(
                    "info",
                    f"{slot_label} Removed",
                    f"{slot_label} was unmounted and removed from slot.",
                )
                if getattr(Z_STATE, "pending_ingest", None) and Z_STATE.pending_ingest.get("slot") == slot:
                    logger.info(f"[AUTO-INGEST] Clearing pending ingest for removed card {slot}")
                    Z_STATE.pending_ingest = None
                    Z_STATE.ui_wake.set()

            _PREV_MEDIA_SLOTS[slot] = {"size": 0, "dev": None}

        # Insertion transition: 0 -> >0
        elif prev_sz == 0 and curr_sz > 0:
            _PREV_MEDIA_SLOTS[slot] = {"size": curr_sz, "dev": curr_dev}

            if slot in _EJECTED_SLOTS:
                logger.info(
                    f"[MEDIA] {slot_label} present on /dev/{curr_dev}, but slot is marked ejected - ignoring insertion."
                )
                continue

            mb = curr_sz // (1024 * 1024)
            logger.info(f"[MEDIA] {slot_label} inserted on /dev/{curr_dev} ({mb} MB)")
            transitions.append({"event": "inserted", "slot": slot, "dev": curr_dev, "size": curr_sz})
            add_event(
                "info",
                f"{slot_label} Inserted",
                f"Detected media on /dev/{curr_dev} ({mb} MB). Ready for import.",
            )
            send_notification(
                {
                    "type": "media",
                    "title": f"{slot_label} Detected",
                    "message": f"{mb} MB card detected on /dev/{curr_dev}. Ready for import.",
                    "level": "info",
                }
            )
            _maybe_trigger_auto_ingest(slot, dev=curr_dev, size=curr_sz)

        else:
            # Steady state: card remains inserted (curr_sz > 0 and prev_sz > 0)
            _PREV_MEDIA_SLOTS[slot] = {"size": curr_sz, "dev": curr_dev}
            if slot in _EJECTED_SLOTS:
                if getattr(Z_STATE, "pending_ingest", None) and Z_STATE.pending_ingest.get("slot") == slot:
                    logger.info(f"[AUTO-INGEST] Clearing pending ingest for ejected card in {slot}")
                    Z_STATE.pending_ingest = None
                    Z_STATE.ui_wake.set()

    return transitions


def _maybe_trigger_auto_ingest(slot: str, dev: str | None = None, size: int | None = None):
    from backend.config import BUTTON_CFG_FILE
    from backend.fsutil import read_json

    if slot in _EJECTED_SLOTS:
        logger.info(f"[AUTO-INGEST] Card slot {slot} is in ejected state, skipping auto-ingest")
        return

    cfg = read_json(BUTTON_CFG_FILE, {})
    auto_enabled = (
        cfg.get("auto_ingest", False)
        or cfg.get("enabled", False)
        or (os.getenv("AUTO_INGEST_ENABLED", "0").lower() in ("1", "true", "yes"))
    )

    if not auto_enabled:
        return

    with _AUTO_INGEST_LOCK:
        if getattr(Z_STATE, "copy_active", False):
            logger.info(f"[AUTO-INGEST] Copy operation already active, skipping auto-trigger for {slot}")
            return

        configured_src = cfg.get("source", "auto")
        if configured_src not in ("auto", slot):
            logger.info(f"[AUTO-INGEST] Card slot {slot} does not match configured source {configured_src}, skipping")
            return

        job_cfg = {
            "source": slot,
            "dest": cfg.get("dest", "/mnt/user/"),
            "use_exif": cfg.get("use_exif", True),
            "verify_checksum": cfg.get("verify_checksum", True),
            "on_collision": cfg.get("on_collision", "skip"),
        }

        # Check if user confirmation prompt is required before starting copy (default: True)
        require_confirm = cfg.get("require_confirmation", True)
        if require_confirm:
            slot_info = _PREV_MEDIA_SLOTS.get(slot, {})
            slot_label = "SD Card" if slot == "sd" else "TF Card (MicroSD)"
            dev_name = dev or slot_info.get("dev") or slot
            card_size = size if size is not None else slot_info.get("size", 0)
            logger.info(f"[AUTO-INGEST] {slot_label} detected - offering media ingest confirmation prompt")
            Z_STATE.pending_ingest = {
                "slot": slot,
                "dest": job_cfg["dest"],
                "use_exif": job_cfg["use_exif"],
                "size": card_size,
                "dev": dev_name,
                "ts": time.time(),
            }
            Z_STATE.ui_wake.set()
            add_event(
                "info",
                "Media Ingest Offered",
                f"{slot_label} detected on /dev/{dev_name}. Awaiting user confirmation to start import.",
            )
            return

        # Direct auto-ingest without confirmation prompt (if user opted out in settings)
        Z_STATE.copy_active = True
        Z_STATE.copy_status = "copying"
        Z_STATE.ui_wake.set()
        add_event("info", "Auto-Ingest Started", f"Automatically importing media from {slot.upper()} card...")
        send_notification(
            {
                "type": "media",
                "title": "Auto-Ingest Started",
                "message": f"Automatically importing photos from {slot.upper()} card to {job_cfg['dest']}",
                "level": "info",
            }
        )
        threading.Thread(target=lambda c: asyncio.run(_do_copy(c)), args=(job_cfg,), daemon=True).start()


_LAST_MEDIA_PROBE = 0.0


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
    if is_empty and (now - _LAST_MEDIA_PROBE) > 3.0:
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


def rescan_media_slots(force_usb_reset: bool = True):
    """
    Force-rescan all media slots:
    1. Clears any ejected slot suppression so all cards present will be freshly recognized.
    2. If force_usb_reset is True, resets the card reader USB device if desynchronized.
    3. Rescans SCSI devices.
    4. Re-reads slots and triggers auto-ingest if a card is present.
    """
    global _EJECTED_SLOTS
    _EJECTED_SLOTS.clear()

    if force_usb_reset:
        try:
            if not os.path.exists("/dev/bus/usb") and os.path.exists("/host/dev/bus/usb"):
                os.makedirs("/dev/bus", exist_ok=True)
                try:
                    os.symlink("/host/dev/bus/usb", "/dev/bus/usb")
                except OSError:
                    pass
            subprocess.run(["usbreset", "05e3:0764"], capture_output=True, timeout=3.0)
            time.sleep(0.8)
        except Exception as e:
            logger.debug(f"usbreset error: {e}")

    # Rescan SCSI devices
    for scsi_dev in glob.glob(os.path.join(HOST_SYS, "class/scsi_device/*/device/rescan")):
        try:
            with open(scsi_dev, "w") as f:
                f.write("1\n")
        except OSError:
            pass

    time.sleep(0.5)
    slots = read_media_slots()
    # Reset previous slots state so any present card is seen as a fresh insertion
    _PREV_MEDIA_SLOTS.clear()
    check_media_slot_transitions(slots)
    return slots


def eject_media_slot(slot: str = "sd"):
    """
    Safely eject the specified media slot:
    1. Flushes OS filesystem buffers via sync.
    2. Unmounts any active temporary mounts.
    3. Marks the slot as ejected so it won't prompt for auto-ingest again while remaining in slot.
    4. Clears pending_ingest.
    """
    global _EJECTED_SLOTS, _PREV_MEDIA_SLOTS
    try:
        subprocess.run(["sync"], timeout=5.0)
    except Exception:
        pass

    # Unmount if mounted under /mnt/disks or /media
    for mount_check in glob.glob(f"/mnt/disks/{slot}*") + glob.glob(f"/media/{slot}*"):
        try:
            subprocess.run(["umount", mount_check], timeout=3.0)
        except Exception:
            pass

    _EJECTED_SLOTS.add(slot)

    if getattr(Z_STATE, "pending_ingest", None) and Z_STATE.pending_ingest.get("slot") == slot:
        Z_STATE.pending_ingest = None
        Z_STATE.ui_wake.set()

    # Retain current probed size in _PREV_MEDIA_SLOTS so subsequent poll cycles
    # don't falsely perceive a 0 -> >0 insertion edge transition while the card stays in.
    curr_slots = read_media_slots()
    curr_info = curr_slots.get(slot, {})
    curr_sz = curr_info.get("size", 0)
    curr_dev = curr_info.get("dev")
    _PREV_MEDIA_SLOTS[slot] = {"size": curr_sz, "dev": curr_dev}

    slot_label = "SD Card" if slot == "sd" else "TF Card (MicroSD)"
    add_event(
        "info",
        f"{slot_label} Ejected",
        f"{slot_label} was safely unmounted and ejected. You can now physically remove it.",
    )
    return {"status": "ok", "message": f"{slot_label} safely ejected"}


def read_media_slots():
    slots = {
        "sd": {"size": 0, "dev": None, "ejected": "sd" in _EJECTED_SLOTS},
        "tf": {"size": 0, "dev": None, "ejected": "tf" in _EJECTED_SLOTS},
    }
    try:
        for p in glob.glob(os.path.join(HOST_SYS, "block/sd*")):
            try:
                target = os.readlink(p)
                if "usb" in target:
                    lun_str = target.split("/")[-3]
                    dev = os.path.basename(p)
                    size = probe_media_slot_capacity(dev, fallback_sysfs_path=os.path.join(p, "size"))
                    _ensure_slot_polling(p, dev, size == 0)
                    slot_name = "sd" if lun_str.endswith(":1") else ("tf" if lun_str.endswith(":0") else None)
                    if slot_name:
                        if size == 0:
                            _EJECTED_SLOTS.discard(slot_name)
                        slots[slot_name]["size"] = size
                        slots[slot_name]["dev"] = dev
                        slots[slot_name]["ejected"] = slot_name in _EJECTED_SLOTS
            except Exception as e:
                logger.debug(f"Silenced exception: {e}")
    except Exception as e:
        logger.debug(f"Silenced exception: {e}")
    return slots


def _get_exif_date(filepath):
    try:
        supported_exts = (
            ".jpg",
            ".jpeg",
            ".tiff",
            ".tif",
            ".cr2",
            ".cr3",
            ".nef",
            ".arw",
            ".dng",
            ".heic",
            ".heif",
            ".rw2",
            ".orf",
            ".raf",
        )
        if filepath.lower().endswith(supported_exts):
            with open(filepath, "rb") as f:
                tags = exifread.process_file(f, stop_tag="DateTimeOriginal", details=False, strict=False)
                date_str = str(tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime") or "")
                if date_str:
                    parts = date_str.split(" ")
                    if len(parts) > 0:
                        date_part = parts[0]
                        if re.match(r"^\d{4}:\d{2}:\d{2}$", date_part):
                            y, m, d = date_part.split(":")
                            return f"{y}/{m}/{d}"
    except Exception as e:
        logger.debug(f"Silenced exception: {e}")

    try:
        mtime = os.path.getmtime(filepath)
        dt = datetime.datetime.fromtimestamp(mtime)
        return dt.strftime("%Y/%m/%d")
    except Exception:
        return None


def resolve_copy_destination(dst):
    """Canonical destination directory if it exists inside an allowed root, else None."""
    real = resolve_within(str(dst or "").strip(), ALLOWED_BROWSE_ROOTS)
    if real is None or not os.path.isdir(real):
        return None
    return real


def build_copy_plan(src_path, dst_path, use_exif, date_func=None):
    """Map every regular file under `src_path` to its destination.

    With `use_exif`, files land in ``<dst>/YYYY/MM/DD/<name>`` (EXIF capture
    date, falling back to mtime); otherwise the source tree is mirrored.
    Returns ``(entries, collisions)`` where each entry is
    ``(src_file, dst_file, size, is_collision)`` and `collisions` lists the
    destination-relative paths that already exist.
    """
    date_func = date_func or _get_exif_date
    entries, collisions = [], []
    for dirpath, _, filenames in os.walk(src_path):
        for name in sorted(filenames):
            src_file = os.path.join(dirpath, name)
            if os.path.islink(src_file):
                continue  # never follow symlinks off the card
            date_subpath = date_func(src_file) if use_exif else None
            if date_subpath:
                rel_path = os.path.join(date_subpath, os.path.basename(name))
            else:
                rel_path = os.path.relpath(src_file, src_path)
            dst_file = os.path.normpath(os.path.join(dst_path, rel_path))
            if not dst_file.startswith(dst_path):
                continue
            is_collision = os.path.exists(dst_file)
            if is_collision:
                collisions.append(rel_path)
            try:
                size = os.path.getsize(src_file)
            except OSError:
                size = 0
            entries.append((src_file, dst_file, size, is_collision))
    return entries, collisions


def select_files_to_copy(entries, skip_existing):
    """Apply the collision policy. Returns ``([(src, dst), ...], total_bytes)``."""
    files, total = [], 0
    for src_file, dst_file, size, is_collision in entries:
        if is_collision and skip_existing:
            continue
        files.append((src_file, dst_file))
        total += size
    return files, total


async def _do_copy(cfg):
    src_mode = cfg.get("source", "sd").strip()
    dst = cfg.get("dest", "/mnt/user/").strip()
    use_exif = cfg.get("use_exif", True)
    verify_checksum = cfg.get("verify_checksum", True)

    copy_start_ts = time.time()
    err_msg = ""
    Z_STATE.copy_progress = {
        "total": 0,
        "copied": 0,
        "start": copy_start_ts,
        "file": "Initializing...",
        "files_total": 0,
        "files_done": 0,
    }
    tmp_mount = False
    mounted_path = None
    try:
        target_lun = "1" if src_mode == "sd" else "0"
        found_dev = None
        for p in glob.glob(os.path.join(HOST_SYS, "block/sd*")):
            try:
                target = os.readlink(p)
                if "usb" in target:
                    if target.split("/")[-3].endswith(f":{target_lun}"):
                        dev = os.path.basename(p)
                        size = int(open(os.path.join(HOST_SYS, f"block/{dev}/size")).read().strip())
                        if size > 0:
                            found_dev = dev
                            break
            except (OSError, ValueError):
                pass

        if not found_dev:
            raise Exception(f"No media detected in {src_mode.upper()} slot.")

        part_dev = f"{found_dev}1"
        if not os.path.exists(os.path.join(HOST_DEV, part_dev)):
            part_dev = found_dev

        try:
            with open(os.path.join(HOST_PROC, "mounts")) as f:
                for line in f:
                    if f"/{part_dev}" in line or f"/{found_dev}" in line:
                        mounted_path = line.split()[1]
                        break
        except (OSError, IndexError):
            pass

        if not mounted_path:
            mounted_path = "/tmp/sd_copy_mount"
            os.makedirs(mounted_path, exist_ok=True)
            cmd = ["mount", "-r", "-o", "noatime,nodiratime", os.path.join(HOST_DEV, part_dev), mounted_path]
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode != 0:
                raise Exception(f"Failed to mount {part_dev}")
            tmp_mount = True

        src_path = mounted_path.rstrip("/") + "/"
        real_dst = resolve_copy_destination(dst)
        if real_dst is None:
            raise Exception(f"Destination {dst} is missing or outside the allowed folders.")
        dst_path = real_dst.rstrip("/") + "/"

        Z_STATE.copy_progress["file"] = "Scanning media and EXIF metadata..."
        Z_STATE.ui_wake.set()

        all_files, collisions = await asyncio.to_thread(build_copy_plan, src_path, dst_path, use_exif)

        if collisions:
            collision_rule = cfg.get("on_collision", "skip")
            if collision_rule in ["skip", "overwrite"]:
                Z_STATE.copy_overwrite_choice = collision_rule
            else:
                Z_STATE.copy_status = "awaiting_confirmation"
                Z_STATE.copy_progress["file"] = f"{len(collisions)} files already exist in destination."
                add_event(
                    "warning", "Copy Collision", f"{len(collisions)} files already exist. Waiting for confirmation."
                )
                Z_STATE.ui_wake.set()

                Z_STATE.copy_confirm_event.clear()
                Z_STATE.copy_confirm_event.wait(timeout=300.0)

                if not Z_STATE.copy_confirm_event.is_set():
                    raise Exception("Aborted: Timed out waiting for overwrite confirmation.")

                if Z_STATE.copy_overwrite_choice == "cancel":
                    raise Exception("Aborted by user.")

        skip_existing = bool(collisions) and Z_STATE.copy_overwrite_choice == "skip"
        files_to_copy, total_size = select_files_to_copy(all_files, skip_existing)

        Z_STATE.copy_progress["total"] = total_size
        Z_STATE.copy_progress["files_total"] = len(files_to_copy)
        Z_STATE.copy_progress["files_done"] = 0
        Z_STATE.copy_abort_flag = False
        Z_STATE.copy_progress["start"] = time.time()
        Z_STATE.copy_status = "copying"
        Z_STATE.ui_wake.set()

        for src_f, dst_f in files_to_copy:
            if Z_STATE.copy_abort_flag:
                break
            os.makedirs(os.path.dirname(dst_f), exist_ok=True)
            Z_STATE.copy_progress["file"] = os.path.basename(src_f)
            length = 1024 * 1024 * 4
            hasher_src = hashlib.sha256()
            hasher_dst = hashlib.sha256()
            try:
                async with aiofiles.open(src_f, "rb") as fsrc, aiofiles.open(dst_f, "wb") as fdst:
                    while True:
                        if Z_STATE.copy_abort_flag:
                            break
                        while getattr(Z_STATE, "copy_paused", False):
                            if Z_STATE.copy_status != "paused":
                                Z_STATE.copy_status = "paused"
                                Z_STATE.ui_wake.set()
                            await asyncio.sleep(0.5)

                        if Z_STATE.copy_status != "copying" and not Z_STATE.copy_abort_flag:
                            Z_STATE.copy_status = "copying"
                            Z_STATE.ui_wake.set()

                        buf = await fsrc.read(length)
                        if not buf:
                            break
                        if verify_checksum:
                            hasher_src.update(buf)
                        await fdst.write(buf)
                        Z_STATE.copy_progress["copied"] += len(buf)
                    await fdst.flush()

                if Z_STATE.copy_abort_flag:
                    if os.path.exists(dst_f):
                        os.remove(dst_f)
                    break

                # Genuine post-write destination verification
                if verify_checksum:
                    hasher_dst = hashlib.sha256()
                    async with aiofiles.open(dst_f, "rb") as fdst_check:
                        while True:
                            cbuf = await fdst_check.read(length)
                            if not cbuf:
                                break
                            hasher_dst.update(cbuf)
                    if hasher_src.hexdigest() != hasher_dst.hexdigest():
                        if os.path.exists(dst_f):
                            os.remove(dst_f)
                        raise IOError(f"Checksum mismatch for {os.path.basename(src_f)}")

                shutil.copystat(src_f, dst_f)
                Z_STATE.copy_progress["files_done"] += 1
            except Exception as e:
                logger.info(f"[ZettNAS] Error copying {src_f}: {e}")
                raise

        if Z_STATE.copy_abort_flag:
            Z_STATE.copy_status = "aborted"
            Z_STATE.copy_progress["file"] = "Aborted."
            err_msg = "User aborted the copy operation."
            add_event("warning", "Copy Aborted", err_msg)
            raise Exception("Aborted by user.")
        else:
            Z_STATE.copy_status = "success"
            done_cnt = Z_STATE.copy_progress.get("files_done", 0)
            verified_note = " (SHA-256 verified)" if verify_checksum else ""
            add_event("success", "Copy Completed", f"Successfully copied {done_cnt} files{verified_note}.")
            send_notification(
                title="ZettNAS: Media Ingest Complete",
                message=f"Successfully copied {done_cnt} files to array storage.",
                level="normal",
                event_type="copy",
                dedup_key="copy_finished",
            )
            Z_STATE.copy_progress["file"] = "Finished successfully."

    except Exception as e:
        err_msg = str(e)
        logger.info(f"[ZettNAS] Copy failed: {e}")
        Z_STATE.copy_status = "error"
        Z_STATE.copy_progress["file"] = f"Error: {e}"
        add_event("error", "Copy Failed", str(e))
        send_notification(
            title="ZettNAS Alert: Media Ingest Failed",
            message=f"Media copy operation failed: {e}",
            level="warning",
            event_type="copy",
            dedup_key="copy_failed",
        )
        try:
            send_led_packet(5, 255, 0, 0, 0, 0, 0, speed=10)
        except (OSError, ValueError):
            pass
    finally:
        if tmp_mount and mounted_path:
            subprocess.run(["umount", mounted_path])
        # Record into copy history
        try:
            log_copy_event(
                ts=int(copy_start_ts),
                source=src_mode,
                dest=dst,
                files_count=Z_STATE.copy_progress.get("files_done", 0),
                total_bytes=Z_STATE.copy_progress.get("copied", 0),
                status=Z_STATE.copy_status,
                checksum_verified=bool(verify_checksum and Z_STATE.copy_status == "success"),
                duration_sec=time.time() - copy_start_ts,
                error=err_msg,
            )
        except Exception as log_e:
            logger.info(f"[ZettNAS] Failed to log copy history: {log_e}")

        Z_STATE.pending_ingest = None
        Z_STATE.copy_active = False
        Z_STATE.ui_wake.set()
        time.sleep(8)
        if not getattr(Z_STATE, "copy_active", False):
            Z_STATE.copy_status = "idle"
            Z_STATE.ui_wake.set()
