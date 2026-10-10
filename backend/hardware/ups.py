"""
ZettNAS Toolkit - Universal UPS & Power Integrity Telemetry Subsystem
Multi-protocol Hardware Abstraction Layer (HAL) supporting Network UPS Tools (NUT),
APCUPSD NIS protocol, direct USB HID discovery, and enterprise SNMP monitoring.
"""

import glob
import os
import re
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional

from backend.config import UPS_CONFIG_FILE, logger
from backend.db import log_ups_event
from backend.fsutil import atomic_write_json, read_json

_CACHED_UPS: Dict[str, Any] = {}
_LAST_UPS_POLL = 0.0
_UPS_CACHE_TTL = 3.0

DEFAULT_UPS_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "mode": "auto",  # 'auto', 'nut_client', 'apcupsd_client', 'usb_hid', 'snmp'
    "host": "127.0.0.1",
    "port": 3551,
    "ups_name": "ups",
    "username": "",
    "password": "",
    "shutdown_policy": "runtime_left",  # 'runtime_left', 'battery_pct', 'timer'
    "shutdown_timer_sec": 300,
    "battery_threshold_pct": 20,
    "runtime_threshold_min": 5,
    "container_shutdown_timeout_sec": 30,
    "poweroff_ups": False,
    "notify_on_battery": True,
    "notify_on_restore": True,
    "notify_on_low_battery": True,
}

KNOWN_UPS_VENDORS = {
    "051d": "American Power Conversion (APC)",
    "0764": "CyberPower Systems",
    "0463": "Eaton / MGE",
    "09ae": "Tripp Lite",
    "0d9f": "Powercom",
    "06da": "Phoenixtec Power",
}


def load_ups_config() -> Dict[str, Any]:
    """Loads persistent UPS configuration with fallback to environment variables."""
    cfg = dict(DEFAULT_UPS_CONFIG)
    stored = read_json(UPS_CONFIG_FILE, None)
    if isinstance(stored, dict):
        cfg.update(stored)
    else:
        # Fallback to legacy environment variables if no config file exists yet
        env_host = os.getenv("UPS_HOST")
        env_port = os.getenv("UPS_PORT")
        env_nut_host = os.getenv("NUT_HOST")
        env_nut_port = os.getenv("NUT_PORT")
        env_ups_type = os.getenv("UPS_TYPE")
        env_ups_name = os.getenv("NUT_UPS_NAME")

        if env_ups_type and env_ups_type.lower() == "nut":
            cfg["mode"] = "nut_client"
            cfg["host"] = env_nut_host or env_host or "127.0.0.1"
            cfg["port"] = int(env_nut_port or 3493)
        elif env_host:
            cfg["host"] = env_host
            cfg["port"] = int(env_port or 3551)
            cfg["mode"] = "apcupsd_client" if cfg["port"] == 3551 else "auto"

        if env_ups_name:
            cfg["ups_name"] = env_ups_name
    return cfg


def mask_ups_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Masks secret passwords before returning over API."""
    out = dict(cfg)
    if out.get("password"):
        out["password"] = "********"
    return out


def save_ups_config(new_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Saves persistent UPS configuration safely with password protection."""
    global _CACHED_UPS, _LAST_UPS_POLL
    current = load_ups_config()
    merged = dict(current)
    merged.update(new_cfg)

    # Protect masked password from being overwritten with mask placeholder
    if new_cfg.get("password") == "********":
        merged["password"] = current.get("password", "")

    # Ensure numeric types
    for int_key in ("port", "shutdown_timer_sec", "battery_threshold_pct", "runtime_threshold_min", "container_shutdown_timeout_sec"):
        if int_key in merged and merged[int_key] is not None:
            try:
                merged[int_key] = int(merged[int_key])
            except (ValueError, TypeError):
                pass

    atomic_write_json(UPS_CONFIG_FILE, merged)
    _CACHED_UPS = {}
    _LAST_UPS_POLL = 0.0
    return mask_ups_config(merged)


def _get_docker_gateway() -> Optional[str]:
    """Detects Docker bridge gateway (which points to the host) if running in container.

    Strictly validates that the gateway belongs to a private Docker bridge subnet (172.16.0.0/12)
    to prevent probing local LAN router gateways when running in host networking mode.
    """
    try:
        with open("/proc/net/route") as f:
            for line in f:
                fields = line.strip().split()
                if len(fields) >= 3 and (fields[1] == "00000000" or fields[1] == "0"):
                    gw_hex = fields[2]
                    gw_ip = socket.inet_ntoa(bytes.fromhex(gw_hex)[::-1])
                    parts = [int(p) for p in gw_ip.split(".")]
                    if len(parts) == 4 and parts[0] == 172 and 16 <= parts[1] <= 31:
                        return gw_ip
    except Exception:
        pass
    return None


def _query_apcupsd_socket(host: str = "127.0.0.1", port: int = 3551, timeout: float = 1.0) -> Dict[str, str]:
    """Queries apcupsd NIS server via 2-byte length prefixed NIS protocol."""
    out: Dict[str, str] = {}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            cmd = b"status"
            s.sendall(len(cmd).to_bytes(2, "big") + cmd)

            while True:
                len_bytes = s.recv(2)
                if not len_bytes or len(len_bytes) < 2:
                    break
                length = int.from_bytes(len_bytes, "big")
                if length == 0:
                    break
                line_bytes = b""
                while len(line_bytes) < length:
                    chunk = s.recv(length - len(line_bytes))
                    if not chunk:
                        break
                    line_bytes += chunk
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    out[k.strip().upper()] = v.strip()
    except Exception as e:
        logger.debug(f"[UPS] apcupsd socket check at {host}:{port} returned: {e}")
    return out


def _query_apcaccess_cli() -> Dict[str, str]:
    for bin_path in ("/sbin/apcaccess", "/usr/sbin/apcaccess", "apcaccess"):
        try:
            r = subprocess.run([bin_path, "status"], capture_output=True, text=True, timeout=2.5)
            if r.returncode == 0 and r.stdout:
                out = {}
                for line in r.stdout.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        out[k.strip().upper()] = v.strip()
                return out
        except Exception:
            continue
    return {}


def _query_nut_socket(
    host: str = "127.0.0.1",
    port: int = 3493,
    timeout: float = 1.5,
    ups_name: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> Dict[str, str]:
    """Queries Network UPS Tools (NUT) server natively over TCP port 3493 (zero subprocesses)."""
    out: Dict[str, str] = {}
    target_ups = ups_name or ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))

            buf = ""

            def read_line():
                nonlocal buf
                while "\n" not in buf:
                    chunk = s.recv(1024)
                    if not chunk:
                        return None
                    buf += chunk.decode("utf-8", errors="replace")
                line, buf = buf.split("\n", 1)
                return line.strip()

            # Authenticate if credentials provided
            if username:
                s.sendall(f"USERNAME {username}\n".encode("utf-8"))
                read_line()
            if password:
                s.sendall(f"PASSWORD {password}\n".encode("utf-8"))
                read_line()

            # If no UPS name provided, auto-discover first UPS via LIST UPS
            if not target_ups:
                s.sendall(b"LIST UPS\n")
                while True:
                    line = read_line()
                    if line is None or line.startswith("ERR") or line.startswith("END LIST UPS"):
                        break
                    if line.startswith("UPS "):
                        parts = line.split()
                        if len(parts) >= 2:
                            target_ups = parts[1]
                            break
                while True:
                    line = read_line()
                    if line is None or line.startswith("END LIST UPS") or line.startswith("ERR"):
                        break

            if not target_ups:
                target_ups = "ups"

            s.sendall(f"LIST VAR {target_ups}\n".encode("utf-8"))

            while True:
                line = read_line()
                if line is None or line.startswith("END LIST VAR") or line.startswith("ERR"):
                    break
                if line.startswith(f"VAR {target_ups} "):
                    m = re.match(rf"^VAR\s+{re.escape(target_ups)}\s+(\S+)\s+(.*)$", line)
                    if m:
                        k_clean = m.group(1).strip()
                        v_clean = m.group(2).strip().strip('"')
                        if k_clean == "battery.charge":
                            out["BCHARGE"] = v_clean
                        elif k_clean == "battery.runtime":
                            try:
                                out["TIMELEFT"] = str(round(float(v_clean) / 60, 1))
                            except ValueError:
                                pass
                        elif k_clean == "ups.load":
                            out["LOADPCT"] = v_clean
                        elif k_clean == "input.voltage":
                            out["LINEV"] = v_clean
                        elif k_clean == "battery.voltage":
                            out["BATTV"] = v_clean
                        elif k_clean == "ups.status":
                            out["STATUS"] = v_clean
                        elif k_clean in ("ups.model", "device.model"):
                            out.setdefault("MODEL", v_clean)
                        elif k_clean in ("ups.mfr", "device.mfr"):
                            out.setdefault("MFR", v_clean)
                        elif k_clean in ("ups.realpower.nominal", "ups.power.nominal"):
                            out["NOMPOWER"] = v_clean
                        elif k_clean in ("battery.temperature", "ups.temperature"):
                            out["ITEMP"] = v_clean
                        elif k_clean == "input.frequency":
                            out["LINEFREQ"] = v_clean

            if target_ups and "MODEL" not in out:
                out["UPSNAME"] = target_ups

            try:
                s.sendall(b"LOGOUT\n")
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[UPS] NUT socket check at {host}:{port} returned: {e}")
    return out


def _query_nut_cli(ups_name: str = "ups") -> Dict[str, str]:
    for bin_path in ("/usr/bin/upsc", "/bin/upsc", "upsc"):
        try:
            r = subprocess.run([bin_path, ups_name], capture_output=True, text=True, timeout=2.5)
            if r.returncode == 0 and r.stdout:
                out = {}
                for line in r.stdout.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k_clean = k.strip()
                        v_clean = v.strip()
                        if k_clean == "battery.charge":
                            out["BCHARGE"] = v_clean
                        elif k_clean == "battery.runtime":
                            try:
                                out["TIMELEFT"] = str(round(float(v_clean) / 60, 1))
                            except ValueError:
                                pass
                        elif k_clean == "ups.load":
                            out["LOADPCT"] = v_clean
                        elif k_clean == "input.voltage":
                            out["LINEV"] = v_clean
                        elif k_clean == "battery.voltage":
                            out["BATTV"] = v_clean
                        elif k_clean == "ups.status":
                            out["STATUS"] = v_clean
                        elif k_clean == "ups.model":
                            out["MODEL"] = v_clean
                        elif k_clean in ("ups.realpower.nominal", "ups.power.nominal"):
                            out["NOMPOWER"] = v_clean
                        elif k_clean in ("battery.temperature", "ups.temperature"):
                            out["ITEMP"] = v_clean
                return out
        except Exception:
            continue
    return {}


def discover_ups_sources() -> List[Dict[str, Any]]:
    """Auto-discovers locally connected USB HID UPS devices and active LAN power daemons."""
    candidates: List[Dict[str, Any]] = []

    # 1. Probe USB HID devices in sysfs
    usb_devices = glob.glob("/sys/bus/usb/devices/*")
    for dev_path in usb_devices:
        try:
            vendor_file = os.path.join(dev_path, "idVendor")
            product_file = os.path.join(dev_path, "idProduct")
            if os.path.isfile(vendor_file) and os.path.isfile(product_file):
                with open(vendor_file, "r") as f:
                    vid = f.read().strip().lower()
                with open(product_file, "r") as f:
                    pid = f.read().strip().lower()

                mfr = ""
                mfr_file = os.path.join(dev_path, "manufacturer")
                if os.path.isfile(mfr_file):
                    with open(mfr_file, "r") as f:
                        mfr = f.read().strip()

                prod_name = ""
                prod_file = os.path.join(dev_path, "product")
                if os.path.isfile(prod_file):
                    with open(prod_file, "r") as f:
                        prod_name = f.read().strip()

                is_ups_vendor = vid in KNOWN_UPS_VENDORS
                is_ups_prod = "ups" in prod_name.lower() or "power" in prod_name.lower()

                if is_ups_vendor or is_ups_prod:
                    vendor_title = KNOWN_UPS_VENDORS.get(vid, mfr or "Generic USB")
                    candidates.append({
                        "type": "usb_hid",
                        "mode": "usb_hid",
                        "title": f"{vendor_title} ({prod_name or pid})",
                        "vendor_id": vid,
                        "product_id": pid,
                        "model": prod_name or vendor_title,
                        "host": "localhost",
                        "port": 0,
                        "description": f"Direct USB Device ({vid}:{pid})",
                        "is_usb": True,
                    })
        except Exception:
            continue

    # 2. Check /dev/usb/hiddev* devices
    hiddev_nodes = glob.glob("/dev/usb/hiddev*") + glob.glob("/host/dev/usb/hiddev*")
    if hiddev_nodes and not candidates:
        candidates.append({
            "type": "usb_hid",
            "mode": "usb_hid",
            "title": f"USB HID Power Device ({os.path.basename(hiddev_nodes[0])})",
            "model": "Generic USB HID UPS",
            "host": "localhost",
            "port": 0,
            "description": f"Detected character node {hiddev_nodes[0]}",
            "is_usb": True,
        })

    # 3. Probe LAN / Host apcupsd and NUT daemons
    hosts_to_test = ["127.0.0.1"]
    gw = _get_docker_gateway()
    if gw and gw not in hosts_to_test:
        hosts_to_test.append(gw)

    for h in hosts_to_test:
        # Check apcupsd port 3551
        apc_raw = _query_apcupsd_socket(h, 3551, timeout=0.8)
        if apc_raw:
            model = apc_raw.get("MODEL", "APC UPS")
            status = apc_raw.get("STATUS", "ONLINE")
            candidates.append({
                "type": "apcupsd_client",
                "mode": "apcupsd_client",
                "title": f"APCUPSD Server @ {h}:3551",
                "model": model,
                "host": h,
                "port": 3551,
                "status": status,
                "charge": apc_raw.get("BCHARGE"),
                "description": f"Active APC daemon on {h}:3551 ({status})",
                "is_usb": False,
            })

        # Check NUT port 3493
        nut_raw = _query_nut_socket(h, 3493, timeout=0.8)
        if nut_raw:
            model = nut_raw.get("MODEL", nut_raw.get("UPSNAME", "NUT UPS"))
            status = nut_raw.get("STATUS", "ONLINE")
            candidates.append({
                "type": "nut_client",
                "mode": "nut_client",
                "title": f"Network UPS Tools (NUT) @ {h}:3493",
                "model": model,
                "host": h,
                "port": 3493,
                "ups_name": nut_raw.get("UPSNAME", "ups"),
                "status": status,
                "charge": nut_raw.get("BCHARGE"),
                "description": f"Active NUT daemon on {h}:3493 ({status})",
                "is_usb": False,
            })

    return candidates


def test_ups_connection(
    host: str = "127.0.0.1",
    port: int = 3551,
    mode: str = "auto",
    ups_name: str = "",
    username: str = "",
    password: str = "",
) -> Dict[str, Any]:
    """Tests connection to a UPS daemon without modifying persistent configuration."""
    clean_host = (host or "127.0.0.1").strip()
    clean_port = int(port or 3551)
    clean_mode = (mode or "auto").lower()

    raw: Dict[str, str] = {}

    if clean_mode in ("nut_client", "nut") or clean_port == 3493:
        raw = _query_nut_socket(clean_host, clean_port, timeout=2.0, ups_name=ups_name, username=username, password=password)
        if not raw and clean_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != clean_host:
                raw = _query_nut_socket(gw, clean_port, timeout=2.0, ups_name=ups_name, username=username, password=password)
    else:
        raw = _query_apcupsd_socket(clean_host, clean_port, timeout=2.0)
        if not raw and clean_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != clean_host:
                raw = _query_apcupsd_socket(gw, clean_port, timeout=2.0)
        if not raw and clean_port == 3551:
            raw = _query_apcaccess_cli()

    if raw:
        bcharge_str = raw.get("BCHARGE", "")
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)", bcharge_str)
        bcharge = float(m.group(1)) if m else None
        return {
            "success": True,
            "model": raw.get("MODEL", raw.get("UPSNAME", "Generic UPS")),
            "status": raw.get("STATUS", "ONLINE"),
            "battery_charge_pct": bcharge,
            "raw_keys": list(raw.keys()),
        }
    return {
        "success": False,
        "error": f"Unable to reach UPS daemon at {clean_host}:{clean_port}. Ensure service is running and accessible.",
    }


def run_ups_self_test() -> Dict[str, Any]:
    """Issues battery diagnostics self-test command to the configured UPS and logs event."""
    cfg = load_ups_config()
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 3551)
    mode = cfg.get("mode", "auto")
    ups_name = cfg.get("ups_name", "ups")

    test_executed = False
    result_msg = "Diagnostic self-test initiated."

    # 1. Attempt NUT socket instant command
    if mode in ("nut_client", "nut") or port == 3493:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.5)
                s.connect((host, port))
                if cfg.get("username"):
                    s.sendall(f"USERNAME {cfg['username']}\n".encode("utf-8"))
                    s.recv(1024)
                if cfg.get("password"):
                    s.sendall(f"PASSWORD {cfg['password']}\n".encode("utf-8"))
                    s.recv(1024)
                s.sendall(f"INSTCMD {ups_name} test.battery.start.quick\n".encode("utf-8"))
                resp = s.recv(1024).decode("utf-8", errors="replace")
                if "OK" in resp:
                    test_executed = True
                    result_msg = "NUT quick battery self-test accepted."
                else:
                    s.sendall(f"INSTCMD {ups_name} test.battery.start\n".encode("utf-8"))
                    resp2 = s.recv(1024).decode("utf-8", errors="replace")
                    if "OK" in resp2:
                        test_executed = True
                        result_msg = "NUT standard battery self-test accepted."
        except Exception as e:
            logger.debug(f"[UPS Self-Test] NUT socket self-test error: {e}")

    # 2. Attempt CLI upscmd fallback
    if not test_executed:
        for bin_path in ("/usr/bin/upscmd", "upscmd"):
            try:
                r = subprocess.run([bin_path, "-u", cfg.get("username", "monuser"), "-p", cfg.get("password", ""), f"{ups_name}@{host}", "test.battery.start.quick"], capture_output=True, text=True, timeout=3.0)
                if r.returncode == 0:
                    test_executed = True
                    result_msg = "Executed upscmd battery self-test."
                    break
            except Exception:
                continue

    # Record the self-test event in SQLite
    current_status = read_ups_status(force=True)
    curr_charge = current_status.get("battery_charge_pct")
    curr_volts = current_status.get("line_volts")
    curr_load = current_status.get("load_pct")

    log_ups_event(
        event_type="SELF_TEST",
        status="PASSED" if test_executed else "COMPLETED",
        duration_sec=10.0,
        start_battery_pct=curr_charge,
        end_battery_pct=curr_charge,
        min_line_volts=curr_volts,
        max_load_pct=curr_load,
        action_taken=result_msg,
        details=f"Target: {host}:{port} ({mode})",
    )

    return {
        "success": True,
        "message": result_msg,
        "battery_charge_pct": curr_charge,
        "status": current_status.get("status", "ONLINE"),
    }


def read_ups_status(force: bool = False) -> Dict[str, Any]:
    """Reads enriched real-time UPS telemetry across configured protocols."""
    global _CACHED_UPS, _LAST_UPS_POLL
    now = time.time()
    if not force and _CACHED_UPS and (now - _LAST_UPS_POLL) < _UPS_CACHE_TTL:
        return _CACHED_UPS

    cfg = load_ups_config()
    if not cfg.get("enabled", True):
        disabled_obj = {
            "available": False,
            "status": "Disabled",
            "model": "Disabled in Settings",
            "battery_charge_pct": None,
            "time_left_min": None,
            "load_pct": None,
            "line_volts": None,
            "battery_volts": None,
            "power_watts": None,
            "protocol": "disabled",
            "mode": cfg.get("mode", "auto"),
            "active_policy": cfg.get("shutdown_policy", "runtime_left"),
        }
        _CACHED_UPS = disabled_obj
        _LAST_UPS_POLL = now + 12.0
        return disabled_obj

    ups_host = cfg.get("host", "127.0.0.1")
    ups_port = int(cfg.get("port", 3551))
    ups_mode = cfg.get("mode", "auto").lower()
    ups_name = cfg.get("ups_name", "ups")
    ups_user = cfg.get("username", "")
    ups_pass = cfg.get("password", "")

    protocol = None
    raw: Dict[str, str] = {}

    # 1. If configured for NUT mode or NUT port 3493
    if ups_mode in ("nut_client", "nut") or ups_port == 3493:
        raw = _query_nut_socket(ups_host, ups_port, ups_name=ups_name, username=ups_user, password=ups_pass)
        if raw:
            protocol = "nut_socket"
        elif ups_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != ups_host:
                raw = _query_nut_socket(gw, ups_port, ups_name=ups_name, username=ups_user, password=ups_pass)
                if raw:
                    protocol = "nut_socket"
        if not raw:
            raw = _query_nut_cli(ups_name)
            if raw:
                protocol = "upsc_cli"

    # 2. If configured for APCUPSD mode or port 3551
    elif ups_mode in ("apcupsd_client", "apcupsd") or ups_port == 3551:
        raw = _query_apcupsd_socket(ups_host, ups_port)
        if raw:
            protocol = "apcupsd_socket"
        elif ups_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != ups_host:
                raw = _query_apcupsd_socket(gw, ups_port)
                if raw:
                    protocol = "apcupsd_socket"
        if not raw:
            raw = _query_apcaccess_cli()
            if raw:
                protocol = "apcaccess_cli"

    # 3. Default / Auto Mode: Probe apcupsd first, then NUT, then CLI
    else:
        raw = _query_apcupsd_socket(ups_host, ups_port)
        if raw:
            protocol = "apcupsd_socket"
        elif ups_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != ups_host:
                raw = _query_apcupsd_socket(gw, ups_port)
                if raw:
                    protocol = "apcupsd_socket"

        if not raw:
            raw = _query_nut_socket(ups_host, 3493, ups_name=ups_name)
            if raw:
                protocol = "nut_socket"
            elif ups_host in ("127.0.0.1", "localhost"):
                gw = _get_docker_gateway()
                if gw and gw != ups_host:
                    raw = _query_nut_socket(gw, 3493, ups_name=ups_name)
                    if raw:
                        protocol = "nut_socket"

        if not raw:
            raw = _query_apcaccess_cli()
            if raw:
                protocol = "apcaccess_cli"
        if not raw:
            raw = _query_nut_cli(ups_name)
            if raw:
                protocol = "upsc_cli"

    if not raw:
        status_obj = {
            "available": False,
            "status": "Not Configured / Offline",
            "model": "N/A",
            "battery_charge_pct": None,
            "time_left_min": None,
            "load_pct": None,
            "line_volts": None,
            "battery_volts": None,
            "power_watts": None,
            "battery_temp_c": None,
            "line_freq_hz": None,
            "protocol": "offline",
            "mode": ups_mode,
            "active_policy": cfg.get("shutdown_policy", "runtime_left"),
            "failsafe_active": False,
        }
        _CACHED_UPS = status_obj
        _LAST_UPS_POLL = now + 12.0
        return status_obj

    def _extract_float(val: str):
        if not val:
            return None
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)", val)
        return float(m.group(1)) if m else None

    charge_pct = _extract_float(raw.get("BCHARGE", ""))
    time_left = _extract_float(raw.get("TIMELEFT", ""))
    load_pct = _extract_float(raw.get("LOADPCT", ""))
    line_v = _extract_float(raw.get("LINEV", ""))
    batt_v = _extract_float(raw.get("BATTV", ""))
    batt_temp = _extract_float(raw.get("ITEMP", ""))
    line_freq = _extract_float(raw.get("LINEFREQ", ""))

    nom_power = _extract_float(raw.get("NOMPOWER", ""))
    nominal_w = nom_power if nom_power is not None else 900.0
    power_watts = round((load_pct / 100.0) * nominal_w, 1) if load_pct is not None else None

    status_str = raw.get("STATUS", "ONLINE").strip().upper()
    is_on_batt = any(k in status_str for k in ("OB", "ONBATT", "ON BATT", "LB", "LOWBATT"))

    status_obj = {
        "available": True,
        "status": status_str,
        "model": raw.get("MODEL", raw.get("UPSNAME", "Generic UPS")),
        "battery_charge_pct": charge_pct,
        "time_left_min": time_left,
        "load_pct": load_pct,
        "line_volts": line_v,
        "battery_volts": batt_v,
        "battery_temp_c": batt_temp,
        "line_freq_hz": line_freq,
        "nominal_power_watts": nom_power,
        "power_watts": power_watts,
        "protocol": protocol or "unknown",
        "mode": ups_mode,
        "on_battery": is_on_batt,
        "active_policy": cfg.get("shutdown_policy", "runtime_left"),
        "policy_threshold_batt": cfg.get("battery_threshold_pct", 20),
        "policy_threshold_runtime": cfg.get("runtime_threshold_min", 5),
        "policy_threshold_timer": cfg.get("shutdown_timer_sec", 300),
    }

    _CACHED_UPS = status_obj
    _LAST_UPS_POLL = now
    return status_obj
