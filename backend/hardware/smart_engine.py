"""
ZettNAS Toolkit - Universal S.M.A.R.T. & Thermal Engine
Multi-Protocol Hardware Telemetry Provider with Zero-Wake Spindown Safety.
Supports SATA, PCIe NVMe, SAS enterprise HBAs, and USB mass storage bridges.
"""

import json
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.config import HDD_CRITICAL_TEMP, HDD_WARN_TEMP, NVME_CRITICAL_TEMP, NVME_WARN_TEMP, logger
from backend.db import log_smart_metrics
from backend.state import Z_STATE


class SmartTelemetryEngine:
    """
    High-reliability SMART inspector supporting SATA, PCIe NVMe, SAS enterprise,
    and USB mass storage bridges without waking sleeping drive platters.
    """

    @classmethod
    def is_device_sleeping(cls, dev_path: str) -> bool:
        """
        Non-invasive power mode query. Returns True if drive is in STANDBY or SLEEP mode.
        Executes smartctl -n standby or hdparm -C without triggering spindle spinup.
        """
        # 1. Primary check: smartctl -n standby -i
        try:
            cmd = ["smartctl", "-n", "standby", "-i", dev_path]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            # Exit code 2 indicates device is in STANDBY or SLEEP
            if (r.returncode & 2) != 0:
                return True
            out = ((r.stdout or "") + " " + (r.stderr or "")).upper()
            if "STANDBY" in out or "SLEEP" in out:
                return True
        except Exception:
            pass

        # 2. Secondary fallback: hdparm -C (ATA only)
        try:
            cmd = ["hdparm", "-C", dev_path]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and ("standby" in r.stdout.lower() or "sleeping" in r.stdout.lower()):
                return True
        except Exception:
            pass

        return False

    @classmethod
    def decode_smart_json(cls, doc: Dict[str, Any], is_nvme: bool, protocol: str = "sat") -> Tuple:
        """Decodes SMART telemetry from smartctl JSON output across SATA, NVMe, and SCSI."""
        model = doc.get("model_name") or doc.get("device", {}).get("model_name") or "Unknown"
        serial = doc.get("serial_number") or "Unknown"
        hours = str(doc.get("power_cycle_count") or "Unknown")

        passed = bool(doc.get("smart_status", {}).get("passed", True))
        temp = doc.get("temperature", {}).get("current")

        metrics: Dict[str, Any] = {
            "realloc": 0,
            "pending": 0,
            "offline": 0,
            "crc": 0,
            "nvme_used": None,
            "nvme_spare": None,
            "nvme_spare_thresh": None,
            "nvme_media_err": 0,
            "tbw_tb": None,
            "tbr_tb": None,
            "power_cycles": None,
            "critical_warning": None,
            "sas_grown_defects": None,
        }

        # Power on hours lookup in power_on_time
        if "power_on_time" in doc and "hours" in doc["power_on_time"]:
            hours = str(doc["power_on_time"]["hours"])

        if is_nvme or protocol == "nvme":
            nvme_log = doc.get("nvme_smart_health_information_log", {})
            if temp is None:
                temp = nvme_log.get("temperature")
            metrics["nvme_used"] = nvme_log.get("percentage_used")
            metrics["nvme_spare"] = nvme_log.get("available_spare")
            metrics["nvme_spare_thresh"] = nvme_log.get("available_spare_threshold")
            metrics["nvme_media_err"] = nvme_log.get("media_errors", 0)
            if "power_cycles" in nvme_log:
                metrics["power_cycles"] = nvme_log["power_cycles"]
            if "critical_warning" in nvme_log:
                cw = nvme_log["critical_warning"]
                metrics["critical_warning"] = hex(cw) if isinstance(cw, int) else str(cw)
            if "data_units_written" in nvme_log:
                try:
                    duw = int(nvme_log["data_units_written"])
                    metrics["tbw_tb"] = round((duw * 512000) / 1e12, 2)
                except (ValueError, TypeError):
                    pass
            if "data_units_read" in nvme_log:
                try:
                    dur = int(nvme_log["data_units_read"])
                    metrics["tbr_tb"] = round((dur * 512000) / 1e12, 2)
                except (ValueError, TypeError):
                    pass
        elif protocol == "scsi":
            # Enterprise SAS SMART Decoding
            defect_list = doc.get("scsi_grown_defect_list")
            if defect_list is not None:
                metrics["sas_grown_defects"] = int(defect_list)
                metrics["realloc"] = int(defect_list)
            err_log = doc.get("scsi_error_counter_log", {})
            uncorr_read = err_log.get("read", {}).get("total_un_corrected_errors", 0)
            uncorr_write = err_log.get("write", {}).get("total_un_corrected_errors", 0)
            metrics["offline"] = int(uncorr_read) + int(uncorr_write)
        else:
            # Standard ATA SMART Table Decoding
            for attr in doc.get("ata_smart_attributes", {}).get("table", []):
                aid = attr.get("id")
                raw_val = attr.get("raw", {}).get("value", 0)
                if aid == 5:
                    metrics["realloc"] = int(raw_val)
                elif aid == 197:
                    metrics["pending"] = int(raw_val)
                elif aid == 198:
                    metrics["offline"] = int(raw_val)
                elif aid == 199:
                    metrics["crc"] = int(raw_val)
                elif aid in (194, 190) and temp is None:
                    raw_str = attr.get("raw", {}).get("string", "")
                    digits = [int(x) for x in raw_str.split() if x.isdigit()]
                    if digits:
                        temp = digits[0]
                    else:
                        temp = int(raw_val) & 0xFF
                elif aid == 9:
                    hours = str(raw_val)
                elif aid == 12:
                    metrics["power_cycles"] = int(raw_val)
                elif aid == 241 and metrics["tbw_tb"] is None:
                    try:
                        metrics["tbw_tb"] = round((int(raw_val) * 512) / 1e12, 2)
                    except (ValueError, TypeError):
                        pass
                elif aid == 242 and metrics["tbr_tb"] is None:
                    try:
                        metrics["tbr_tb"] = round((int(raw_val) * 512) / 1e12, 2)
                    except (ValueError, TypeError):
                        pass

        # Health verdict synthesis
        crit_temp = NVME_CRITICAL_TEMP if (is_nvme or protocol == "nvme") else HDD_CRITICAL_TEMP
        warn_temp = NVME_WARN_TEMP if (is_nvme or protocol == "nvme") else HDD_WARN_TEMP
        health = "ok"

        if not passed or metrics["pending"] > 0 or metrics["offline"] > 0 or metrics["nvme_media_err"] > 0:
            health = "crit"
        elif (
            metrics["nvme_spare"] is not None
            and metrics["nvme_spare_thresh"] is not None
            and metrics["nvme_spare"] <= metrics["nvme_spare_thresh"]
        ):
            health = "crit"
        elif temp is not None and temp >= crit_temp:
            health = "crit"
        elif (
            metrics["realloc"] > 0
            or metrics["crc"] > 0
            or (metrics["nvme_used"] is not None and metrics["nvme_used"] >= 80)
        ):
            health = "warn"
        elif temp is not None and temp >= warn_temp:
            health = "warn"

        return temp, health, metrics, model, serial, hours

    @classmethod
    def query_smart_telemetry(
        cls,
        dev_name: str,
        dev_path: str,
        protocol: str = "sat",
        allow_wake: bool = False,
    ) -> Dict[str, Any]:
        """
        Queries SMART telemetry using multi-protocol auto-negotiation.
        Guarantees the Spindown Safety Invariant unless allow_wake is explicitly True.
        """
        now = time.time()
        is_nvme = protocol == "nvme" or dev_name.startswith("nvme")

        # Spindown Safety Guard for rotational media
        if not is_nvme and not allow_wake:
            if cls.is_device_sleeping(dev_path):
                prev_t, _ = Z_STATE.cached_smart_data.get(dev_name, (None, "standby"))
                Z_STATE.cached_smart_data[dev_name] = (prev_t, "standby")
                return {
                    "dev": dev_name,
                    "standby": True,
                    "temp": prev_t,
                    "health": "standby",
                    "metrics": {},
                    "model": "Sleeping Platter",
                    "serial": "N/A",
                }

        # Build protocol-aware smartctl execution probe chain
        probe_protocols = [protocol]
        if protocol in ("sat,auto", "usb"):
            probe_protocols = ["sat,auto", "sntrealtek", "sntjmicron", "sat"]

        stdout_doc: Optional[Dict[str, Any]] = None
        raw_text: str = ""

        for proto in probe_protocols:
            cmd = ["smartctl", "-j", "-H", "-A", "-d", proto]
            if not is_nvme and not allow_wake:
                cmd.extend(["-n", "standby"])
            cmd.append(dev_path)

            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                combined = (r.stdout or "") + " " + (r.stderr or "")

                if not is_nvme and (
                    "DEVICE IS IN STANDBY" in combined.upper() or "DEVICE IS IN SLEEP" in combined.upper()
                ):
                    prev_t, _ = Z_STATE.cached_smart_data.get(dev_name, (None, "standby"))
                    Z_STATE.cached_smart_data[dev_name] = (prev_t, "standby")
                    return {
                        "dev": dev_name,
                        "standby": True,
                        "temp": prev_t,
                        "health": "standby",
                        "metrics": {},
                    }

                if r.stdout and r.stdout.strip().startswith("{"):
                    try:
                        stdout_doc = json.loads(r.stdout)
                        raw_text = r.stdout
                        break
                    except Exception:
                        pass
            except Exception:
                continue

        if stdout_doc:
            temp, health, metrics, model, serial, hours = cls.decode_smart_json(stdout_doc, is_nvme, protocol)
        else:
            temp, health, metrics, model, serial, hours = None, "unknown", {}, "Unknown", "Unknown", "Unknown"

        if temp is not None or health != "standby":
            Z_STATE.cached_smart_data[dev_name] = (temp, health if health != "standby" else "ok")
            Z_STATE.cached_smart_time[dev_name] = now
            log_smart_metrics(int(now), dev_name, temp, metrics)

        return {
            "dev": dev_name,
            "standby": False,
            "temp": temp,
            "health": health,
            "model": model,
            "serial": serial,
            "power_on_hours": hours,
            "metrics": metrics,
            "raw": raw_text[:4000],
        }
