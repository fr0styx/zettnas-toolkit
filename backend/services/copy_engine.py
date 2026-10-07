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
_AUTO_INGEST_LOCK = threading.Lock()


def reset_media_slot_state() -> None:
    """Reset edge-detection tracking for media slots (useful for testing)."""
    global _PREV_MEDIA_SLOTS
    _PREV_MEDIA_SLOTS = {"sd": {"size": 0, "dev": None}, "tf": {"size": 0, "dev": None}}


def check_media_slot_transitions(slots: dict) -> list[dict]:
    """
    Detects edge transitions (insertion / removal) for SD and TF media slots.
    Dispatches notifications, logs events, and triggers auto-ingest if enabled.
    """
    global _PREV_MEDIA_SLOTS
    transitions = []

    for slot in ("sd", "tf"):
        prev = _PREV_MEDIA_SLOTS.get(slot, {"size": 0, "dev": None})
        curr = slots.get(slot, {"size": 0, "dev": None})
        prev_sz = prev.get("size", 0)
        curr_sz = curr.get("size", 0)
        curr_dev = curr.get("dev")
        slot_label = "SD Card" if slot == "sd" else "TF Card (MicroSD)"

        # Insertion transition: 0 -> >0
        if prev_sz == 0 and curr_sz > 0:
            mb = curr_sz // (1024 * 1024)
            logger.info(f"[MEDIA] {slot_label} inserted on /dev/{curr_dev} ({mb} MB)")
            transitions.append({"event": "inserted", "slot": slot, "dev": curr_dev, "size": curr_sz})
            add_event(
                "info",
                f"{slot_label} Inserted",
                f"Detected media on /dev/{curr_dev} ({mb} MB). Ready for import.",
            )
            send_notification({
                "type": "media",
                "title": f"{slot_label} Detected",
                "message": f"{mb} MB card detected on /dev/{curr_dev}. Ready for import.",
                "level": "info",
            })
            _maybe_trigger_auto_ingest(slot)

        # Removal transition: >0 -> 0
        elif prev_sz > 0 and curr_sz == 0:
            logger.info(f"[MEDIA] {slot_label} removed")
            transitions.append({"event": "removed", "slot": slot})
            add_event(
                "info",
                f"{slot_label} Removed",
                f"{slot_label} was unmounted and removed from slot.",
            )

        _PREV_MEDIA_SLOTS[slot] = {"size": curr_sz, "dev": curr_dev}

    return transitions


def _maybe_trigger_auto_ingest(slot: str):
    from backend.config import BUTTON_CFG_FILE
    from backend.fsutil import read_json

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

        Z_STATE.copy_active = True
        Z_STATE.copy_status = "copying"
        Z_STATE.ui_wake.set()
        add_event("info", "Auto-Ingest Started", f"Automatically importing media from {slot.upper()} card...")
        send_notification({
            "type": "media",
            "title": "Auto-Ingest Started",
            "message": f"Automatically importing photos from {slot.upper()} card to {job_cfg['dest']}",
            "level": "info",
        })
        threading.Thread(target=lambda c: asyncio.run(_do_copy(c)), args=(job_cfg,), daemon=True).start()


def read_media_slots():
    slots = {"sd": {"size": 0, "dev": None}, "tf": {"size": 0, "dev": None}}
    try:
        for p in glob.glob(os.path.join(HOST_SYS, "block/sd*")):
            try:
                target = os.readlink(p)
                if "usb" in target:
                    lun_str = target.split("/")[-3]
                    if lun_str.endswith(":1"):
                        dev = os.path.basename(p)
                        size = int(open(os.path.join(p, "size")).read().strip()) * 512
                        slots["sd"]["size"] = size
                        slots["sd"]["dev"] = dev
                    elif lun_str.endswith(":0"):
                        dev = os.path.basename(p)
                        size = int(open(os.path.join(p, "size")).read().strip()) * 512
                        slots["tf"]["size"] = size
                        slots["tf"]["dev"] = dev
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

        Z_STATE.copy_active = False
        Z_STATE.ui_wake.set()
        time.sleep(8)
        if not getattr(Z_STATE, "copy_active", False):
            Z_STATE.copy_status = "idle"
            Z_STATE.ui_wake.set()
