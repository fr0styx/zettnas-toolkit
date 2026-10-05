import os
import glob
import time
import datetime
import asyncio
import aiofiles
import shutil
import subprocess
import exifread
from backend.config import logger, HOST_SYS, HOST_DEV, HOST_PROC
from backend.state import Z_STATE, add_event
from backend.hardware.led import send_led_packet

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
        if filepath.lower().endswith(('.jpg', '.jpeg', '.tiff', '.tif', '.cr2', '.nef', '.arw', '.dng')):
            with open(filepath, 'rb') as f:
                tags = exifread.process_file(f, details=False)
                date_str = str(tags.get('EXIF DateTimeOriginal', ''))
                if not date_str:
                    date_str = str(tags.get('Image DateTime', ''))
                if date_str:
                    parts = date_str.split(' ')
                    if len(parts) > 0:
                        y, m, d = parts[0].split(':')
                        return f"{y}/{m}/{d}"
    except Exception as e:
        logger.debug(f"Silenced exception: {e}")
        
    try:
        mtime = os.path.getmtime(filepath)
        dt = datetime.datetime.fromtimestamp(mtime)
        return dt.strftime("%Y/%m/%d")
    except Exception:
        return None

async def _do_copy(cfg):
    src_mode = cfg.get("source", "sd").strip()
    dst = cfg.get("dest", "/mnt/user/").strip()
    use_exif = cfg.get("use_exif", True)
    
    Z_STATE.copy_progress = {"total": 0, "copied": 0, "start": time.time(), "file": "Initializing...", "files_total": 0, "files_done": 0}
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
            except (OSError, ValueError): pass
            
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
        except (OSError, IndexError): pass
        
        if not mounted_path:
            mounted_path = "/tmp/sd_copy_mount"
            os.makedirs(mounted_path, exist_ok=True)
            cmd = ["mount", "-r", "-o", "noatime,nodiratime", os.path.join(HOST_DEV, part_dev), mounted_path]
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode != 0:
                raise Exception(f"Failed to mount {part_dev}")
            tmp_mount = True

        src_path = mounted_path.rstrip("/") + "/"
        dst_path = dst.rstrip("/") + "/"
        
        if not os.path.exists(dst_path):
            raise Exception(f"Destination path {dst_path} does not exist.")

        Z_STATE.copy_progress["file"] = "Scanning media and EXIF metadata..."
        Z_STATE.ui_wake.set()
        
        collisions = []
        all_files = []
        for dirpath, _, filenames in os.walk(src_path):
            for f in filenames:
                src_file = os.path.join(dirpath, f)
                rel_path = os.path.relpath(src_file, src_path)
                
                date_subpath = _get_exif_date(src_file) if use_exif else None
                if date_subpath:
                    dst_file = os.path.join(dst_path, date_subpath, os.path.basename(f))
                    rel_path = os.path.join(date_subpath, os.path.basename(f))
                else:
                    dst_file = os.path.join(dst_path, rel_path)
                    
                is_collision = os.path.exists(dst_file)
                if is_collision:
                    collisions.append(rel_path)
                file_size = 0
                if not os.path.islink(src_file):
                    try: file_size = os.path.getsize(src_file)
                    except OSError: pass
                all_files.append((src_file, dst_file, file_size, is_collision))

        if collisions:
            collision_rule = cfg.get("on_collision", "skip")
            if collision_rule in ["skip", "overwrite"]:
                Z_STATE.copy_overwrite_choice = collision_rule
            else:
                Z_STATE.copy_status = "awaiting_confirmation"
                Z_STATE.copy_progress["file"] = f"{len(collisions)} files already exist in destination."
                add_event("warning", "Copy Collision", f"{len(collisions)} files already exist. Waiting for confirmation.")
                Z_STATE.ui_wake.set()
                
                Z_STATE.copy_confirm_event.clear()
                Z_STATE.copy_confirm_event.wait(timeout=300.0)
                
                if not Z_STATE.copy_confirm_event.is_set():
                    raise Exception("Aborted: Timed out waiting for overwrite confirmation.")
                
                if Z_STATE.copy_overwrite_choice == "cancel":
                    raise Exception("Aborted by user.")

        files_to_copy = []
        total_size = 0
        for src_file, dst_file, file_size, is_collision in all_files:
            if is_collision and collisions and Z_STATE.copy_overwrite_choice == "skip":
                continue
            if file_size > 0:
                total_size += file_size
                files_to_copy.append((src_file, dst_file))

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
            try:
                async with aiofiles.open(src_f, 'rb') as fsrc, aiofiles.open(dst_f, 'wb') as fdst:
                    while True:
                        if Z_STATE.copy_abort_flag: break
                        while getattr(Z_STATE, 'copy_paused', False):
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
                        await fdst.write(buf)
                        Z_STATE.copy_progress["copied"] += len(buf)
                if Z_STATE.copy_abort_flag: os.remove(dst_f); break
                shutil.copystat(src_f, dst_f)
                Z_STATE.copy_progress['files_done'] += 1
            except Exception as e:
                logger.info(f"[ZettNAS] Error copying {src_f}: {e}")

        if Z_STATE.copy_abort_flag:
            Z_STATE.copy_status = "aborted"
            Z_STATE.copy_progress["file"] = "Aborted."
            add_event("warning", "Copy Aborted", "User aborted the copy operation.")
            raise Exception("Aborted by user.")
        else:
            Z_STATE.copy_status = "success"
            add_event("success", "Copy Completed", f"Successfully copied {Z_STATE.copy_progress['files_done']} files.")
        Z_STATE.copy_progress["file"] = "Finished successfully." 
        
    except Exception as e:
        logger.info(f"[ZettNAS] Copy failed: {e}")
        Z_STATE.copy_status = "error"
        Z_STATE.copy_progress["file"] = f"Error: {e}"
        add_event("error", "Copy Failed", str(e))
        try: send_led_packet(5, 255, 0, 0, 0, 0, 0, speed=10)
        except (OSError, ValueError): pass
    finally:
        if tmp_mount and mounted_path:
            subprocess.run(["umount", mounted_path])
        Z_STATE.copy_active = False
        Z_STATE.ui_wake.set()
        time.sleep(8)
        if not getattr(Z_STATE, 'copy_active', False):
            Z_STATE.copy_status = "idle"
            Z_STATE.ui_wake.set()
