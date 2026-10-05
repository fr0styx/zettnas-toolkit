import os
import re
import time
import subprocess
from backend.config import (
    logger, HOST_SYS, HOST_DEV, HOST_PROC, DISKS, OS_NVME,
    SMART_POLL_INTERVAL_HDD, SMART_POLL_INTERVAL_NVME, SHOW_OS_DISK
)
from backend.state import Z_STATE

_DISK_LIST_TTL = 60.0  # seconds

def _discover_disks():
    now = time.time()
    if Z_STATE.cached_disk_list is not None and (now - Z_STATE.cached_disk_list_time) < _DISK_LIST_TTL:
        return Z_STATE.cached_disk_list

    def rota(name):
        try:
            with open(os.path.join(HOST_SYS, "block", name, "queue/rotational")) as f:
                return f.read().strip() == "1"
        except Exception:
            return name.startswith("sd")

    def classify(name):
        if name == OS_NVME:
            return "os"
        return "data" if rota(name) else "cache"

    override = DISKS.strip()
    if override:
        result = [{"dev": d, "role": classify(d)} for d in override.split(",")]
        Z_STATE.cached_disk_list = result
        Z_STATE.cached_disk_list_time = now
        return result
    disks = []
    try:
        names = sorted(os.listdir(os.path.join(HOST_SYS, "block")))
        for name in names:
            if name.startswith("sd") and len(name) == 3:
                disks.append({"dev": name, "role": classify(name)})
        for name in names:
            if name.startswith("nvme") and name.endswith("n1"):
                disks.append({"dev": name, "role": classify(name)})
    except Exception as e:
        logger.debug(f"Silenced exception: {e}")
    Z_STATE.cached_disk_list = disks
    Z_STATE.cached_disk_list_time = now
    return disks

def _short_name(dev, idx_nvme=0):
    if dev.startswith("nvme"):
        return "nv" + dev[4]
    return dev

def _parse_smart(text, is_nvme):
    temp = None
    passed = None
    realloc = pending = offline = crc = 0
    nvme_spare = None
    nvme_spare_thresh = None
    nvme_used = None
    nvme_media_err = 0

    for line in text.splitlines():
        s = line.strip()
        low = s.lower()
        if "overall-health" in low:
            passed = "passed" in low
        if s.startswith("Temperature:"):
            nums = [int(x) for x in s.split() if x.isdigit()]
            if nums:
                temp = nums[0]
        elif ("Temperature_Celsius" in s or "Airflow_Temperature" in s) and temp is None:
            cols = s.split()
            if len(cols) >= 10 and cols[9].isdigit():
                temp = int(cols[9])

        def raw(cols):
            return int(cols[9]) if len(cols) >= 10 and cols[9].lstrip("-").isdigit() else 0

        if "Reallocated_Sector_Ct" in s:
            realloc = raw(s.split())
        elif "Current_Pending_Sector" in s:
            pending = raw(s.split())
        elif "Offline_Uncorrectable" in s:
            offline = raw(s.split())
        elif "UDMA_CRC_Error_Count" in s:
            crc = raw(s.split())

        if is_nvme:
            def pct_val(txt):
                return [int(x.rstrip("%")) for x in txt.split() if x.rstrip("%").isdigit()]
            if low.startswith("available spare:"):
                v = pct_val(s)
                if v: nvme_spare = v[0]
            elif low.startswith("available spare threshold:"):
                v = pct_val(s)
                if v: nvme_spare_thresh = v[0]
            elif low.startswith("percentage used:"):
                v = pct_val(s)
                if v: nvme_used = v[0]
            elif "media and data integrity errors" in low:
                v = [int(x.replace(",", "")) for x in s.split() if x.replace(",", "").isdigit()]
                if v: nvme_media_err = v[-1]

    health = "ok"
    if passed is False or pending > 0 or offline > 0 or nvme_media_err > 0:
        health = "crit"
    elif nvme_spare is not None and nvme_spare_thresh is not None and nvme_spare <= nvme_spare_thresh:
        health = "crit"
    elif temp is not None and temp >= 60:
        health = "crit"
    elif health != "crit":
        if realloc > 0 or crc > 0 or (nvme_used is not None and nvme_used >= 80):
            health = "warn"
        elif temp is not None and temp >= 50:
            health = "warn"
    return temp, health

if not hasattr(Z_STATE, "last_smart_scan"):
    Z_STATE.last_smart_scan = {}

def read_disk_temps_and_io():
    now = time.time()
    curr_io = {}
    try:
        with open(os.path.join(HOST_PROC, "diskstats")) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14:
                    dev = parts[2]
                    curr_io[dev] = int(parts[3]) + int(parts[7])
    except Exception as e:
        logger.debug(f"Silenced exception: {e}")

    out = []
    show_os = SHOW_OS_DISK
    for d in _discover_disks():
        dev_name = d["dev"]
        role = d["role"]
        if role == "os" and not show_os:
            continue
        dev = HOST_DEV.rstrip("/") + "/" + dev_name
        is_nvme = dev_name.startswith("nvme")
        dtype = "nvme" if is_nvme else "sat"

        poll_interval = SMART_POLL_INTERVAL_NVME if is_nvme else SMART_POLL_INTERVAL_HDD
        last_scan = Z_STATE.last_smart_scan.get(dev_name, 0.0)
        should_poll_smart = (now - last_scan) >= poll_interval

        is_standby = False
        if should_poll_smart or dev_name not in Z_STATE.cached_smart_data:
            Z_STATE.last_smart_scan[dev_name] = now
            try:
                cmd = ["smartctl"]
                if not is_nvme:
                    cmd.extend(["-n", "standby"])
                cmd.extend(["-H", "-A", "-d", dtype, dev])

                r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)

                if not is_nvme and (r.returncode == 2 or "STANDBY" in r.stdout.upper() or "SLEEP" in r.stdout.upper()):
                    is_standby = True
                    prev_t, _ = Z_STATE.cached_smart_data.get(dev_name, (None, "standby"))
                    temp = prev_t
                    health = "standby"
                    Z_STATE.cached_smart_data[dev_name] = (temp, health)
                else:
                    temp, health = _parse_smart(r.stdout, is_nvme)
                    Z_STATE.cached_smart_data[dev_name] = (temp, health)
            except Exception:
                temp, health = Z_STATE.cached_smart_data.get(dev_name, (None, "ok"))
        else:
            temp, health = Z_STATE.cached_smart_data.get(dev_name, (None, "ok"))
            is_standby = (health == "standby")

        prev_count = Z_STATE.prev_disk_io.get(dev_name, 0)
        curr_count = curr_io.get(dev_name, 0)
        io_active = (curr_count > prev_count) if prev_count > 0 else False

        out.append({
            "name": _short_name(dev_name, 0),
            "dev": dev_name,
            "temp": temp,
            "role": role,
            "health": health,
            "standby": is_standby,
            "active": io_active
        })

    Z_STATE.prev_disk_io = curr_io
    return out

def fetch_disk_smart_detail(dev_name):
    if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev_name):
        return {"error": "Invalid device name format."}

    dev = HOST_DEV.rstrip("/") + "/" + dev_name
    is_nvme = dev_name.startswith("nvme")
    dtype = "nvme" if is_nvme else "sat"
    try:
        r = subprocess.run(["smartctl", "-x", "-d", dtype, dev],
                           capture_output=True, text=True, timeout=12)
        raw_text = r.stdout
    except Exception as e:
        raw_text = f"Error querying device: {e}"

    model = "Unknown"
    serial = "Unknown"
    power_hours = "Unknown"
    health_verdict = "PASSED"

    for line in raw_text.splitlines():
        low = line.lower()
        if "device model:" in low or "model number:" in low:
            model = line.split(":", 1)[1].strip()
        elif "serial number:" in low:
            serial = line.split(":", 1)[1].strip()
        elif "power on hours:" in low or "power_on_hours" in low:
            parts = line.split()
            power_hours = parts[-1] if parts else "Unknown"
        elif "overall-health" in low:
            health_verdict = "PASSED" if "passed" in low else "FAILED"

    return {
        "dev": dev_name,
        "is_nvme": is_nvme,
        "model": model,
        "serial": serial,
        "power_on_hours": power_hours,
        "health": health_verdict,
        "raw": raw_text[:4000]
    }
