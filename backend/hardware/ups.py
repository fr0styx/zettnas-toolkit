"""
ZettNAS Toolkit - UPS & Power Integrity Telemetry Subsystem
Monitors battery health, load, runtime, and power status via apcupsd (port 3551 / apcaccess)
or Network UPS Tools (NUT).
"""

import os
import re
import socket
import subprocess
import time
from typing import Any, Dict

from backend.config import logger

_CACHED_UPS: Dict[str, Any] = {}
_LAST_UPS_POLL = 0.0
_UPS_CACHE_TTL = 3.0


def _get_docker_gateway() -> str | None:
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
                    # Validate that gw_ip belongs to standard Docker bridge space (172.16.0.0/12)
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
            # NIS status command: 2 bytes length (big endian) + "status"
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
    host: str = "127.0.0.1", port: int = 3493, timeout: float = 1.5, ups_name: str | None = None
) -> Dict[str, str]:
    """Queries Network UPS Tools (NUT) server natively over TCP port 3493 (zero subprocesses)."""
    out: Dict[str, str] = {}
    target_ups = ups_name or os.getenv("NUT_UPS_NAME", "")
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

            # If no UPS name provided, auto-discover first UPS via LIST UPS
            if not target_ups:
                s.sendall(b"LIST UPS\n")
                while True:
                    line = read_line()
                    if line is None or line.startswith("ERR") or line.startswith("END LIST UPS"):
                        break
                    # Line format: UPS <upsname> "<description>"
                    if line.startswith("UPS "):
                        parts = line.split()
                        if len(parts) >= 2:
                            target_ups = parts[1]
                            break
                # Drain remaining lines from LIST UPS
                while True:
                    line = read_line()
                    if line is None or line.startswith("END LIST UPS") or line.startswith("ERR"):
                        break

            if not target_ups:
                target_ups = "ups"

            # Query variables for the target UPS
            s.sendall(f"LIST VAR {target_ups}\n".encode("utf-8"))

            while True:
                line = read_line()
                if line is None or line.startswith("END LIST VAR") or line.startswith("ERR"):
                    break
                # Format: VAR <upsname> <varname> "<value>" or VAR <upsname> <varname> <value>
                if line.startswith(f"VAR {target_ups} "):
                    m = re.match(rf"^VAR\s+{re.escape(target_ups)}\s+(\S+)\s+(.*)$", line)
                    if m:
                        k_clean = m.group(1).strip()
                        v_clean = m.group(2).strip().strip('"')
                        if k_clean == "battery.charge":
                            out["BCHARGE"] = v_clean
                        elif k_clean == "battery.runtime":
                            try:
                                # Convert seconds to minutes
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

            if target_ups and "MODEL" not in out:
                out["UPSNAME"] = target_ups

            try:
                s.sendall(b"LOGOUT\n")
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[UPS] NUT socket check at {host}:{port} returned: {e}")
    return out


def _query_nut_cli() -> dict[str, str]:
    for bin_path in ("/usr/bin/upsc", "/bin/upsc", "upsc"):
        try:
            ups_name = os.getenv("NUT_UPS_NAME", "ups")
            r = subprocess.run([bin_path, ups_name], capture_output=True, text=True, timeout=2.5)
            if r.returncode == 0 and r.stdout:
                out = {}
                for line in r.stdout.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        # Map NUT keys to apcupsd equivalent keys
                        k_clean = k.strip()
                        v_clean = v.strip()
                        if k_clean == "battery.charge":
                            out["BCHARGE"] = v_clean
                        elif k_clean == "battery.runtime":
                            try:
                                # NUT returns runtime in seconds, convert to minutes
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
                return out
        except Exception:
            continue
    return {}


def read_ups_status(force: bool = False) -> Dict[str, Any]:
    global _CACHED_UPS, _LAST_UPS_POLL
    now = time.time()
    if not force and _CACHED_UPS and (now - _LAST_UPS_POLL) < _UPS_CACHE_TTL:
        return _CACHED_UPS

    ups_host = os.getenv("UPS_HOST", "127.0.0.1")
    ups_port = int(os.getenv("UPS_PORT", "3551"))
    nut_host = os.getenv("NUT_HOST", ups_host)
    nut_port = int(os.getenv("NUT_PORT", "3493"))
    ups_type = os.getenv("UPS_TYPE", "auto").lower()

    protocol = None
    raw: Dict[str, str] = {}

    # 1. If explicitly configured for NUT protocol or NUT port 3493
    if ups_type == "nut" or ups_port == 3493:
        raw = _query_nut_socket(nut_host, nut_port)
        if raw:
            protocol = "nut_socket"
        elif nut_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != nut_host:
                raw = _query_nut_socket(gw, nut_port)
                if raw:
                    protocol = "nut_socket"
        if not raw:
            raw = _query_nut_cli()
            if raw:
                protocol = "upsc_cli"
    else:
        # 2. Default: try apcupsd NIS socket first
        raw = _query_apcupsd_socket(ups_host, ups_port)
        if raw:
            protocol = "apcupsd_socket"
        elif ups_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != ups_host:
                raw = _query_apcupsd_socket(gw, ups_port)
                if raw:
                    protocol = "apcupsd_socket"

        # 3. If apcupsd offline, probe native NUT socket
        if not raw:
            raw = _query_nut_socket(nut_host, nut_port)
            if raw:
                protocol = "nut_socket"
            elif nut_host in ("127.0.0.1", "localhost"):
                gw = _get_docker_gateway()
                if gw and gw != nut_host:
                    raw = _query_nut_socket(gw, nut_port)
                    if raw:
                        protocol = "nut_socket"

        # 4. Fallback to CLI utilities
        if not raw:
            raw = _query_apcaccess_cli()
            if raw:
                protocol = "apcaccess_cli"
        if not raw:
            raw = _query_nut_cli()
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
            "protocol": "offline",
        }
        _CACHED_UPS = status_obj
        _LAST_UPS_POLL = now + 12.0  # Effective 15s cache when offline
        return status_obj

    # Extract parsed fields
    bcharge_raw = raw.get("BCHARGE", "")
    timeleft_raw = raw.get("TIMELEFT", "")
    load_raw = raw.get("LOADPCT", "")
    linev_raw = raw.get("LINEV", "")
    battv_raw = raw.get("BATTV", "")

    def _extract_float(val: str):
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)", val)
        return float(m.group(1)) if m else None

    status_str = raw.get("STATUS", "ONLINE").strip()
    status_obj = {
        "available": True,
        "status": status_str,
        "model": raw.get("MODEL", raw.get("UPSNAME", "Generic UPS")),
        "battery_charge_pct": _extract_float(bcharge_raw),
        "time_left_min": _extract_float(timeleft_raw),
        "load_pct": _extract_float(load_raw),
        "line_volts": _extract_float(linev_raw),
        "battery_volts": _extract_float(battv_raw),
        "protocol": protocol or "unknown",
    }

    _CACHED_UPS = status_obj
    _LAST_UPS_POLL = now
    return status_obj
