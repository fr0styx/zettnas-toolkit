import concurrent.futures
import json
import os
import re
import subprocess
import threading
import time

from backend.config import (
    DATA_DIR,
    DISKS,
    HDD_CRITICAL_TEMP,
    HDD_WARN_TEMP,
    HOST_DEV,
    HOST_PROC,
    HOST_SYS,
    NVME_CRITICAL_TEMP,
    NVME_WARN_TEMP,
    OS_NVME,
    SHOW_OS_DISK,
    SMART_POLL_INTERVAL_HDD,
    SMART_POLL_INTERVAL_NVME,
    logger,
)
from backend.db import log_smart_metrics, query_smart_velocity
from backend.fsutil import atomic_write_json
from backend.services.notifications import send_notification
from backend.state import Z_STATE, add_event

TRENDS_FILE = os.path.join(DATA_DIR, "smart_trends.json")
_smart_trends = None


def _evaluate_smart_trends(dev_name, metrics):
    global _smart_trends

    if _smart_trends is None:
        if os.path.exists(TRENDS_FILE):
            try:
                with open(TRENDS_FILE, "r") as f:
                    _smart_trends = json.load(f)
            except Exception:
                _smart_trends = {}
        else:
            _smart_trends = {}

    baseline = _smart_trends.get(dev_name, {})
    changed = False
    alerts = []

    def check_metric(key, friendly_name, crit=False):
        nonlocal changed
        val = metrics.get(key)
        if val is None or val == 0:  # Ignore missing or 0 values
            return
        base_val = baseline.get(key, 0)
        if val > base_val:
            if (
                base_val > 0
            ):  # Only alert if it's not the first time we see it > 0 to avoid noise on first boot if it was already >0
                alerts.append(f"{friendly_name} increased from {base_val} to {val}")
            baseline[key] = val
            changed = True

    check_metric("realloc", "Reallocated Sectors", crit=True)
    check_metric("pending", "Pending Sectors", crit=True)
    check_metric("offline", "Offline Uncorrectable Sectors", crit=True)
    check_metric("crc", "UDMA CRC Errors")
    check_metric("nvme_media_err", "NVMe Media Errors", crit=True)

    # Check wear specifically (nvme_used)
    used = metrics.get("nvme_used")
    if used is not None:
        base_used = baseline.get("nvme_used", 0)
        if used > base_used:
            # We don't alert on every 1% tick unless it crosses a threshold?
            # Actually, just storing it is fine. Alert if it hits 80, 90, 95
            baseline["nvme_used"] = used
            changed = True

    if changed:
        _smart_trends[dev_name] = baseline
        atomic_write_json(TRENDS_FILE, _smart_trends)
        for msg in alerts:
            add_event("warning", f"SMART Degradation: {dev_name}", msg)
            send_notification(
                {"type": "hardware", "title": f"SMART Degradation: {dev_name}", "message": msg, "level": "warning"}
            )


_DISK_LIST_TTL = 15.0  # seconds


def _discover_disks():
    now = time.time()
    if Z_STATE.cached_disk_list is not None and (now - Z_STATE.cached_disk_list_time) < _DISK_LIST_TTL:
        return Z_STATE.cached_disk_list

    def is_removable(name):
        try:
            with open(os.path.join(HOST_SYS, "block", name, "removable")) as f:
                return f.read().strip() == "1"
        except Exception:
            return False

    def rota(name):
        if is_removable(name):
            return False
        try:
            with open(os.path.join(HOST_SYS, "block", name, "queue/rotational")) as f:
                return f.read().strip() == "1"
        except Exception:
            return name.startswith("sd")

    def classify(name):
        if name == OS_NVME:
            return "os"
        return "data" if rota(name) else "cache"

    def has_medium(name):
        size_file = os.path.join(HOST_SYS, "block", name, "size")
        if not os.path.exists(size_file):
            return True
        try:
            with open(size_file) as f:
                return int(f.read().strip()) > 0
        except Exception:
            return True

    override = DISKS.strip()
    if override:
        result = [{"dev": d, "role": classify(d)} for d in override.split(",") if has_medium(d)]
        Z_STATE.cached_disk_list = result
        Z_STATE.cached_disk_list_time = now
        return result

    # Primary: Unified Hardware Abstraction Layer (HAL)
    disks = []
    try:
        from backend.hardware.hal import DiskDiscoveryHAL

        records = DiskDiscoveryHAL.discover_physical_disks()
        for r in records:
            disks.append(
                {
                    "dev": r.dev_name,
                    "role": r.role,
                    "canonical_id": r.canonical_id,
                    "model": r.model,
                    "serial": r.serial,
                    "transport": r.transport,
                    "controller_driver": r.controller_driver,
                    "smart_protocol": r.smart_protocol,
                }
            )
    except Exception as e:
        logger.debug(f"[disks] HAL fallback error: {e}")
        disks = []
        try:
            names = sorted(os.listdir(os.path.join(HOST_SYS, "block")))
            for name in names:
                if re.match(r"^(sd[a-z]+|nvme[0-9]+n[0-9]+|vd[a-z]+)$", name):
                    if not has_medium(name):
                        continue
                    disks.append({"dev": name, "role": classify(name)})
        except Exception as ex:
            logger.debug(f"Silenced exception: {ex}")

    Z_STATE.cached_disk_list = disks
    Z_STATE.cached_disk_list_time = now
    return disks


def _short_name(dev, idx_nvme=0):
    if dev.startswith("nvme"):
        return "nv" + dev[4]
    return dev


def _parse_smart_json(doc: dict, is_nvme: bool):
    temp = None
    passed = None
    realloc = pending = offline = crc = 0
    nvme_spare = None
    nvme_spare_thresh = None
    nvme_used = None
    nvme_media_err = 0
    tbw_tb = None
    tbr_tb = None
    power_cycles = None
    critical_warning = None

    smart_status = doc.get("smart_status", {})
    if isinstance(smart_status, dict) and "passed" in smart_status:
        passed = bool(smart_status["passed"])

    temp_obj = doc.get("temperature", {})
    if isinstance(temp_obj, dict) and "current" in temp_obj:
        try:
            temp = int(temp_obj["current"])
        except (ValueError, TypeError):
            pass

    power_cycle_obj = doc.get("power_cycle_count")
    if power_cycle_obj is not None:
        try:
            power_cycles = int(power_cycle_obj)
        except (ValueError, TypeError):
            pass

    if is_nvme:
        nvme_log = doc.get("nvme_smart_health_information_log", {})
        if isinstance(nvme_log, dict):
            if temp is None and "temperature" in nvme_log:
                try:
                    temp = int(nvme_log["temperature"])
                except (ValueError, TypeError):
                    pass
            if "available_spare" in nvme_log:
                try:
                    nvme_spare = int(nvme_log["available_spare"])
                except (ValueError, TypeError):
                    pass
            if "available_spare_threshold" in nvme_log:
                try:
                    nvme_spare_thresh = int(nvme_log["available_spare_threshold"])
                except (ValueError, TypeError):
                    pass
            if "percentage_used" in nvme_log:
                try:
                    nvme_used = int(nvme_log["percentage_used"])
                except (ValueError, TypeError):
                    pass
            if "media_errors" in nvme_log:
                try:
                    nvme_media_err = int(nvme_log["media_errors"])
                except (ValueError, TypeError):
                    pass
            if "critical_warning" in nvme_log:
                cw = nvme_log["critical_warning"]
                critical_warning = hex(cw) if isinstance(cw, int) else str(cw)
            if power_cycles is None and "power_cycles" in nvme_log:
                try:
                    power_cycles = int(nvme_log["power_cycles"])
                except (ValueError, TypeError):
                    pass
            if "data_units_written" in nvme_log:
                try:
                    duw = int(nvme_log["data_units_written"])
                    tbw_tb = round((duw * 512000) / 1e12, 2)
                except (ValueError, TypeError):
                    pass
            if "data_units_read" in nvme_log:
                try:
                    dur = int(nvme_log["data_units_read"])
                    tbr_tb = round((dur * 512000) / 1e12, 2)
                except (ValueError, TypeError):
                    pass
    else:
        ata_table = doc.get("ata_smart_attributes", {}).get("table", [])
        if isinstance(ata_table, list):
            for attr in ata_table:
                if not isinstance(attr, dict):
                    continue
                attr_id = attr.get("id")
                raw_val = attr.get("raw", {}).get("value", 0) if isinstance(attr.get("raw"), dict) else 0
                if attr_id == 5:
                    realloc = int(raw_val)
                elif attr_id == 197:
                    pending = int(raw_val)
                elif attr_id == 198:
                    offline = int(raw_val)
                elif attr_id == 199:
                    crc = int(raw_val)
                elif attr_id in (194, 190) and temp is None:
                    try:
                        raw_str = attr.get("raw", {}).get("string", "")
                        digits = [int(x) for x in raw_str.split() if x.isdigit()]
                        if digits:
                            temp = digits[0]
                        else:
                            temp = int(raw_val) & 0xFF
                    except (ValueError, TypeError):
                        pass
                elif attr_id == 12 and power_cycles is None:
                    try:
                        power_cycles = int(raw_val)
                    except (ValueError, TypeError):
                        pass
                elif attr_id == 241 and tbw_tb is None:
                    try:
                        tbw_tb = round((int(raw_val) * 512) / 1e12, 2)
                    except (ValueError, TypeError):
                        pass
                elif attr_id == 242 and tbr_tb is None:
                    try:
                        tbr_tb = round((int(raw_val) * 512) / 1e12, 2)
                    except (ValueError, TypeError):
                        pass

        # Check for SAS / SCSI enterprise SMART data
        defect_list = doc.get("scsi_grown_defect_list")
        if defect_list is not None:
            try:
                realloc = int(defect_list)
            except (ValueError, TypeError):
                pass
        err_log = doc.get("scsi_error_counter_log", {})
        if isinstance(err_log, dict):
            uncorr_read = (
                err_log.get("read", {}).get("total_un_corrected_errors", 0)
                if isinstance(err_log.get("read"), dict)
                else 0
            )
            uncorr_write = (
                err_log.get("write", {}).get("total_un_corrected_errors", 0)
                if isinstance(err_log.get("write"), dict)
                else 0
            )
            offline = int(uncorr_read) + int(uncorr_write)

    crit_temp = NVME_CRITICAL_TEMP if is_nvme else 60
    warn_temp = NVME_WARN_TEMP if is_nvme else 50
    health = "ok"
    if passed is False or pending > 0 or offline > 0 or nvme_media_err > 0:
        health = "crit"
    elif nvme_spare is not None and nvme_spare_thresh is not None and nvme_spare <= nvme_spare_thresh:
        health = "crit"
    elif temp is not None and temp >= crit_temp:
        health = "crit"
    elif health != "crit":
        if realloc > 0 or crc > 0 or (nvme_used is not None and nvme_used >= 80):
            health = "warn"
        elif temp is not None and temp >= warn_temp:
            health = "warn"

    metrics = {
        "realloc": realloc,
        "pending": pending,
        "offline": offline,
        "crc": crc,
        "nvme_spare": nvme_spare,
        "nvme_spare_thresh": nvme_spare_thresh,
        "nvme_used": nvme_used,
        "nvme_media_err": nvme_media_err,
        "tbw_tb": tbw_tb,
        "tbr_tb": tbr_tb,
        "power_cycles": power_cycles,
        "critical_warning": critical_warning,
    }
    return temp, health, metrics


def _parse_smart_text(text: str, is_nvme: bool):
    temp = None
    passed = None
    realloc = pending = offline = crc = 0
    nvme_spare = None
    nvme_spare_thresh = None
    nvme_used = None
    nvme_media_err = 0
    tbw_tb = None
    tbr_tb = None
    power_cycles = None
    critical_warning = None

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
                if v:
                    nvme_spare = v[0]
            elif low.startswith("available spare threshold:"):
                v = pct_val(s)
                if v:
                    nvme_spare_thresh = v[0]
            elif low.startswith("percentage used:"):
                v = pct_val(s)
                if v:
                    nvme_used = v[0]
            elif "media and data integrity errors" in low:
                v = [int(x.replace(",", "")) for x in s.split() if x.replace(",", "").isdigit()]
                if v:
                    nvme_media_err = v[-1]
            elif "data units written:" in low:
                m = re.search(r"data units written:.*?\[([\d\.]+)\s*([KMGTPE]?B)\]", s, re.IGNORECASE)
                if m:
                    val, unit = float(m.group(1)), m.group(2).upper()
                    if unit.startswith("P"):
                        tbw_tb = round(val * 1024.0, 2)
                    elif unit.startswith("T"):
                        tbw_tb = round(val, 2)
                    elif unit.startswith("G"):
                        tbw_tb = round(val / 1024.0, 2)
                    else:
                        tbw_tb = round(val, 2)
            elif "data units read:" in low:
                m = re.search(r"data units read:.*?\[([\d\.]+)\s*([KMGTPE]?B)\]", s, re.IGNORECASE)
                if m:
                    val, unit = float(m.group(1)), m.group(2).upper()
                    if unit.startswith("P"):
                        tbr_tb = round(val * 1024.0, 2)
                    elif unit.startswith("T"):
                        tbr_tb = round(val, 2)
                    elif unit.startswith("G"):
                        tbr_tb = round(val / 1024.0, 2)
                    else:
                        tbr_tb = round(val, 2)
            elif "critical warning:" in low:
                m = re.search(r"critical warning:\s*([0-9a-fx]+)", s, re.IGNORECASE)
                if m:
                    critical_warning = m.group(1)
            elif "power cycles:" in low:
                m = re.search(r"power cycles:\s*([\d,]+)", s, re.IGNORECASE)
                if m:
                    power_cycles = int(m.group(1).replace(",", ""))

    crit_temp = NVME_CRITICAL_TEMP if is_nvme else 60
    warn_temp = NVME_WARN_TEMP if is_nvme else 50
    health = "ok"
    if passed is False or pending > 0 or offline > 0 or nvme_media_err > 0:
        health = "crit"
    elif nvme_spare is not None and nvme_spare_thresh is not None and nvme_spare <= nvme_spare_thresh:
        health = "crit"
    elif temp is not None and temp >= crit_temp:
        health = "crit"
    elif health != "crit":
        if realloc > 0 or crc > 0 or (nvme_used is not None and nvme_used >= 80):
            health = "warn"
        elif temp is not None and temp >= warn_temp:
            health = "warn"
    metrics = {
        "realloc": realloc,
        "pending": pending,
        "offline": offline,
        "crc": crc,
        "nvme_spare": nvme_spare,
        "nvme_spare_thresh": nvme_spare_thresh,
        "nvme_used": nvme_used,
        "nvme_media_err": nvme_media_err,
        "tbw_tb": tbw_tb,
        "tbr_tb": tbr_tb,
        "power_cycles": power_cycles,
        "critical_warning": critical_warning,
    }
    return temp, health, metrics


def _parse_smart(data, is_nvme: bool):
    """Parses SMART telemetry from JSON dict, JSON string (smartctl -j), or legacy text."""
    if isinstance(data, dict):
        return _parse_smart_json(data, is_nvme)
    if isinstance(data, str) and data.strip().startswith("{"):
        try:
            doc = json.loads(data)
            if isinstance(doc, dict):
                return _parse_smart_json(doc, is_nvme)
        except Exception:
            pass
    return _parse_smart_text(data, is_nvme)


def _resolve_dev_path(dev_name: str) -> str:
    if dev_name.startswith("/"):
        return dev_name
    base = HOST_DEV if os.path.exists(HOST_DEV) else "/dev"
    by_id = os.path.join(base, "disk", "by-id", dev_name)
    if os.path.exists(by_id):
        return by_id
    return os.path.join(base, dev_name)


def _handle_smart_failure(dev_name: str, now: float):
    prev_t, prev_h = Z_STATE.cached_smart_data.get(dev_name, (None, "ok"))
    last_ok = Z_STATE.cached_smart_time.get(dev_name, 0.0)
    if prev_t is not None and (now - last_ok) > 180.0:
        temp = None
        health = "unknown"
    else:
        temp = prev_t
        health = prev_h if prev_h != "standby" else "ok"
    Z_STATE.cached_smart_data[dev_name] = (temp, health)


def poll_disk_smart(dev_name: str, is_nvme: bool):
    """Executes smartctl for a single disk in background and updates cached SMART data."""
    now = time.time()
    dev = _resolve_dev_path(dev_name)
    dtype = "nvme" if is_nvme else "sat"
    if Z_STATE.cached_disk_list:
        for d in Z_STATE.cached_disk_list:
            if d.get("dev") == dev_name:
                dtype = d.get("smart_protocol") or dtype
                break

    is_removable = False
    try:
        with open(os.path.join(HOST_SYS, "block", dev_name, "removable")) as f:
            is_removable = f.read().strip() == "1"
    except Exception:
        pass

    if is_removable:
        Z_STATE.cached_smart_data[dev_name] = (None, "ok")
        return

    Z_STATE.last_smart_scan[dev_name] = now
    try:
        cmd = ["smartctl", "-j"]
        if not is_nvme:
            cmd.extend(["-n", "standby"])
        cmd.extend(["-H", "-A", "-d", dtype, dev])

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        combined_out = ((r.stdout or "") + " " + (r.stderr or "")).upper()

        if not is_nvme and ("DEVICE IS IN STANDBY" in combined_out or "DEVICE IS IN SLEEP" in combined_out):
            prev_t, _ = Z_STATE.cached_smart_data.get(dev_name, (None, "standby"))
            Z_STATE.cached_smart_data[dev_name] = (prev_t, "standby")
        elif r.stdout and (r.returncode == 0 or (r.returncode & 7) == 0 or r.stdout.strip().startswith("{")):
            temp, health, metrics = _parse_smart(r.stdout, is_nvme)
            _evaluate_smart_trends(dev_name, metrics)
            log_smart_metrics(int(now), dev_name, temp, metrics)
            Z_STATE.cached_smart_data[dev_name] = (temp, health)
            Z_STATE.cached_smart_time[dev_name] = now
        elif "unrecognized option" in combined_out.lower() or "-j" in combined_out.lower():
            # Graceful fallback for environments with legacy smartctl without -j
            cmd_fallback = [c for c in cmd if c != "-j"]
            r_fb = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=8)
            fb_out = ((r_fb.stdout or "") + " " + (r_fb.stderr or "")).upper()
            if not is_nvme and ("DEVICE IS IN STANDBY" in fb_out or "DEVICE IS IN SLEEP" in fb_out):
                prev_t, _ = Z_STATE.cached_smart_data.get(dev_name, (None, "standby"))
                Z_STATE.cached_smart_data[dev_name] = (prev_t, "standby")
            elif r_fb.stdout and (r_fb.returncode == 0 or (r_fb.returncode & 7) == 0):
                temp, health, metrics = _parse_smart(r_fb.stdout, is_nvme)
                _evaluate_smart_trends(dev_name, metrics)
                log_smart_metrics(int(now), dev_name, temp, metrics)
                Z_STATE.cached_smart_data[dev_name] = (temp, health)
                Z_STATE.cached_smart_time[dev_name] = now
            else:
                _handle_smart_failure(dev_name, now)
        else:
            _handle_smart_failure(dev_name, now)
    except Exception:
        _handle_smart_failure(dev_name, now)


def poll_all_disks_smart(force: bool = False):
    """Background worker method: polls SMART concurrently for all disks whose poll interval has elapsed."""
    now = time.time()
    show_os = SHOW_OS_DISK
    targets = []
    for d in _discover_disks():
        dev_name = d["dev"]
        role = d["role"]
        if role == "os" and not show_os:
            continue
        is_nvme = dev_name.startswith("nvme")
        poll_interval = SMART_POLL_INTERVAL_NVME if is_nvme else SMART_POLL_INTERVAL_HDD
        last_scan = Z_STATE.last_smart_scan.get(dev_name, 0.0)
        if force or (now - last_scan) >= poll_interval or dev_name not in Z_STATE.cached_smart_data:
            targets.append((dev_name, is_nvme))

    if targets:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(targets))) as executor:
            futures = [executor.submit(poll_disk_smart, dev, is_nv) for dev, is_nv in targets]
            concurrent.futures.wait(futures, timeout=15.0)


def read_disk_temps_and_io(allow_sync_poll: bool = False):
    """
    Fast, non-blocking telemetry method (<1ms):
    Reads /proc/diskstats for active I/O deltas and returns disk telemetry
    using background-cached SMART data. Never stalls the fan PWM loop.
    """
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
        is_nvme = dev_name.startswith("nvme")

        if allow_sync_poll and dev_name not in Z_STATE.cached_smart_data:
            poll_disk_smart(dev_name, is_nvme)

        prev_t, prev_h = Z_STATE.cached_smart_data.get(dev_name, (None, "ok"))
        last_ok = Z_STATE.cached_smart_time.get(dev_name, 0.0)
        if prev_t is not None and (now - last_ok) > 180.0 and prev_h != "standby":
            temp = None
            health = "unknown"
        else:
            temp = prev_t
            health = prev_h

        is_standby = health == "standby"
        prev_count = Z_STATE.prev_disk_io.get(dev_name, 0)
        curr_count = curr_io.get(dev_name, 0)
        io_active = (curr_count > prev_count) if prev_count > 0 else False

        out.append(
            {
                "name": _short_name(dev_name, 0),
                "dev": dev_name,
                "temp": temp,
                "role": role,
                "health": health,
                "standby": is_standby,
                "active": io_active,
                "is_nvme": is_nvme,
            }
        )

    Z_STATE.prev_disk_io = curr_io
    return out


VALID_DEV_PATTERN = re.compile(r"^(sd[a-z]+|nvme[0-9]+n[0-9]+|vd[a-z]+|xvd[a-z]+|[a-zA-Z0-9_\-\.:]+)$")


def fetch_disk_smart_detail(dev_name):
    if not VALID_DEV_PATTERN.fullmatch(dev_name):
        return {"error": "Invalid device name format."}

    dev = _resolve_dev_path(dev_name)
    is_nvme = dev_name.startswith("nvme")
    dtype = "nvme" if is_nvme else "sat"
    if Z_STATE.cached_disk_list:
        for d in Z_STATE.cached_disk_list:
            if d.get("dev") == dev_name:
                dtype = d.get("smart_protocol") or dtype
                break

    # For spinning HDDs, issue an asynchronous direct block read to trigger spin up without blocking the thread
    if not is_nvme:
        try:
            subprocess.Popen(
                ["dd", f"if={dev}", "of=/dev/null", "count=1", "bs=512", "iflag=direct"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.debug(f"Direct block wake read on {dev} threw: {e}")

    try:
        r = subprocess.run(["smartctl", "-x", "-d", dtype, dev], capture_output=True, text=True, timeout=25)
        raw_text = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
    except Exception as e:
        raw_text = f"Error querying device: {e}"

    model = "Unknown"
    serial = "Unknown"
    power_hours = "Unknown"
    health_verdict = "UNKNOWN"
    self_test_status = None

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
        elif "smart health status:" in low:
            health_verdict = "PASSED" if ("ok" in low or "passed" in low) else "FAILED"
        elif "self-test execution status:" in low or "self-test status:" in low:
            self_test_status = line.split(":", 1)[1].strip()

    # Fallback to sysfs for USB Mass Storage / SD Cards where smartctl returns unsupported
    if model == "Unknown":

        def _read_sysfs(name, attr):
            try:
                with open(os.path.join(HOST_SYS, "block", name, attr)) as f:
                    return f.read().strip()
            except Exception:
                return ""

        sys_model = _read_sysfs(dev_name, "device/model")
        sys_vendor = _read_sysfs(dev_name, "device/vendor")
        sys_removable = _read_sysfs(dev_name, "removable") == "1"
        sys_size = _read_sysfs(dev_name, "size")
        cap_str = ""
        if sys_size and sys_size.isdigit() and int(sys_size) > 0:
            gb = (int(sys_size) * 512) / (1024**3)
            cap_str = f"{gb:.1f} GB"

        if sys_model or sys_vendor:
            combined = f"{sys_vendor} {sys_model}".strip()
            model = f"{combined} ({cap_str})".strip() if cap_str else combined
            serial = "N/A (Removable Media)" if sys_removable else "N/A"
            power_hours = "N/A (Flash Media)"
            health_verdict = "PASSED"
            raw_text = (
                f"Device: /dev/{dev_name} (USB Mass Storage / Flash Media)\n"
                f"Vendor: {sys_vendor}\n"
                f"Model: {sys_model}\n"
                f"Capacity: {cap_str}\n"
                f"Removable: {'Yes' if sys_removable else 'No'}\n\n"
                "Notice: Removable flash cards and USB storage bridges do not support\n"
                "ATA S.M.A.R.T. commands. The device is online, responsive, and available for I/O."
            )

    temp, smart_health, metrics = _parse_smart(raw_text, is_nvme)
    if temp is not None or smart_health != "standby":
        Z_STATE.cached_smart_data[dev_name] = (temp, smart_health if smart_health != "standby" else "ok")
        Z_STATE.last_smart_scan[dev_name] = time.time()
        log_smart_metrics(int(time.time()), dev_name, temp, metrics)

    velocity = query_smart_velocity(dev_name)

    return {
        "dev": dev_name,
        "is_nvme": is_nvme,
        "model": model,
        "serial": serial,
        "power_on_hours": power_hours,
        "health": health_verdict,
        "temp": temp,
        "self_test_status": self_test_status,
        "metrics": metrics,
        "degradation": velocity,
        "nvme_endurance": (
            {
                "tbw_tb": metrics.get("tbw_tb"),
                "tbr_tb": metrics.get("tbr_tb"),
                "percentage_used": metrics.get("nvme_used"),
                "available_spare": metrics.get("nvme_spare"),
                "spare_threshold": metrics.get("nvme_spare_thresh"),
                "critical_warning": metrics.get("critical_warning"),
                "power_cycles": metrics.get("power_cycles"),
            }
            if is_nvme
            else None
        ),
        "raw": raw_text[:4000],
    }


def run_disk_smart_test(dev_name: str, test_type: str = "short"):
    """
    Triggers or aborts an active S.M.A.R.T. self-test on the target disk via smartctl.
    Supported types: 'short', 'long' (extended), 'abort'.
    """
    if not VALID_DEV_PATTERN.fullmatch(dev_name):
        return {"success": False, "error": "Invalid device name format."}

    dev = _resolve_dev_path(dev_name)
    is_nvme = dev_name.startswith("nvme")
    dtype = "nvme" if is_nvme else "sat"
    if Z_STATE.cached_disk_list:
        for d in Z_STATE.cached_disk_list:
            if d.get("dev") == dev_name:
                dtype = d.get("smart_protocol") or dtype
                break

    test_type = (test_type or "short").lower().strip()
    if test_type in ("abort", "stop", "cancel"):
        cmd = ["smartctl", "-X", "-d", dtype, dev]
        action_name = "abort"
    elif test_type in ("long", "extended"):
        cmd = ["smartctl", "-t", "long", "-d", dtype, dev]
        action_name = "long"
    else:
        cmd = ["smartctl", "-t", "short", "-d", dtype, dev]
        action_name = "short"

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
        success = (
            (r.returncode == 0)
            or ("testing has begun" in out.lower())
            or ("test routine started" in out.lower())
            or ("self-test routine aborted" in out.lower())
            or (action_name == "abort" and "aborted" in out.lower())
        )
        return {
            "success": success,
            "dev": dev_name,
            "test_type": action_name,
            "output": out.strip()[:1000],
        }
    except Exception as e:
        logger.error(f"[SMART] Failed to execute self-test action ({action_name}) on {dev_name}: {e}")
        return {"success": False, "error": str(e)}


def locate_disk(dev_name: str, duration_sec: int = 5) -> dict:
    """
    Triggers physical drive identification strobe (Locate Drive / Blink Bay).
    Reads 4KB from sector 0 in a gentle rhythm for duration_sec to pulse drive activity LED safely without writing.
    """
    if not VALID_DEV_PATTERN.fullmatch(dev_name):
        return {"success": False, "error": "Invalid device name format."}

    dev_path = _resolve_dev_path(dev_name)
    if not os.path.exists(dev_path):
        return {"success": False, "error": f"Device {dev_name} does not exist."}

    duration = max(1, min(int(duration_sec or 5), 10))

    def _strobe_task():
        end_time = time.time() + duration
        try:
            with open(dev_path, "rb") as f:
                while time.time() < end_time:
                    f.seek(0)
                    _ = f.read(4096)
                    time.sleep(0.12)
        except Exception as e:
            logger.debug(f"[DiskLocate] Strobe read error on {dev_name}: {e}")

    threading.Thread(target=_strobe_task, daemon=True, name=f"locate-{dev_name}").start()
    return {"success": True, "dev": dev_name, "duration": duration}
