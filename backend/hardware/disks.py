import concurrent.futures
import json
import logging
import os
import re
import subprocess
import threading
import time
from typing import Optional

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
from backend.db import (
    get_latest_smart_test_result,
    get_smart_history_samples,
    get_smart_test_history,
    log_smart_metrics,
    log_smart_test_result,
    query_smart_velocity,
)
from backend.fsutil import atomic_write_json
from backend.services.notifications import send_notification
from backend.state import Z_STATE, add_event

logger = logging.getLogger("ZettNAS")

TRENDS_FILE = os.path.join(DATA_DIR, "smart_trends.json")
_smart_trends = None


def _evaluate_smart_trends(dev_name, metrics):
    global _smart_trends

    if _smart_trends is None:
        if os.path.exists(TRENDS_FILE):
            try:
                with open(TRENDS_FILE) as f:
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
        # growth is judged and alerted by Drive Health's verdicts (REL-7), not here
        for msg in alerts:
            logger.info(f"[SMART] {dev_name}: {msg}")


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
        if name == OS_NVME or name.startswith("mmcblk"):
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

    try:
        from backend.hardware.unraid import get_unraid_disk_roles

        unraid_roles = get_unraid_disk_roles()
        if unraid_roles:
            for entry in disks:
                d_dev = entry["dev"]
                base_dev = os.path.basename(d_dev)
                u_info = unraid_roles.get(d_dev) or unraid_roles.get(base_dev)
                if u_info and u_info.get("is_parity"):
                    entry["role"] = "parity"
                    entry["is_parity"] = True
                    entry["parity_label"] = u_info.get("parity_label", "P")
    except Exception as e:
        logger.debug(f"[disks] Error applying unraid roles: {e}")

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
    realloc = pending = offline = crc = timeouts = spin_retries = 0
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
            temp_from_194 = None
            temp_from_190 = None
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
                elif attr_id == 188:
                    timeouts = int(raw_val) & 0xFFFF  # Seagate packs three counters; the low one is timeouts
                elif attr_id == 10:
                    spin_retries = int(raw_val)
                elif attr_id == 194:
                    try:
                        raw_str = attr.get("raw", {}).get("string", "")
                        digits = [int(x) for x in raw_str.split() if x.isdigit()]
                        if digits:
                            t_val = digits[0]
                        else:
                            t_val = int(raw_val) & 0xFF
                        if 0 < t_val < 120:
                            temp_from_194 = t_val
                    except (ValueError, TypeError):
                        pass
                elif attr_id == 190:
                    try:
                        raw_str = attr.get("raw", {}).get("string", "")
                        digits = [int(x) for x in raw_str.split() if x.isdigit()]
                        if digits:
                            t_val = digits[0]
                        else:
                            t_val = int(raw_val) & 0xFF
                        if 0 < t_val < 120:
                            temp_from_190 = t_val
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
            if temp is None:
                if temp_from_194 is not None:
                    temp = temp_from_194
                elif temp_from_190 is not None:
                    temp = temp_from_190

        # Check for SAS / SCSI enterprise SMART data
        defect_list = doc.get("scsi_grown_defect_list")
        if defect_list is not None:
            try:
                realloc = int(defect_list)
            except (ValueError, TypeError):
                pass
        # SAS drives only: SATA drives have no error counter log and keep attribute 198
        err_log = doc.get("scsi_error_counter_log")
        if isinstance(err_log, dict) and err_log:
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
    if (
        passed is False
        or pending > 0
        or offline > 0
        or nvme_media_err > 0
        or nvme_spare is not None
        and nvme_spare_thresh is not None
        and nvme_spare <= nvme_spare_thresh
        or temp is not None
        and temp >= crit_temp
    ):
        health = "crit"
    elif health != "crit":
        if (
            realloc > 0
            or crc > 0
            or (nvme_used is not None and nvme_used >= 80)
            or temp is not None
            and temp >= warn_temp
        ):
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
        "timeouts": timeouts,
        "spin_retries": spin_retries,
    }
    return temp, health, metrics


def _extract_raw_val(cols: list[str]) -> int:
    """Extracts raw integer value from either 7/8-column (smartctl -x / modern)
    or 10-column (smartctl -A / legacy) ATA attribute row.

    Layouts:
    - 7/8-col (smartctl -x): ID(0) NAME(1) FLAGS(2) VAL(3) WORST(4) THRESH(5) FAIL(6) RAW_VALUE(7) [MIN/MAX/SUB_BYTES(8+)]
    - 10-col  (smartctl -A): ID(0) NAME(1) FLAG(2) VAL(3) WORST(4) THRESH(5) TYPE(6) UPDATED(7) WHEN_FAILED(8) RAW_VALUE(9) [MIN/MAX(10+)]
    """
    if not cols or len(cols) < 8:
        return 0

    raw_col = None
    # 1. Check for 10-column smartctl -A layout
    if len(cols) >= 10 and (cols[6] in ("Pre-fail", "Old_age") or cols[7] in ("Always", "Offline")):
        raw_col = cols[9]
    # 2. Check for 7/8-column smartctl -x layout
    elif len(cols) >= 8 and (len(cols[2]) == 6 or cols[6] in ("-", "NOW", "Past", "PAST")):
        raw_col = cols[7]
    # 3. Fallback heuristic: check if cols[9] or cols[7] contains the primary raw value
    elif len(cols) >= 10 and not cols[7].lstrip("-").isdigit() and cols[9].lstrip("-").isdigit():
        raw_col = cols[9]
    elif len(cols) >= 8:
        raw_col = cols[7]

    if not raw_col:
        return 0

    token = raw_col.split("(")[0].split("/")[0].strip()
    try:
        return int(token)
    except (ValueError, TypeError):
        m = re.search(r"-?\d+", token)
        return int(m.group(0)) if m else 0


def _parse_smart_text(text: str, is_nvme: bool):
    temp = None
    temp_from_194 = None
    temp_from_190 = None
    passed = None
    realloc = pending = offline = crc = timeouts = spin_retries = 0
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
        if s.startswith("Temperature:") or "current drive temperature:" in low or "current temperature:" in low:
            nums = [int(x) for x in s.split() if x.isdigit()]
            if nums and temp is None:
                temp = nums[0]
        elif "Temperature_Celsius" in s:
            val = _extract_raw_val(s.split())
            if 0 < val < 120:
                temp_from_194 = val
        elif "Airflow_Temperature" in s:
            val = _extract_raw_val(s.split())
            if 0 < val < 120:
                temp_from_190 = val

        if "Reallocated_Sector_Ct" in s:
            realloc = _extract_raw_val(s.split())
        elif "Current_Pending_Sector" in s:
            pending = _extract_raw_val(s.split())
        elif "Offline_Uncorrectable" in s:
            offline = _extract_raw_val(s.split())
        elif "UDMA_CRC_Error_Count" in s:
            crc = _extract_raw_val(s.split())
        elif "Command_Timeout" in s:
            timeouts = _extract_raw_val(s.split()) & 0xFFFF
        elif "Spin_Retry_Count" in s:
            spin_retries = _extract_raw_val(s.split())

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

    if temp is None:
        if temp_from_194 is not None:
            temp = temp_from_194
        elif temp_from_190 is not None:
            temp = temp_from_190

    crit_temp = NVME_CRITICAL_TEMP if is_nvme else 60
    warn_temp = NVME_WARN_TEMP if is_nvme else 50
    health = "ok"
    if (
        passed is False
        or pending > 0
        or offline > 0
        or nvme_media_err > 0
        or nvme_spare is not None
        and nvme_spare_thresh is not None
        and nvme_spare <= nvme_spare_thresh
        or temp is not None
        and temp >= crit_temp
    ):
        health = "crit"
    elif health != "crit":
        if (
            realloc > 0
            or crc > 0
            or (nvme_used is not None and nvme_used >= 80)
            or temp is not None
            and temp >= warn_temp
        ):
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
        "timeouts": timeouts,
        "spin_retries": spin_retries,
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
            logger.debug("backend.hardware.disks._parse_smart: ignored error", exc_info=True)
    return _parse_smart_text(data, is_nvme)


def _resolve_dev_path(dev_name: str) -> str:
    base = HOST_DEV if os.path.exists(HOST_DEV) else "/dev"
    clean_name = dev_name
    if clean_name.startswith("/host/dev/"):
        clean_name = clean_name[len("/host/dev/") :]
    elif clean_name.startswith("/dev/"):
        clean_name = clean_name[len("/dev/") :]
    elif clean_name.startswith("/"):
        if os.path.exists(clean_name):
            return clean_name
        clean_name = os.path.basename(clean_name)

    by_id = os.path.join(base, "disk", "by-id", clean_name)
    if os.path.exists(by_id):
        return by_id
    candidate = os.path.join(base, clean_name)
    if os.path.exists(candidate):
        return candidate
    return candidate


def _get_smart_device_type(dev_name: str, is_nvme: bool = False) -> str:
    """
    Resolves the smartctl device type (-d flag).
    For NVMe namespace block devices, smartmontools requires the broadcast NSID 0xffffffff
    ('nvme,0xffffffff') to correctly execute controller-level Device Self-Tests (Log 0x06).
    """
    clean = dev_name
    if clean.startswith("/host/dev/"):
        clean = clean[len("/host/dev/") :]
    elif clean.startswith("/dev/"):
        clean = clean[len("/dev/") :]

    is_nv = is_nvme or clean.startswith("nvme")
    dtype = "nvme,0xffffffff" if is_nv else "sat"
    if Z_STATE.cached_disk_list:
        for d in Z_STATE.cached_disk_list:
            if d.get("dev") == clean or d.get("dev") == dev_name:
                proto = d.get("smart_protocol")
                if proto:
                    return "nvme,0xffffffff" if proto == "nvme" else proto
                break
    return dtype


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
    dtype = _get_smart_device_type(dev_name, is_nvme)

    is_removable = False
    try:
        with open(os.path.join(HOST_SYS, "block", dev_name, "removable")) as f:
            is_removable = f.read().strip() == "1"
    except Exception:
        logger.debug("backend.hardware.disks.poll_disk_smart: ignored error", exc_info=True)

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

        is_standby = (not is_nvme) and (
            r.returncode == 2
            or (r.returncode & 2) != 0
            or "DEVICE IS IN STANDBY" in combined_out
            or "DEVICE IS IN SLEEP" in combined_out
            or "STANDBY MODE" in combined_out
            or "SLEEP MODE" in combined_out
        )

        if is_standby:
            prev_t, _ = Z_STATE.cached_smart_data.get(dev_name, (None, "standby"))
            Z_STATE.cached_smart_data[dev_name] = (prev_t, "standby")
        elif r.stdout and (r.returncode == 0 or (r.returncode & 7) == 0):
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
            is_fb_standby = (not is_nvme) and (
                r_fb.returncode == 2
                or (r_fb.returncode & 2) != 0
                or "DEVICE IS IN STANDBY" in fb_out
                or "DEVICE IS IN SLEEP" in fb_out
                or "STANDBY MODE" in fb_out
                or "SLEEP MODE" in fb_out
            )
            if is_fb_standby:
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


IDLE_AFTER_SECS = 600
_IO_SEEN: dict[str, tuple[int, float]] = {}  # dev -> (I/O count, when it last changed)


def _idle_for(dev_name: str, now: float) -> float:
    """Seconds since the disk last did any I/O, from /proc/diskstats (0 when unknown)."""
    try:
        with open(os.path.join(HOST_PROC, "diskstats")) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14 and parts[2] == dev_name:
                    count = int(parts[3]) + int(parts[7])
                    prev = _IO_SEEN.get(dev_name)
                    if prev is None or prev[0] != count:
                        _IO_SEEN[dev_name] = (count, now)
                        return 0.0
                    return now - prev[1]
    except (OSError, ValueError):
        logger.debug("disks: diskstats unreadable", exc_info=True)
    return 0.0


def _hdd_interval(dev_name: str, now: float) -> float:
    """The SMART interval for a spinning disk: longer once it has been idle (PERF-2, on by default)."""
    from backend import config as _cfg

    if getattr(_cfg, "SMART_IDLE_ADAPTIVE", True) and _idle_for(dev_name, now) >= IDLE_AFTER_SECS:
        return float(getattr(_cfg, "SMART_IDLE_POLL", 1800))
    return float(SMART_POLL_INTERVAL_HDD)


# One pool for every SMART round (PERF-2): its threads wait idle between rounds instead of being
# started and stopped every time, and a disk whose read is still running isn't queued again.
_SMART_POOL: concurrent.futures.ThreadPoolExecutor | None = None
_SMART_POOL_LOCK = threading.Lock()
_SMART_IN_FLIGHT: set[str] = set()


def _smart_pool() -> concurrent.futures.ThreadPoolExecutor:
    global _SMART_POOL
    with _SMART_POOL_LOCK:
        if _SMART_POOL is None:
            _SMART_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="SmartPoll")
        return _SMART_POOL


def _poll_one(dev_name: str, is_nvme: bool) -> None:
    try:
        poll_disk_smart(dev_name, is_nvme)
    finally:
        with _SMART_POOL_LOCK:
            _SMART_IN_FLIGHT.discard(dev_name)


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
        poll_interval = SMART_POLL_INTERVAL_NVME if is_nvme else _hdd_interval(dev_name, now)
        last_scan = Z_STATE.last_smart_scan.get(dev_name, 0.0)
        if force or (now - last_scan) >= poll_interval or dev_name not in Z_STATE.cached_smart_data:
            targets.append((dev_name, is_nvme))

    with _SMART_POOL_LOCK:
        targets = [(dev, is_nv) for dev, is_nv in targets if dev not in _SMART_IN_FLIGHT]
        _SMART_IN_FLIGHT.update(dev for dev, _ in targets)
    if targets:
        pool = _smart_pool()
        futures = [pool.submit(_poll_one, dev, is_nv) for dev, is_nv in targets]
        concurrent.futures.wait(futures, timeout=15.0)


def read_disk_temps_and_io(allow_sync_poll: bool = False):
    """
    Fast, non-blocking telemetry method (<1ms):
    Reads /proc/diskstats for active I/O deltas and returns disk telemetry
    using background-cached SMART data. Never stalls the fan PWM loop.
    """
    now = time.time()
    curr_io = {}
    curr_sectors = {}
    try:
        with open(os.path.join(HOST_PROC, "diskstats")) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14:
                    dev = parts[2]
                    curr_io[dev] = int(parts[3]) + int(parts[7])
                    try:
                        curr_sectors[dev] = (int(parts[5]), int(parts[9]))
                    except (ValueError, IndexError):
                        pass
    except Exception as e:
        logger.debug(f"Silenced exception: {e}")

    prev_sectors = getattr(Z_STATE, "prev_disk_sectors", None)
    prev_time = getattr(Z_STATE, "prev_disk_time", 0.0)
    dt = max(0.1, now - prev_time) if prev_time > 0 else 0.0
    total_read_rate = 0.0
    total_write_rate = 0.0

    if prev_sectors and dt > 0:
        delta_r_sec = 0
        delta_w_sec = 0
        for dev, (r_sec, w_sec) in curr_sectors.items():
            if dev in prev_sectors:
                p_r, p_w = prev_sectors[dev]
                if r_sec >= p_r:
                    delta_r_sec += r_sec - p_r
                if w_sec >= p_w:
                    delta_w_sec += w_sec - p_w
        total_read_rate = (delta_r_sec * 512.0) / dt
        total_write_rate = (delta_w_sec * 512.0) / dt

    Z_STATE.prev_disk_sectors = curr_sectors
    Z_STATE.prev_disk_time = now
    Z_STATE.disk_throughput = {
        "read_bytes_sec": total_read_rate,
        "write_bytes_sec": total_write_rate,
    }

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
        # Predicted failure (D6): a healthy-looking disk that is degrading shows as warn/crit
        risk = (getattr(Z_STATE, "disk_risk", {}) or {}).get(dev_name) or {}
        risk_level = str(risk.get("risk") or "low")
        if not is_standby and health in ("ok", "unknown"):
            if risk_level == "critical":
                health = "crit"
            elif risk_level == "high":
                health = "warn"
        prev_count = Z_STATE.prev_disk_io.get(dev_name, 0)
        curr_count = curr_io.get(dev_name, 0)
        io_active = (curr_count > prev_count) if prev_count > 0 else False

        is_parity = bool(d.get("is_parity")) or role == "parity"
        parity_label = d.get("parity_label", "P" if is_parity else "")

        out.append(
            {
                "name": _short_name(dev_name, 0),
                "dev": dev_name,
                "temp": temp,
                "role": role,
                "health": health,
                "risk": risk_level,
                "risk_advice": risk.get("advice", ""),
                "standby": is_standby,
                "active": io_active,
                "is_nvme": is_nvme,
                "is_parity": is_parity,
                "parity_label": parity_label,
            }
        )

    Z_STATE.prev_disk_io = curr_io
    return out


VALID_DEV_PATTERN = re.compile(r"^(sd[a-z]+|nvme[0-9]+n[0-9]+|vd[a-z]+|xvd[a-z]+|[a-zA-Z0-9_\-\.:]+)$")


def _parse_self_test_info(doc: dict | None, raw_text: str):
    in_progress = False
    percent_remaining = None
    percent_completed = 100
    status_text = ""
    is_aborted = False
    polling_mins = {}

    if doc:
        # 1. ATA self-test status
        ata_st = doc.get("ata_smart_data", {}).get("self_test", {})
        if ata_st:
            st_val = ata_st.get("status", {}).get("value", 0)
            st_str = ata_st.get("status", {}).get("string", "")
            polling_mins = ata_st.get("polling_minutes", {}) or {}
            status_text = st_str
            low_st = st_str.lower()
            if 240 <= st_val <= 249 or (
                "in progress" in low_st and "no self-test in progress" not in low_st and "not in progress" not in low_st
            ):
                in_progress = True
                if 241 <= st_val <= 249:
                    percent_remaining = (st_val - 240) * 10
                else:
                    percent_remaining = ata_st.get("remaining_percent", 90)
                percent_completed = max(0, min(100, 100 - percent_remaining))
            elif st_val == 0:
                percent_remaining = 0
                percent_completed = 100
            elif st_val in (1, 2) or "aborted" in low_st:
                is_aborted = True

        # 2. NVMe self-test status
        nvme_st = doc.get("nvme_self_test_log", {})
        if nvme_st:
            nv_curr = nvme_st.get("current_self_test_operation", {})
            nv_op = (
                nv_curr.get("value", 0)
                if isinstance(nv_curr, dict)
                else (int(nv_curr) if str(nv_curr).isdigit() else 0)
            )
            if nv_op != 0:
                in_progress = True
                pct = (
                    nvme_st.get("current_self_test_completion_percent")
                    or nvme_st.get("current_device_self_test_completion")
                    or nvme_st.get("current_self_test_completion")
                    or 0
                )
                if isinstance(pct, dict):
                    pct = pct.get("value", 0)
                percent_completed = int(pct)
                percent_remaining = max(0, min(100, 100 - percent_completed))
                status_text = (
                    nv_curr.get("string", "Self-test in progress")
                    if isinstance(nv_curr, dict)
                    else "Self-test in progress"
                )

    # 3. Fallback / supplementary check from raw_text
    for line in (raw_text or "").splitlines():
        low = line.lower()
        if "self-test execution status:" in low or "self-test status:" in low:
            txt = line.split(":", 1)[1].strip()
            if not status_text:
                status_text = txt
            if "in progress" in low and not ("no self-test in progress" in low or "not in progress" in low):
                in_progress = True
                m_comp = re.search(r"(\d+)%\s+(?:completed|done)", low)
                if m_comp:
                    percent_completed = int(m_comp.group(1))
                    percent_remaining = max(0, min(100, 100 - percent_completed))
                else:
                    m_rem = re.search(r"(\d+)%\s+(?:of test\s+)?remaining", low)
                    if m_rem:
                        percent_remaining = int(m_rem.group(1))
                        percent_completed = max(0, min(100, 100 - percent_remaining))
                    else:
                        m_val = re.search(r"\((\d+)\)", line)
                        if m_val:
                            val = int(m_val.group(1))
                            if 241 <= val <= 249:
                                percent_remaining = (val - 240) * 10
                                percent_completed = max(0, min(100, 100 - percent_remaining))
            elif "aborted" in low:
                is_aborted = True
        elif "short self-test routine recommended polling time:" in low and "short" not in polling_mins:
            m_p = re.search(r"\((\s*\d+)\)\s*minutes", low)
            if m_p:
                polling_mins["short"] = int(m_p.group(1).strip())
        elif "extended self-test routine recommended polling time:" in low and "extended" not in polling_mins:
            m_p = re.search(r"\((\s*\d+)\)\s*minutes", low)
            if m_p:
                polling_mins["extended"] = int(m_p.group(1).strip())

    # 4. Parse self-test log
    log_entries = []
    if doc:
        ata_log_table = (
            doc.get("ata_smart_self_test_log", {}).get("extended", {}).get("table")
            or doc.get("ata_smart_self_test_log", {}).get("standard", {}).get("table")
            or []
        )
        for idx, entry in enumerate(ata_log_table):
            status_str = entry.get("status", {}).get("string", "Unknown")
            passed = entry.get("status", {}).get("passed", True)
            log_entries.append(
                {
                    "num": idx + 1,
                    "type": entry.get("type", {}).get("string", "Offline"),
                    "status": status_str,
                    "passed": passed,
                    "lifetime_hours": entry.get("lifetime_hours", "-"),
                    "remaining_pct": entry.get("remaining_percent", 0),
                    "lba_first_error": entry.get("lba_first_error", "-") or "-",
                }
            )

        if not log_entries:
            nvme_log_table = doc.get("nvme_self_test_log", {}).get("table") or []
            for idx, entry in enumerate(nvme_log_table):
                code_obj = entry.get("self_test_code") or entry.get("type") or {}
                t_str = code_obj.get("string") if isinstance(code_obj, dict) else str(code_obj)
                res_obj = entry.get("self_test_result") or entry.get("result") or {}
                if isinstance(res_obj, dict):
                    res_str = res_obj.get("string", "Completed")
                    res_val = res_obj.get("value", 0)
                else:
                    res_str = str(res_obj)
                    res_val = 0 if "error" not in res_str.lower() and "fail" not in res_str.lower() else 1
                passed = res_val == 0
                poh = entry.get("power_on_hours", entry.get("lifetime_hours", "-"))
                failing_lba = entry.get("failing_lba", entry.get("lba_first_error", "-")) or "-"
                log_entries.append(
                    {
                        "num": idx + 1,
                        "type": t_str or "Self-test",
                        "status": res_str,
                        "passed": passed,
                        "lifetime_hours": poh,
                        "remaining_pct": 0,
                        "lba_first_error": failing_lba,
                    }
                )

    # Fallback to text parsing if log_entries is still empty
    if not log_entries:
        for line in (raw_text or "").splitlines():
            m = re.match(
                r"^(?:#\s*)?(\d+)\s+([A-Za-z0-9_\s]+?)\s{2,}(Completed[^\d\n\r]+?|Aborted[^\d\n\r]+?|Failed[^\d\n\r]+?|In progress[^\d\n\r]+?|Self-test[^\d\n\r]+?|Interrupted[^\d\n\r]+?|Fatal[^\d\n\r]+?|Unknown[^\d\n\r]+?)\s+(?:(\d{1,2}%)\s+)?(\d+)\s+([0-9a-zA-Z_\-]+)",
                line.strip(),
            )
            if m:
                num, test_desc, status_str, remaining, hours, lba = m.groups()
                status_clean = status_str.strip()
                passed = "without error" in status_clean.lower() or (
                    "completed" in status_clean.lower() and "error" not in status_clean.lower()
                )
                rem_pct = int(remaining.replace("%", "").strip()) if remaining else 0
                log_entries.append(
                    {
                        "num": int(num),
                        "type": test_desc.strip(),
                        "status": status_clean,
                        "passed": passed,
                        "remaining_pct": rem_pct,
                        "lifetime_hours": int(hours.strip()) if hours.strip().isdigit() else hours.strip(),
                        "lba_first_error": lba.strip(),
                    }
                )

    progress = {
        "in_progress": in_progress,
        "percent_remaining": percent_remaining,
        "percent_completed": percent_completed,
        "status_text": status_text or ("In progress" if in_progress else "Completed"),
        "is_aborted": is_aborted,
        "polling_minutes": polling_mins,
    }
    return progress, log_entries


def drive_health_for(dev_name: str, doc: dict | None) -> dict:
    """Drive Health's verdict for a drive: from smartctl's JSON when it was read now, else from its
    stored history (a sleeping drive is never woken for this)."""
    from backend.services import drive_health

    try:
        readings = drive_health.read_smartctl(doc) if doc else None
        result = drive_health.assess(readings, get_smart_history_samples(dev_name), get_smart_test_history(dev_name, 5))
    except Exception:
        logger.debug("backend.hardware.disks.drive_health_for: could not assess %s", dev_name, exc_info=True)
        return {"verdict": "unknown", "label": "Not read yet", "label_key": "unknown", "summary": "", "findings": []}
    remember_verdict(dev_name, result)
    return result


def drive_identity(dev_name: str) -> str:
    """A drive's lasting name: its WWN or serial, or the kernel name when neither is known (REL-7)."""
    try:
        for d in _discover_disks():
            if d.get("dev") == dev_name:
                for k in ("wwn", "serial"):
                    v = str(d.get(k) or "").strip()
                    if v and "standby" not in v.lower():
                        return f"{k}:{v}"
    except Exception:
        logger.debug("backend.hardware.disks.drive_identity: discovery failed", exc_info=True)
    return f"dev:{dev_name}"


def remember_verdict(dev_name: str, result: dict) -> None:
    """Keeps the latest verdict per drive for the Overview and the phone (status_summary), and
    alerts when it changed (REL-7)."""
    try:
        from backend.services import drive_alerts

        drive_alerts.on_verdict(dev_name, result, key=drive_identity(dev_name))
    except Exception:
        logger.debug("backend.hardware.disks.remember_verdict: alert not sent", exc_info=True)
    top = next((f for f in result.get("findings") or [] if f.get("severity") == result.get("verdict")), None)
    with Z_STATE.smart.lock:
        Z_STATE.drive_verdicts[dev_name] = {
            "verdict": result.get("verdict", "unknown"),
            "kind": (top or {}).get("kind", ""),
            "summary": result.get("summary", ""),
            "summary_key": result.get("summary_key", ""),
            "summary_params": result.get("summary_params") or {},
            "ts": time.time(),
        }


# The latest S.M.A.R.T. reading per drive, shared by Drive Health's list, its detail pane and the
# S.M.A.R.T. detail route, so opening the window reads each drive once, not twice. One reader per
# drive at a time: a second caller waits for the first and takes its reading.
_DETAIL_CACHE: dict[str, tuple[float, dict]] = {}
_DETAIL_LOCKS: dict[str, threading.Lock] = {}
_DETAIL_LOCKS_GUARD = threading.Lock()


def _detail_lock(dev_name: str) -> threading.Lock:
    with _DETAIL_LOCKS_GUARD:
        return _DETAIL_LOCKS.setdefault(dev_name, threading.Lock())


def cached_smart_detail(dev_name: str, max_age: float) -> dict | None:
    """The last reading of this drive (or its error) if at most max_age seconds old, else None."""
    hit = _DETAIL_CACHE.get(dev_name)
    if hit and time.time() - hit[0] <= max_age:
        return hit[1]
    return None


def smart_detail_age(dev_name: str) -> float | None:
    hit = _DETAIL_CACHE.get(dev_name)
    return time.time() - hit[0] if hit else None


def forget_smart_detail(dev_name: str) -> None:
    _DETAIL_CACHE.pop(dev_name.removeprefix("/dev/").removeprefix("/host/dev/"), None)


def read_smart_detail(dev_name: str, wake_if_standby: bool = False, max_age: float = 0.0) -> dict:
    """fetch_disk_smart_detail, reusing a reading at most max_age seconds old (never when waking)."""
    with _detail_lock(dev_name):
        if not wake_if_standby and max_age > 0:
            hit = cached_smart_detail(dev_name, max_age)
            if hit is not None:
                return hit
        try:
            detail = fetch_disk_smart_detail(dev_name, wake_if_standby)
        except Exception as e:  # kept too, so one broken drive does not slow every opening
            detail = {"error": f"{type(e).__name__}: {e}"}
        if isinstance(detail, dict):
            _DETAIL_CACHE[dev_name] = (time.time(), detail)
        return detail


def is_drive_asleep(dev_name: str) -> bool:
    """Whether a drive is spun down right now, asked without waking it (smartctl -n standby).
    NVMe drives never count as asleep. Anything that would wake a drive that is asleep must be
    confirmed by the person first (the "disk.wake" confirmation)."""
    clean = dev_name.removeprefix("/dev/").removeprefix("/host/dev/")
    if clean.startswith("nvme") or not VALID_DEV_PATTERN.fullmatch(clean):
        return False
    try:
        r = subprocess.run(
            ["smartctl", "-n", "standby", "-i", "-d", _get_smart_device_type(clean, False), _resolve_dev_path(clean)],
            capture_output=True,
            text=True,
            timeout=6,
        )
    except (OSError, subprocess.SubprocessError):
        return (Z_STATE.cached_smart_data.get(clean) or (None, None))[1] == "standby"
    out = ((r.stdout or "") + " " + (r.stderr or "")).upper()
    return bool(
        r.returncode == 2
        or (r.returncode & 2) != 0
        or any(w in out for w in ("DEVICE IS IN STANDBY", "DEVICE IS IN SLEEP", "STANDBY MODE", "SLEEP MODE"))
    )


def refresh_drive_verdicts() -> int:
    """Judges every drive the way Drive Health does, never waking one. Run by the SMART poller."""
    done = 0
    for d in _discover_disks():
        dev = d.get("dev")
        if not dev:
            continue
        try:
            detail = read_smart_detail(dev, False)  # also keeps it for Drive Health's next opening
            if not (detail or {}).get("error"):
                done += 1
        except Exception:
            logger.debug("backend.hardware.disks.refresh_drive_verdicts: %s failed", dev, exc_info=True)
    return done


def fetch_disk_smart_detail(dev_name: str, wake_if_standby: bool = False):
    if not VALID_DEV_PATTERN.fullmatch(dev_name):
        return {"error": "Invalid device name format."}

    dev = _resolve_dev_path(dev_name)
    clean_name = dev_name.removeprefix("/dev/").removeprefix("/host/dev/")
    is_nvme = clean_name.startswith("nvme")
    dtype = _get_smart_device_type(dev_name, is_nvme)

    # If caller didn't explicitly request a wake, probe with -n standby to avoid spinning up platters.
    cached_temp, cached_health = Z_STATE.cached_smart_data.get(dev_name, (None, None))
    if not is_nvme and not wake_if_standby:
        try:
            r_sb = subprocess.run(
                ["smartctl", "-n", "standby", "-i", "-d", dtype, dev],
                capture_output=True,
                text=True,
                timeout=6,
            )
            sb_out = ((r_sb.stdout or "") + " " + (r_sb.stderr or "")).upper()
            if (
                r_sb.returncode == 2
                or (r_sb.returncode & 2) != 0
                or "DEVICE IS IN STANDBY" in sb_out
                or "DEVICE IS IN SLEEP" in sb_out
                or "STANDBY MODE" in sb_out
                or "SLEEP MODE" in sb_out
            ):
                Z_STATE.cached_smart_data[dev_name] = (cached_temp, "standby")
                return {
                    "dev": dev_name,
                    "is_nvme": False,
                    "model": "SATA HDD (Standby)",
                    "serial": "Hidden while in standby",
                    "power_on_hours": "Unknown (Standby)",
                    "health": "STANDBY",
                    "is_standby": True,
                    "temp": cached_temp,
                    "self_test_status": None,
                    "self_test_progress": {
                        "in_progress": False,
                        "percent_remaining": 0,
                        "percent_completed": 100,
                        "status_text": "Drive in standby",
                        "is_aborted": False,
                        "polling_minutes": {},
                    },
                    "self_test_log": [],
                    "latest_report": get_latest_smart_test_result(dev_name),
                    "metrics": {},
                    "degradation": query_smart_velocity(dev_name),
                    "drive_health": drive_health_for(dev_name, None),
                    "nvme_endurance": None,
                    "raw": "Device is in low-power STANDBY mode. Platters are not spinning.\nIssue a wake command to inspect live SMART counters.",
                }
        except Exception:
            logger.debug("backend.hardware.disks.fetch_disk_smart_detail: ignored error", exc_info=True)

    # For spinning HDDs, trigger hardware / kernel spinup if wake_if_standby was explicitly requested
    if not is_nvme and wake_if_standby:
        # 1. Unraid kernel mdcmd spinup integration
        try:
            for md_path in ("/proc/mdcmd", "/host/proc/mdcmd"):
                if os.path.exists(md_path) and os.access(md_path, os.W_OK):
                    from backend.hardware.unraid import _find_emhttp_dir

                    emhttp_dir = _find_emhttp_dir()
                    if emhttp_dir:
                        disks_ini = os.path.join(emhttp_dir, "disks.ini")
                        if os.path.isfile(disks_ini):
                            import configparser

                            cp = configparser.ConfigParser()
                            cp.read(disks_ini)
                            for sec in cp.sections():
                                dev_val = cp.get(sec, "device", fallback="").strip("\"'")
                                if dev_val == clean_name:
                                    idx = cp.get(sec, "idx", fallback="").strip("\"'")
                                    if idx:
                                        with open(md_path, "w") as f_cmd:
                                            f_cmd.write(f"spinup {idx}\n")
                                        logger.info(
                                            f"[Storage] Issued Unraid spinup {idx} for /dev/{clean_name} to {md_path}"
                                        )
                                        break
        except Exception as e:
            logger.debug(f"Unraid mdcmd spinup attempt on {clean_name} threw: {e}")

        # 2. Universal SATA PHY direct block read spinup
        try:
            subprocess.Popen(
                ["dd", f"if={dev}", "of=/dev/null", "count=1", "bs=512", "iflag=direct"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.debug(f"Direct block wake read on {dev} threw: {e}")

    doc = None
    cmd_j = ["smartctl", "-x", "-j", "-d", dtype]
    if not is_nvme and not wake_if_standby:
        cmd_j.extend(["-n", "standby"])
    cmd_j.append(dev)

    try:
        rj = subprocess.run(cmd_j, capture_output=True, text=True, timeout=25)
        if not is_nvme and not wake_if_standby:
            out_sb = ((rj.stdout or "") + " " + (rj.stderr or "")).upper()
            if (
                rj.returncode == 2
                or (rj.returncode & 2) != 0
                or "DEVICE IS IN STANDBY" in out_sb
                or "DEVICE IS IN SLEEP" in out_sb
            ):
                Z_STATE.cached_smart_data[dev_name] = (cached_temp, "standby")
                return {
                    "dev": dev_name,
                    "is_nvme": False,
                    "model": "SATA HDD (Standby)",
                    "serial": "Hidden while in standby",
                    "power_on_hours": "Unknown (Standby)",
                    "health": "STANDBY",
                    "is_standby": True,
                    "temp": cached_temp,
                    "self_test_status": None,
                    "self_test_progress": {
                        "in_progress": False,
                        "percent_remaining": 0,
                        "percent_completed": 100,
                        "status_text": "Drive in standby",
                        "is_aborted": False,
                        "polling_minutes": {},
                    },
                    "self_test_log": [],
                    "latest_report": get_latest_smart_test_result(dev_name),
                    "metrics": {},
                    "degradation": query_smart_velocity(dev_name),
                    "drive_health": drive_health_for(dev_name, None),
                    "nvme_endurance": None,
                    "raw": "Device is in low-power STANDBY mode. Platters are not spinning.\nIssue a wake command to inspect live SMART counters.",
                }
        if rj.stdout and rj.stdout.strip().startswith("{"):
            doc = json.loads(rj.stdout)
    except Exception:
        doc = None

    cmd_raw = ["smartctl", "-x", "-d", dtype]
    if not is_nvme and not wake_if_standby:
        cmd_raw.extend(["-n", "standby"])
    cmd_raw.append(dev)
    try:
        r = subprocess.run(cmd_raw, capture_output=True, text=True, timeout=25)
        raw_text = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
    except Exception as e:
        raw_text = f"Error querying device: {e}"

    model = "Unknown"
    serial = "Unknown"
    power_hours = "Unknown"
    health_verdict = "UNKNOWN"
    self_test_status = None

    if doc:
        model = doc.get("model_name") or doc.get("device", {}).get("model_name") or "Unknown"
        serial = doc.get("serial_number") or "Unknown"
        poh = doc.get("power_on_time", {}).get("hours")
        if poh is not None:
            power_hours = str(poh)
        sm_status = doc.get("smart_status", {})
        if "passed" in sm_status:
            health_verdict = "PASSED" if sm_status["passed"] else "FAILED"

    for line in raw_text.splitlines():
        low = line.lower()
        if model == "Unknown" and ("device model:" in low or "model number:" in low):
            model = line.split(":", 1)[1].strip()
        elif serial == "Unknown" and "serial number:" in low:
            serial = line.split(":", 1)[1].strip()
        elif power_hours == "Unknown" and ("power on hours:" in low or "power_on_hours" in low):
            parts = line.split()
            power_hours = parts[-1] if parts else "Unknown"
        elif health_verdict == "UNKNOWN" and "overall-health" in low:
            health_verdict = "PASSED" if "passed" in low else "FAILED"
        elif health_verdict == "UNKNOWN" and "smart health status:" in low:
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

    temp, smart_health, metrics = _parse_smart(doc if doc else raw_text, is_nvme)
    if temp is not None or smart_health != "standby":
        Z_STATE.cached_smart_data[dev_name] = (temp, smart_health if smart_health != "standby" else "ok")
        Z_STATE.last_smart_scan[dev_name] = time.time()
        Z_STATE.cached_smart_time[dev_name] = time.time()
        log_smart_metrics(int(time.time()), dev_name, temp, metrics)

    velocity = query_smart_velocity(dev_name)
    self_test_progress, self_test_log = _parse_self_test_info(doc, raw_text)

    return {
        "dev": dev_name,
        "is_nvme": is_nvme,
        "model": model,
        "serial": serial,
        "power_on_hours": power_hours,
        "health": health_verdict,
        "temp": temp,
        "self_test_status": self_test_status or self_test_progress.get("status_text"),
        "self_test_progress": self_test_progress,
        "self_test_log": self_test_log,
        "latest_report": get_latest_smart_test_result(dev_name),
        "metrics": metrics,
        "degradation": velocity,
        "drive_health": drive_health_for(dev_name, doc),
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


def run_disk_smart_test(dev_name: str, test_type: str = "short", skip_if_standby: bool = False):
    """
    Triggers or aborts an active S.M.A.R.T. self-test on the target disk via smartctl.
    Supported types: 'short', 'long' (extended), 'abort'.
    """
    clean_name = dev_name.removeprefix("/dev/").removeprefix("/host/dev/")
    if not VALID_DEV_PATTERN.fullmatch(clean_name):
        return {"success": False, "error": "Invalid device name format."}
    forget_smart_detail(clean_name)  # a test changes what the drive reports

    # Invariant: Never wake sleeping drive platters during automated scheduled self-tests
    if skip_if_standby:
        _, cached_health = Z_STATE.cached_smart_data.get(
            dev_name, Z_STATE.cached_smart_data.get(clean_name, (None, None))
        )
        is_sleeping = cached_health == "standby"
        if not is_sleeping:
            try:
                from backend.hardware.smart_engine import SmartEngine

                dev_path = _resolve_dev_path(dev_name)
                is_sleeping = SmartEngine.is_device_sleeping(dev_path)
            except Exception:
                logger.debug("backend.hardware.disks.run_disk_smart_test: ignored error", exc_info=True)

        if is_sleeping:
            return {
                "success": False,
                "skipped": True,
                "dev": dev_name,
                "test_type": test_type,
                "output": f"Drive {dev_name} is in standby mode. Skipping self-test to preserve platter sleep.",
            }

    dev = _resolve_dev_path(dev_name)
    clean_name = dev_name.removeprefix("/dev/").removeprefix("/host/dev/")
    is_nvme = clean_name.startswith("nvme")
    dtype = _get_smart_device_type(dev_name, is_nvme)

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
            or ("self-test has begun" in out.lower())
            or ("self-test routine aborted" in out.lower())
            or (action_name == "abort" and ("aborted" in out.lower() or "no self-test" in out.lower()))
        )
        polling_mins = 1 if action_name == "short" else 20

        if success:
            model = "Disk"
            serial = "Unknown"
            if Z_STATE.cached_disk_list:
                for d in Z_STATE.cached_disk_list:
                    if d.get("dev") == dev_name:
                        model = d.get("model") or model
                        serial = d.get("serial") or serial
                        break

            if action_name == "abort":
                with Z_STATE.lock:
                    Z_STATE.active_smart_tests.pop(dev_name, None)
                add_event(
                    level="warning",
                    title=f"S.M.A.R.T. Test Aborted: /dev/{dev_name}",
                    message=f"Self-test on {model} ({serial}) was manually cancelled by operator.",
                    details={
                        "type": "smart_test_aborted",
                        "dev": dev_name,
                        "model": model,
                        "serial": serial,
                    },
                )
            else:
                start_temp, _ = Z_STATE.cached_smart_data.get(dev_name, (None, None))
                with Z_STATE.lock:
                    Z_STATE.active_smart_tests[dev_name] = {
                        "dev": dev_name,
                        "test_type": action_name,
                        "start_time": time.time(),
                        "start_temp": start_temp,
                        "model": model,
                        "serial": serial,
                        "is_nvme": is_nvme,
                        "expected_minutes": polling_mins,
                        "last_pct": 0,
                    }
                add_event(
                    level="info",
                    title=f"S.M.A.R.T. {action_name.title()} Test Started: /dev/{dev_name}",
                    message=f"Integrity scan initiated on {model} ({serial}). Estimated duration: ~{polling_mins}m.",
                    details={
                        "type": "smart_test_start",
                        "dev": dev_name,
                        "test_type": action_name,
                        "model": model,
                        "serial": serial,
                        "expected_minutes": polling_mins,
                    },
                )

        err_msg = None
        if not success:
            filtered_lines = [
                line.strip()
                for line in out.splitlines()
                if line.strip()
                and not line.startswith("smartctl")
                and not line.startswith("Copyright")
                and not line.startswith("===")
            ]
            err_msg = filtered_lines[-1] if filtered_lines else (r.stderr or "Device self-test failed to initiate.")

        return {
            "success": success,
            "error": err_msg,
            "dev": dev_name,
            "test_type": action_name,
            "polling_minutes": polling_mins,
            "output": out.strip()[:1000],
        }
    except Exception as e:
        logger.error(f"[SMART] Failed to execute self-test action ({action_name}) on {dev_name}: {e}")
        return {"success": False, "error": str(e)}


def generate_smart_test_report_markdown(
    dev: str,
    test_type: str,
    status: str,
    passed: bool,
    model: str = "Unknown",
    serial: str = "Unknown",
    duration_sec: float = 0.0,
    power_on_hours: int = 0,
    temp_start: float | None = None,
    temp_end: float | None = None,
    lba_first_error: str = "-",
    is_nvme: bool = False,
    metrics: dict | None = None,
    recommendation: str = "",
) -> str:
    """Compiles an executive diagnostic report in clean GitHub-flavored markdown."""
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    mins = int(duration_sec // 60)
    secs = int(duration_sec % 60)
    dur_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
    verdict = "PASSED" if passed else ("ABORTED" if "abort" in status.lower() else "FAILED")
    verdict_emoji = "✓" if passed else ("⏹" if verdict == "ABORTED" else "✗")

    md = f"# S.M.A.R.T. Diagnostic Report: /dev/{dev}\n"
    md += f"**Execution Status**: {verdict_emoji} **{verdict}** ({status})\n"
    md += f"**Generated**: {generated_at}\n\n"

    md += "## Device Identification\n"
    md += f"- **Device Node**: `/dev/{dev}`\n"
    md += f"- **Drive Model**: {model}\n"
    md += f"- **Serial Number**: {serial}\n"
    md += f"- **Media Architecture**: {'PCIe NVMe Solid-State Drive' if is_nvme else 'SATA / SAS Drive'}\n"
    md += f"- **Power-On Lifetime**: {power_on_hours:,} hours\n\n"

    md += "## Test Execution Telemetry\n"
    md += f"- **Routine**: {test_type.title()} Diagnostic Scan\n"
    md += f"- **Duration**: {dur_str}\n"
    if temp_start is not None or temp_end is not None:
        t_s = f"{temp_start}°C" if temp_start is not None else "--"
        t_e = f"{temp_end}°C" if temp_end is not None else "--"
        md += f"- **Thermal Envelope**: {t_s} (start) -> {t_e} (completion)\n"
    md += f"- **First Error LBA**: {lba_first_error}\n\n"

    if is_nvme and metrics:
        md += "## Solid-State Health & Endurance\n"
        if metrics.get("nvme_spare") is not None:
            md += f"- **Available Spare**: {metrics['nvme_spare']}%\n"
        if metrics.get("nvme_used") is not None:
            md += f"- **Percentage Used (Wear)**: {metrics['nvme_used']}%\n"
        if metrics.get("nvme_media_err") is not None:
            md += f"- **Media and Data Integrity Errors**: {metrics['nvme_media_err']}\n"
        if metrics.get("tbw_tb") is not None:
            md += f"- **Total Bytes Written**: {metrics['tbw_tb']} TB\n"
        md += "\n"
    elif metrics:
        md += "## Platter Surface & Defect Telemetry\n"
        md += f"- **Reallocated Sectors**: {metrics.get('realloc', 0)}\n"
        md += f"- **Current Pending Sectors**: {metrics.get('pending', 0)}\n"
        md += f"- **Offline Uncorrectable Sectors**: {metrics.get('offline', 0)}\n"
        md += f"- **UDMA CRC Errors**: {metrics.get('crc', 0)}\n\n"

    if recommendation:
        md += "## Homelab Recommendation\n"
        md += f"{recommendation}\n"

    return md


UNREADABLE_TEST_GIVE_UP_S = 48 * 3600


def check_active_smart_tests():
    """
    Background watcher invoked by stats_collector smart_poller_daemon.
    Detects when in-flight self-tests finish on drive firmware, logs reports to DB,
    and publishes completion/failure events into the System Event Ledger.
    """
    with Z_STATE.lock:
        active_items = list(Z_STATE.active_smart_tests.items())

    if not active_items:
        return

    for dev_name, test_info in active_items:
        try:
            dev = _resolve_dev_path(dev_name)
            clean_name = dev_name.removeprefix("/dev/").removeprefix("/host/dev/")
            is_nvme = clean_name.startswith("nvme")
            dtype = _get_smart_device_type(dev_name, is_nvme)

            doc = None
            try:
                cmd_j = ["smartctl", "-x", "-j", "-d", dtype]
                if not is_nvme:
                    cmd_j.extend(["-n", "standby"])
                cmd_j.append(dev)
                rj = subprocess.run(
                    cmd_j,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if not is_nvme and (rj.returncode == 2 or (rj.returncode & 2) != 0):
                    continue
                if rj.stdout and rj.stdout.strip().startswith("{"):
                    doc = json.loads(rj.stdout)
            except Exception:
                doc = None

            try:
                cmd_raw = ["smartctl", "-x", "-d", dtype]
                if not is_nvme:
                    cmd_raw.extend(["-n", "standby"])
                cmd_raw.append(dev)
                r = subprocess.run(
                    cmd_raw,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if not is_nvme and (r.returncode == 2 or (r.returncode & 2) != 0):
                    continue
                raw_text = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
            except Exception as e:
                raw_text = f"Error: {e}"

            progress, log_entries = _parse_self_test_info(doc, raw_text)

            # smartctl said nothing usable (a timeout, a busy disk): that is no result, not a pass.
            # Ask again on the next poll; after two days give up and say the result is unknown.
            if not doc and not log_entries and not progress.get("in_progress") and not progress.get("is_aborted"):
                if time.time() - test_info.get("start_time", time.time()) < UNREADABLE_TEST_GIVE_UP_S:
                    continue
                with Z_STATE.lock:
                    Z_STATE.active_smart_tests.pop(dev_name, None)
                add_event(
                    level="warning",
                    title=f"S.M.A.R.T. test result unknown: /dev/{dev_name}",
                    message="The drive never reported how its self-test ended. Run it again.",
                    details={"type": "smart_test_result", "dev": dev_name, "status": "UNKNOWN", "passed": False},
                )
                continue

            if progress.get("in_progress"):
                with Z_STATE.lock:
                    if dev_name in Z_STATE.active_smart_tests:
                        Z_STATE.active_smart_tests[dev_name]["last_pct"] = progress.get("percent_completed", 0)
                continue

            # Test completed, aborted, or finished!
            with Z_STATE.lock:
                Z_STATE.active_smart_tests.pop(dev_name, None)

            start_time = test_info.get("start_time", time.time())
            duration_sec = max(1.0, round(time.time() - start_time, 1))
            test_type = test_info.get("test_type", "short")
            model = test_info.get("model", "Drive")
            serial = test_info.get("serial", "Unknown")
            is_nvme_drive = test_info.get("is_nvme", is_nvme)
            temp_start = test_info.get("start_temp")
            temp_end, _ = Z_STATE.cached_smart_data.get(dev_name, (None, None))

            # Determine pass/fail outcome
            is_aborted = bool(progress.get("is_aborted"))
            top_entry = log_entries[0] if log_entries else {}
            lba_err = top_entry.get("lba_first_error", "-") if top_entry else "-"

            if is_aborted:
                status = "ABORTED"
                passed = False
                level = "warning"
                title = f"S.M.A.R.T. {test_type.title()} Test Aborted: /dev/{dev_name}"
                summary = f"Self-test on {model} ({serial}) was interrupted before completion."
                rec = "Test was cancelled. Re-run Short or Extended test when array activity is low."
            elif top_entry.get("passed", True) and lba_err == "-":
                status = "PASSED"
                passed = True
                level = "success"
                title = f"S.M.A.R.T. {test_type.title()} Test Passed: /dev/{dev_name}"
                summary = f"Drive {model} ({serial}) passed all diagnostic routines without error."
                rec = "Drive passed all internal mechanical, magnetic, and electronics checks. Safe for array storage."
            else:
                status = "FAILED"
                passed = False
                level = "error"
                title = f"S.M.A.R.T. {test_type.title()} Test FAILED: /dev/{dev_name}"
                summary = f"Defect detected on {model} ({serial})! First failing LBA: {lba_err}."
                rec = f"CRITICAL: Hardware surface read failure detected at LBA {lba_err}. Immediately backup data and prepare disk replacement."

            # Fetch metrics
            _, _, metrics = {}, {}, {}
            poh = 0
            if doc:
                from backend.hardware.smart_engine import SmartTelemetryEngine

                _, _, metrics, _, _, hours_str = SmartTelemetryEngine.decode_smart_json(doc, is_nvme=is_nvme_drive)
                poh = int(hours_str) if str(hours_str).isdigit() else 0

            # Generate markdown report
            report_md = generate_smart_test_report_markdown(
                dev=dev_name,
                test_type=test_type,
                status=status,
                passed=passed,
                model=model,
                serial=serial,
                duration_sec=duration_sec,
                power_on_hours=poh,
                temp_start=temp_start,
                temp_end=temp_end,
                lba_first_error=lba_err,
                is_nvme=is_nvme_drive,
                metrics=metrics,
                recommendation=rec,
            )

            # Persist to database
            log_smart_test_result(
                dev=dev_name,
                test_type=test_type,
                status=status,
                passed=passed,
                duration_sec=duration_sec,
                power_on_hours=poh,
                temp_start=temp_start,
                temp_end=temp_end,
                lba_first_error=lba_err,
                model=model,
                serial=serial,
                is_nvme=is_nvme_drive,
                summary=summary,
                recommendation=rec,
                report_markdown=report_md,
                raw_details=top_entry,
            )

            # Publish to System Event Ledger
            add_event(
                level=level,
                title=title,
                message=summary,
                details={
                    "type": "smart_test_result",
                    "dev": dev_name,
                    "test_type": test_type,
                    "status": status,
                    "passed": passed,
                    "duration_sec": duration_sec,
                    "lba_first_error": lba_err,
                    "report_markdown": report_md,
                },
            )

            # If failed, send notification via Apprise
            if not passed and not is_aborted:
                try:
                    send_notification(
                        title=f"S.M.A.R.T. Hardware Failure: /dev/{dev_name}",
                        message=f"{model} ({serial}) failed {test_type.title()} test at LBA {lba_err}. Data loss risk: Replace drive immediately.",
                        level="critical",
                        event_type="smart",
                        dedup_key=f"smart_failure_{dev_name}",
                    )
                except Exception as notif_e:
                    logger.warning(f"[SMART] Failed to dispatch notification: {notif_e}")

        except Exception as e:
            logger.error(f"[SMART] Error checking active self-test for {dev_name}: {e}")


def locate_disk(dev_name: str, duration_sec: int = 5, allow_read_strobe: bool = True) -> dict:
    """
    Triggers physical drive identification strobe (Locate Drive / Blink Bay).
    Uses multi-tier hardware driver (SES -> ARGB -> Software Read Strobe).
    """
    if not VALID_DEV_PATTERN.fullmatch(dev_name):
        return {"success": False, "error": "Invalid device name format."}

    dev_path = _resolve_dev_path(dev_name)
    if not os.path.exists(dev_path):
        return {"success": False, "error": f"Device {dev_name} does not exist."}

    from backend.hardware.locate import locate_drive_multitier

    return locate_drive_multitier(dev_name, dev_path, duration_sec, allow_read_strobe)
