"""
ZettNAS Toolkit - Universal UPS & Power Integrity Telemetry Subsystem
Multi-protocol Hardware Abstraction Layer (HAL) supporting Network UPS Tools (NUT),
APCUPSD NIS protocol, direct USB HID discovery, and enterprise SNMP monitoring.
"""

import copy
import glob
import ipaddress
import os
import re
import socket
import subprocess
import time
from typing import Any, Optional

try:
    import fcntl
except ImportError:
    fcntl = None  # Non-Unix fallback

from backend.config import DATA_DIR, POOL_PATH, UPS_CONFIG_FILE, logger
from backend.db import log_ups_event
from backend.fsutil import SETTINGS_RECHECK_SECS, atomic_write_json, read_json, read_json_cached

# Host paths read here (module constants so tests can point them elsewhere)
PSY_ROOTS = ("/sys/class/power_supply", "/host/sys/class/power_supply")
HIDRAW_ROOTS = ("/sys/class/hidraw", "/host/sys/class/hidraw")
USB_DEVICE_ROOTS = ("/sys/bus/usb/devices", "/host/sys/bus/usb/devices")
DEV_ROOTS = ("/dev", "/host/dev")
PROC_NET_ROUTE = "/proc/net/route"

_CACHED_UPS: dict[str, Any] = {}
_LAST_UPS_POLL = 0.0
_UPS_CACHE_TTL = 10.0

# No UPS set up and none found (PERF-19): the next look is after 1, then 5, then every 15 minutes,
# instead of a full probe (USB, apcupsd, NUT, two CLIs, the config recovery tiers) every 10 s. A
# changed USB device list, the Power pane, or saving a config looks again at once. A UPS that was
# set up keeps the 10 s polling: an outage of its server must show quickly.
NOTHING_FOUND_BACKOFF_SECS = (60.0, 300.0, 900.0)
_NOTHING_FOUND: dict[str, Any] = {"until": 0.0, "step": 0, "usb": None}
_DEFAULT_CFG_MEMO: dict[str, Any] = {"until": 0.0, "cfg": None, "env": None}
# the environment variables the last recovery tier reads: a change recovers again
_UPS_ENV_KEYS = ("UPS_HOST", "UPS_PORT", "NUT_HOST", "NUT_PORT", "UPS_TYPE", "NUT_UPS_NAME")
# The hidraw UPS found by the last scan: node, device path, ids and parsed report descriptor
_HID_UPS_CACHE: dict[str, Any] = {}

DEFAULT_UPS_CONFIG: dict[str, Any] = {
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
    "04d8": "WalleCube / OpenUPS (Microchip)",
    "047c": "Dell",
    "0400": "National Semiconductor",
    "04b4": "Cypress (HID UPS)",
    "10af": "Trust",
    "0001": "Fry's / Generic HID",
    "0f03": "Unitek",
    "14b0": "SOCA",
    "03f0": "HP / Hewlett-Packard",
    "0592": "Powerware",
    "1d40": "Delta Energy Systems",
    "2e51": "Mustek",
    "048d": "ITE Tech",
}


def _detect_host_nut_config(custom_dirs: list[str] | None = None) -> dict[str, Any] | None:
    """Inspects host /etc/nut configuration files (ups.conf, upsmon.conf)
    and automatically extracts configured UPS names, hosts, and monitors.
    """
    nut_dirs = custom_dirs or ["/etc/nut", "/host/etc/nut"]
    ups_name = None
    host = "127.0.0.1"
    port = 3493
    user = ""
    password = ""

    for nd in nut_dirs:
        if not os.path.isdir(nd):
            continue
        ups_conf = os.path.join(nd, "ups.conf")
        if os.path.isfile(ups_conf):
            try:
                with open(ups_conf, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line_str = line.strip()
                        if line_str.startswith("[") and line_str.endswith("]"):
                            cand = line_str[1:-1].strip()
                            if cand and cand.lower() != "default":
                                ups_name = cand
                                break
            except Exception:
                logger.debug("backend.hardware.ups._detect_host_nut_config: ignored error", exc_info=True)

        upsmon_conf = os.path.join(nd, "upsmon.conf")
        if os.path.isfile(upsmon_conf):
            try:
                with open(upsmon_conf, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line_str = line.strip()
                        if line_str.startswith("MONITOR"):
                            parts = line_str.split()
                            if len(parts) >= 2:
                                sys_target = parts[1]
                                if "@" in sys_target:
                                    u_name, u_host = sys_target.split("@", 1)
                                    if u_name:
                                        ups_name = u_name
                                    if u_host:
                                        if ":" in u_host:
                                            h_part, p_part = u_host.split(":", 1)
                                            host = h_part
                                            try:
                                                port = int(p_part)
                                            except ValueError:
                                                pass
                                        else:
                                            host = u_host
                                if len(parts) >= 5:
                                    user = parts[3]
                                    password = parts[4]
                            break
            except Exception:
                logger.debug("backend.hardware.ups._detect_host_nut_config: ignored error", exc_info=True)

        if ups_name:
            return {
                "enabled": True,
                "mode": "nut_client",
                "host": host,
                "port": port,
                "ups_name": ups_name,
                "username": user,
                "password": password,
            }
    return None


def _usb_devices() -> tuple[str, ...]:
    """The USB device names the host lists (sysfs, no device I/O): a UPS plugged in changes it."""
    names: list[str] = []
    for root in USB_DEVICE_ROOTS:
        try:
            names += os.listdir(root)
        except OSError:
            continue
    return tuple(sorted(names))


def _ups_set_up() -> bool:
    """A UPS was set up: the saved config names a host or a mode."""
    stored = read_json_cached(UPS_CONFIG_FILE, None, max_age=SETTINGS_RECHECK_SECS)
    return isinstance(stored, dict) and bool(stored.get("host") or stored.get("mode"))


def _forget_nothing_found() -> None:
    _NOTHING_FOUND.update(until=0.0, step=0, usb=None)
    _DEFAULT_CFG_MEMO.update(until=0.0, cfg=None, env=None)


def load_ups_config() -> dict[str, Any]:
    """Loads persistent UPS configuration across multi-tier storage:
    1. Primary JSON state (UPS_CONFIG_FILE)
    2. SQLite WAL database app_config table
    3. Secondary backup JSON (ups_config.backup.json)
    4. Pool-level persistent mirror (POOL_PATH/.zettnas/ups_config.json)
    5. Host NUT auto-discovery (/etc/nut, /host/etc/nut)
    6. Environment variables fallback
    """
    cfg = dict(DEFAULT_UPS_CONFIG)
    # saves go through atomic_write_json, which refreshes the cached copy (PERF-5)
    stored = copy.deepcopy(read_json_cached(UPS_CONFIG_FILE, None, max_age=SETTINGS_RECHECK_SECS))

    recovered_from_backup = False

    # Tier 1: Primary JSON file
    if isinstance(stored, dict) and (stored.get("host") or stored.get("mode")):
        cfg.update(stored)
        return cfg

    # Nothing to recover the last time: the defaults again, without the database, the pool mirror
    # on the array and the host NUT search (PERF-19)
    env_now = tuple(os.getenv(k) or "" for k in _UPS_ENV_KEYS)
    memo = _DEFAULT_CFG_MEMO.get("cfg")
    if memo is not None and time.time() < _DEFAULT_CFG_MEMO["until"] and _DEFAULT_CFG_MEMO.get("env") == env_now:
        return copy.deepcopy(memo)

    # Tier 2: SQLite database
    try:
        from backend.db import get_app_config_value

        db_cfg = get_app_config_value("ups_config")
        if isinstance(db_cfg, dict) and (db_cfg.get("mode") or db_cfg.get("host") or db_cfg.get("ups_name")):
            cfg.update(db_cfg)
            recovered_from_backup = True
    except Exception as e:
        logger.debug(f"[UPS] Error querying db app_config: {e}")

    # Tier 3: Local backup file in DATA_DIR
    if not recovered_from_backup:
        backup_file = os.path.join(DATA_DIR, "ups_config.backup.json")
        b_stored = read_json(backup_file, None)
        if isinstance(b_stored, dict):
            cfg.update(b_stored)
            recovered_from_backup = True

    # Tier 4: Storage Pool Mirror (.zettnas)
    if not recovered_from_backup and POOL_PATH and os.path.isdir(POOL_PATH):
        pool_mirror = os.path.join(POOL_PATH, ".zettnas", "ups_config.json")
        p_stored = read_json(pool_mirror, None)
        if isinstance(p_stored, dict):
            cfg.update(p_stored)
            recovered_from_backup = True

    # Tier 5: Host NUT configuration auto-detection
    if not recovered_from_backup:
        host_nut = _detect_host_nut_config()
        if host_nut:
            cfg.update(host_nut)
            recovered_from_backup = True

    # Tier 6: Legacy environment variables fallback
    if not recovered_from_backup:
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

    # If recovered from an alternative tier, synchronize primary state file
    if recovered_from_backup:
        try:
            atomic_write_json(UPS_CONFIG_FILE, cfg)
            logger.info(
                f"[UPS] Successfully recovered persistent UPS config (mode: {cfg.get('mode')}, host: {cfg.get('host')})"
            )
        except Exception as e:
            logger.debug(f"[UPS] Could not write recovered config to file: {e}")
    else:
        _DEFAULT_CFG_MEMO.update(
            until=time.time() + NOTHING_FOUND_BACKOFF_SECS[-1], cfg=copy.deepcopy(cfg), env=env_now
        )

    return cfg


def mask_ups_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Masks secret passwords before returning over API."""
    out = dict(cfg)
    if out.get("password"):
        out["password"] = "********"
    return out


def save_ups_config(new_cfg: dict[str, Any]) -> dict[str, Any]:
    """Saves persistent UPS configuration safely across primary, database, and secondary backup tiers."""
    global _CACHED_UPS, _LAST_UPS_POLL
    current = load_ups_config()
    merged = dict(current)
    merged.update(new_cfg)

    # Protect masked password from being overwritten with mask placeholder
    if new_cfg.get("password") == "********":
        merged["password"] = current.get("password", "")

    # Ensure numeric types
    for int_key in (
        "port",
        "shutdown_timer_sec",
        "battery_threshold_pct",
        "runtime_threshold_min",
        "container_shutdown_timeout_sec",
    ):
        if int_key in merged and merged[int_key] is not None:
            try:
                merged[int_key] = int(merged[int_key])
            except (ValueError, TypeError):
                pass

    # Tier 1: Write primary file
    atomic_write_json(UPS_CONFIG_FILE, merged)

    # Tier 2: Write SQLite app_config
    try:
        from backend.db import set_app_config_value

        set_app_config_value("ups_config", merged)
    except Exception as e:
        logger.debug(f"[UPS] Error writing app_config to database: {e}")

    # Tier 3: Write backup file in DATA_DIR
    try:
        backup_file = os.path.join(DATA_DIR, "ups_config.backup.json")
        atomic_write_json(backup_file, merged)
    except Exception as e:
        logger.debug(f"[UPS] Error writing backup config file: {e}")

    # Tier 4: Write pool mirror (.zettnas)
    try:
        if POOL_PATH and os.path.isdir(POOL_PATH):
            pool_dir = os.path.join(POOL_PATH, ".zettnas")
            os.makedirs(pool_dir, exist_ok=True)
            pool_mirror = os.path.join(pool_dir, "ups_config.json")
            atomic_write_json(pool_mirror, merged)
    except Exception as e:
        logger.debug(f"[UPS] Error writing pool mirror: {e}")

    _forget_nothing_found()
    _CACHED_UPS = {}
    _LAST_UPS_POLL = 0.0
    return mask_ups_config(merged)


def _get_docker_gateway() -> str | None:
    """Detects Docker bridge gateway (which points to the host) if running in container.

    Strictly validates that the gateway belongs to a private Docker bridge subnet (172.16.0.0/12)
    to prevent probing local LAN router gateways when running in host networking mode.
    """
    try:
        with open(PROC_NET_ROUTE) as f:
            for line in f:
                fields = line.strip().split()
                if len(fields) >= 3 and (fields[1] == "00000000" or fields[1] == "0"):
                    gw_hex = fields[2]
                    gw_ip = socket.inet_ntoa(bytes.fromhex(gw_hex)[::-1])
                    parts = [int(p) for p in gw_ip.split(".")]
                    if len(parts) == 4 and parts[0] == 172 and 16 <= parts[1] <= 31:
                        return gw_ip
    except Exception:
        logger.debug("backend.hardware.ups._get_docker_gateway: ignored error", exc_info=True)
    return None


def _query_apcupsd_socket(host: str = "127.0.0.1", port: int = 3551, timeout: float = 1.0) -> dict[str, str]:
    """Queries apcupsd NIS server via 2-byte length prefixed NIS protocol."""
    out: dict[str, str] = {}
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


def _query_apcaccess_cli() -> dict[str, str]:
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
    ups_name: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, str]:
    """Queries Network UPS Tools (NUT) server natively over TCP port 3493 (zero subprocesses)."""
    out: dict[str, str] = {}
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
                s.sendall(f"USERNAME {username}\n".encode())
                read_line()
            if password:
                s.sendall(f"PASSWORD {password}\n".encode())
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

            s.sendall(f"LIST VAR {target_ups}\n".encode())

            first_line = read_line()
            if first_line and first_line.startswith("ERR UNKNOWN-UPS"):
                # Target UPS name was not recognized; discover available UPS names via LIST UPS
                s.sendall(b"LIST UPS\n")
                discovered_name = None
                while True:
                    line_ups = read_line()
                    if line_ups is None or line_ups.startswith("ERR") or line_ups.startswith("END LIST UPS"):
                        break
                    if line_ups.startswith("UPS "):
                        parts = line_ups.split()
                        if len(parts) >= 2:
                            discovered_name = parts[1]
                            break
                while True:
                    line_ups = read_line()
                    if line_ups is None or line_ups.startswith("END LIST UPS") or line_ups.startswith("ERR"):
                        break
                if discovered_name:
                    target_ups = discovered_name
                    s.sendall(f"LIST VAR {target_ups}\n".encode())
                    first_line = read_line()

            line = first_line
            while line is not None:
                if line.startswith("END LIST VAR") or line.startswith("ERR"):
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
                        elif k_clean in ("ups.load", "output.load", "output.power.percent", "ups.load.nominal"):
                            out["LOADPCT"] = v_clean
                        elif k_clean in ("input.voltage", "ups.input.voltage"):
                            out["LINEV"] = v_clean
                        elif k_clean in ("output.voltage", "ups.output.voltage", "ups.voltage"):
                            out["OUTV"] = v_clean
                        elif k_clean in ("output.voltage.nominal", "ups.voltage.nominal", "output.voltage.target"):
                            out.setdefault("NOMOUTV", v_clean)
                        elif k_clean in (
                            "output.current",
                            "ups.output.current",
                            "ups.current",
                            "output.current.nominal",
                        ):
                            out["OUTCURR"] = v_clean
                        elif k_clean in ("battery.current", "ups.battery.current"):
                            out.setdefault("BATTCURR", v_clean)
                        elif k_clean in ("output.realpower", "ups.realpower", "output.power.real", "ups.power.real"):
                            out["REALPOWER"] = v_clean
                        elif k_clean in ("output.power", "ups.power", "output.apparentpower", "ups.apparentpower"):
                            out["APPARENTPOWER"] = v_clean
                        elif k_clean == "battery.voltage":
                            out["BATTV"] = v_clean
                        elif k_clean == "ups.status":
                            out["STATUS"] = v_clean
                        elif k_clean in ("ups.model", "device.model"):
                            out.setdefault("MODEL", v_clean)
                        elif k_clean in ("ups.mfr", "device.mfr"):
                            out.setdefault("MFR", v_clean)
                        elif k_clean in (
                            "ups.realpower.nominal",
                            "ups.power.nominal",
                            "output.realpower.nominal",
                            "output.power.nominal",
                        ):
                            out["NOMPOWER"] = v_clean
                        elif k_clean in ("battery.temperature", "ups.temperature"):
                            out["ITEMP"] = v_clean
                        elif k_clean in ("input.frequency", "ups.input.frequency"):
                            out["LINEFREQ"] = v_clean
                line = read_line()

            if target_ups and "MODEL" not in out:
                out["UPSNAME"] = target_ups

            try:
                s.sendall(b"LOGOUT\n")
            except Exception:
                logger.debug("backend.hardware.ups._query_nut_socket: ignored error", exc_info=True)
    except Exception as e:
        logger.debug(f"[UPS] NUT socket check at {host}:{port} returned: {e}")
    return out


def _query_nut_cli(ups_name: str = "ups") -> dict[str, str]:
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
                        elif k_clean in ("ups.load", "output.load", "output.power.percent", "ups.load.nominal"):
                            out["LOADPCT"] = v_clean
                        elif k_clean in ("input.voltage", "ups.input.voltage"):
                            out["LINEV"] = v_clean
                        elif k_clean in ("output.voltage", "ups.output.voltage", "ups.voltage"):
                            out["OUTV"] = v_clean
                        elif k_clean in ("output.voltage.nominal", "ups.voltage.nominal", "output.voltage.target"):
                            out.setdefault("NOMOUTV", v_clean)
                        elif k_clean in ("output.current", "ups.current", "output.current.nominal"):
                            out["OUTCURR"] = v_clean
                        elif k_clean in ("battery.current", "ups.battery.current"):
                            out.setdefault("BATTCURR", v_clean)
                        elif k_clean in ("output.realpower", "ups.realpower", "output.power.real", "ups.power.real"):
                            out["REALPOWER"] = v_clean
                        elif k_clean in ("output.power", "ups.power", "output.apparentpower", "ups.apparentpower"):
                            out["APPARENTPOWER"] = v_clean
                        elif k_clean == "battery.voltage":
                            out["BATTV"] = v_clean
                        elif k_clean == "ups.status":
                            out["STATUS"] = v_clean
                        elif k_clean in ("ups.model", "device.model"):
                            out["MODEL"] = v_clean
                        elif k_clean in ("ups.mfr", "device.mfr"):
                            out["MFR"] = v_clean
                        elif k_clean in (
                            "ups.realpower.nominal",
                            "ups.power.nominal",
                            "output.realpower.nominal",
                            "output.power.nominal",
                        ):
                            out["NOMPOWER"] = v_clean
                        elif k_clean in ("battery.temperature", "ups.temperature"):
                            out["ITEMP"] = v_clean
                        elif k_clean in ("input.frequency", "ups.input.frequency"):
                            out["LINEFREQ"] = v_clean
                return out
        except Exception:
            continue
    return {}


def _parse_hid_report_descriptor(desc_bytes: bytes) -> dict[tuple[int, int], tuple[int, int, int]]:
    """
    Parses binary USB HID report descriptor into a mapping of (usage_page, usage) -> (report_id, report_size, report_count).
    Supports all standard HID Power Device (0x84) and Battery System (0x85) items.
    """
    pos = 0
    usage_page = 0
    report_id = 0
    report_size = 8
    report_count = 1
    usages: list[tuple[int, int]] = []
    mapping: dict[tuple[int, int], tuple[int, int, int]] = {}

    while pos < len(desc_bytes):
        b = desc_bytes[pos]
        pos += 1
        if b == 0xFE:  # Long item escape
            size = desc_bytes[pos]
            pos += 1 + 2 + size
            continue
        size = b & 0x03
        if size == 3:
            size = 4
        typ = (b >> 2) & 0x03
        tag = (b >> 4) & 0x0F
        val = 0
        if size > 0 and pos + size <= len(desc_bytes):
            val = int.from_bytes(desc_bytes[pos : pos + size], "little", signed=False)
            pos += size

        if typ == 1:  # Global item
            if tag == 0x00:
                usage_page = val
            elif tag == 0x08:
                report_id = val
            elif tag == 0x07:
                report_size = val
            elif tag == 0x09:
                report_count = val
        elif typ == 2:  # Local item
            if tag == 0x00:
                usages.append((usage_page, val))
        elif typ == 0:  # Main item
            if tag in (0x08, 0x09, 0x0B):  # Input, Output, Feature
                for up, u in usages:
                    key = (up, u)
                    if key not in mapping:
                        mapping[key] = (report_id, report_size, report_count)
                usages = []
    return mapping


def _read_hid_reports(fd: int, mapping: dict, vid: str, pid: str, hid_name: str) -> dict[str, Any]:
    """Reads the UPS values from an open hidraw device using its parsed report descriptor."""
    out: dict[str, Any] = {}
    reports_cache: dict[int, bytearray | None] = {}

    def _get_feature_report(rid: int) -> bytearray | None:
        if rid not in reports_cache:
            buf = bytearray(64)
            buf[0] = rid
            try:
                # _IOC(3, ord('H'), 0x07, 64) = 0xc0404807
                if fcntl is None:  # not on Linux: no USB HID reports
                    return None
                fcntl.ioctl(fd, 0xC0404807, buf)
                reports_cache[rid] = buf
            except Exception:
                reports_cache[rid] = None
        return reports_cache[rid]

    # 1. RemainingCapacity (0x85, 0x66)
    if (0x85, 0x66) in mapping:
        rid, _, _ = mapping[(0x85, 0x66)]
        rep = _get_feature_report(rid)
        if rep and len(rep) > 1:
            out["BCHARGE"] = str(rep[1])

    # 2. RunTimeToEmpty (0x85, 0x68)
    if (0x85, 0x68) in mapping:
        rid, _, _ = mapping[(0x85, 0x68)]
        rep = _get_feature_report(rid)
        if rep and len(rep) >= 4:
            val_sec = int.from_bytes(rep[2:4], "little")
            if val_sec > 0:
                out["TIMELEFT"] = str(round(val_sec / 60.0, 1))

    # 3. Voltage: Input or Config (0x84, 0x57), (0x84, 0x30), (0x84, 0x04)
    for v_key in [(0x84, 0x57), (0x84, 0x30), (0x84, 0x04)]:
        if v_key in mapping:
            rid, _, _ = mapping[v_key]
            rep = _get_feature_report(rid)
            if rep and len(rep) >= 3:
                val = int.from_bytes(rep[1:3], "little")
                if 80 <= val <= 260:
                    out["LINEV"] = str(val)
                    break
                elif 800 <= val <= 2600:
                    out["LINEV"] = str(round(val / 10.0, 1))
                    break

    # 4. PercentLoad (0x84, 0x24)
    if (0x84, 0x24) in mapping:
        rid, _, _ = mapping[(0x84, 0x24)]
        rep = _get_feature_report(rid)
        if rep and len(rep) > 1 and rep[1] <= 100:
            out["LOADPCT"] = str(rep[1])

    # 5. Output / Battery Current (0x84, 0x58), (0x85, 0x58), (0x85, 0x45)
    for c_key in [(0x84, 0x58), (0x85, 0x58), (0x85, 0x45)]:
        if c_key in mapping:
            rid, _, _ = mapping[c_key]
            rep = _get_feature_report(rid)
            if rep and len(rep) >= 3:
                val_raw = int.from_bytes(rep[1:3], "little")
                if val_raw > 0:
                    out["OUTCURR"] = str(round(val_raw / 1000.0, 2)) if val_raw > 50 else str(val_raw)
                    break

    # 6. Status: ACPresent (0x84, 0xd0) or Discharging (0x84, 0xd2)
    status_parts = []
    is_ac = True
    if (0x84, 0xD0) in mapping:
        rid, _, _ = mapping[(0x84, 0xD0)]
        rep = _get_feature_report(rid)
        if rep and len(rep) > 1:
            is_ac = bool(rep[1])

    if (0x84, 0xD2) in mapping:
        rid, _, _ = mapping[(0x84, 0xD2)]
        rep = _get_feature_report(rid)
        if rep and len(rep) > 1 and rep[1]:
            status_parts.append("OB")
            is_ac = False

    if (0x84, 0xD1) in mapping:
        rid, _, _ = mapping[(0x84, 0xD1)]
        rep = _get_feature_report(rid)
        if rep and len(rep) > 1 and rep[1]:
            status_parts.append("CHRG")

    if is_ac and "OB" not in status_parts:
        status_parts.insert(0, "ONLINE")
    elif not is_ac and "OB" not in status_parts:
        status_parts.insert(0, "ONBATT")

    out["STATUS"] = " ".join(status_parts) if status_parts else "ONLINE"
    out["MODEL"] = hid_name or KNOWN_UPS_VENDORS.get(vid, "USB HID UPS")
    out["MFR"] = KNOWN_UPS_VENDORS.get(vid, "Generic USB")
    out["PROTOCOL"] = "direct_usb_hid"
    out["VENDOR_ID"] = vid
    out["PRODUCT_ID"] = pid
    return out


def _cached_hid_ups() -> dict[str, Any] | None:
    """Reads the UPS found by the last scan without listing devices or parsing its descriptor again."""
    c = _HID_UPS_CACHE
    if not c or fcntl is None or not os.path.exists(c["char"]) or not os.path.isdir(c["node_dir"]):
        _HID_UPS_CACHE.clear()
        return None
    try:
        fd = os.open(c["char"], os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        _HID_UPS_CACHE.clear()
        return None
    try:
        out = _read_hid_reports(fd, c["mapping"], c["vid"], c["pid"], c["name"])
    finally:
        os.close(fd)
    return out if out.get("STATUS") else None


def _query_direct_usb(target_device: str | None = None) -> dict[str, Any]:
    """
    Directly queries local USB HID Power Devices via sysfs and /dev/hidraw ioctl.
    Supports WalleCube (04d8:d005 / OpenUPS), APC, CyberPower, Eaton, and standard USB HID UPS units.
    Does not require external daemons (apcupsd/nut) or third-party pip libraries.
    """
    out: dict[str, Any] = {}

    # Layer 1: Check Linux sysfs power_supply class (e.g. /sys/class/power_supply/* or /host/sys/class/power_supply/*)
    psy_roots = [p for p in PSY_ROOTS if os.path.isdir(p)]
    for root in psy_roots:
        try:
            for node in sorted(os.listdir(root)):
                node_dir = os.path.join(root, node)
                if not os.path.isdir(node_dir):
                    continue
                type_file = os.path.join(node_dir, "type")
                psy_type = ""
                if os.path.isfile(type_file):
                    with open(type_file) as f:
                        psy_type = f.read().strip().upper()
                if psy_type in ("UPS", "BATTERY") or "ups" in node.lower() or "battery" in node.lower():

                    def _read_attr(name: str) -> str | None:
                        fp = os.path.join(node_dir, name)  # noqa: B023
                        if os.path.isfile(fp):
                            try:
                                with open(fp) as f:
                                    return f.read().strip()
                            except Exception:
                                logger.debug(
                                    "backend.hardware.ups._query_direct_usb._read_attr: ignored error", exc_info=True
                                )
                        return None

                    cap = _read_attr("capacity")
                    status = _read_attr("status")
                    online = _read_attr("online")
                    v_now = _read_attr("voltage_now")
                    curr_now = _read_attr("current_now")
                    p_now = _read_attr("power_now")
                    mfr = _read_attr("manufacturer")
                    model = _read_attr("model_name")
                    time_left = _read_attr("time_to_empty_now")

                    if cap or status or v_now or curr_now or p_now:
                        if cap and cap.isdigit():
                            out["BCHARGE"] = cap
                        if status:
                            s_up = status.upper()
                            if "DISCHARG" in s_up:
                                out["STATUS"] = "OB"
                            elif "CHARG" in s_up:
                                out["STATUS"] = "ONLINE CHRG"
                            else:
                                out["STATUS"] = "ONLINE"
                        elif online is not None:
                            out["STATUS"] = "ONLINE" if online == "1" else "OB"
                        if v_now and v_now.isdigit():
                            volts = float(v_now) / 1_000_000.0
                            if volts > 1.0:
                                out["BATTV"] = str(round(volts, 1))
                                out.setdefault("OUTV", str(round(volts, 1)))
                        if curr_now and curr_now.lstrip("-").isdigit():
                            amps = abs(float(curr_now)) / 1_000_000.0
                            if amps > 0:
                                out["OUTCURR"] = str(round(amps, 2))
                        if p_now and p_now.lstrip("-").isdigit():
                            watts = abs(float(p_now)) / 1_000_000.0
                            if watts > 0:
                                out["REALPOWER"] = str(round(watts, 1))
                        if time_left and time_left.isdigit():
                            out["TIMELEFT"] = str(round(float(time_left) / 60.0, 1))
                        if model:
                            out["MODEL"] = model
                        if mfr:
                            out["MFR"] = mfr
                        out["PROTOCOL"] = "direct_usb_sysfs"
                        return out
        except Exception as e:
            logger.debug(f"[Direct USB] sysfs power_supply scan error: {e}")

    # Layer 2: Direct HIDRAW Query via fcntl ioctl (the device found last time first, PERF-1)
    cached = _cached_hid_ups()
    if cached:
        return cached
    hidraw_roots = [p for p in HIDRAW_ROOTS if os.path.isdir(p)]
    permission_error_info = None

    if fcntl is not None:
        for root in hidraw_roots:
            try:
                for node in sorted(os.listdir(root)):
                    node_dir = os.path.join(root, node)
                    uevent_file = os.path.join(node_dir, "device/uevent")
                    if not os.path.isfile(uevent_file):
                        continue

                    vid, pid, hid_name = "", "", ""
                    with open(uevent_file) as f:
                        for line in f:
                            if line.startswith("HID_ID="):
                                parts = line.strip().split("=")[1].split(":")
                                if len(parts) >= 3:
                                    vid = parts[1].lstrip("0").lower().zfill(4)
                                    pid = parts[2].lstrip("0").lower().zfill(4)
                            elif line.startswith("HID_NAME="):
                                hid_name = line.strip().split("=", 1)[1].strip()

                    is_ups = vid in KNOWN_UPS_VENDORS or any(
                        k in hid_name.lower()
                        for k in (
                            "ups",
                            "power",
                            "battery",
                            "wallecube",
                            "open",
                            "apc",
                            "cyberpower",
                            "eaton",
                            "tripp",
                        )
                    )
                    if not is_ups:
                        continue

                    char_cands = [os.path.join(d, node) for d in DEV_ROOTS]
                    desc_file = os.path.join(node_dir, "device/report_descriptor")
                    if not os.path.isfile(desc_file):
                        continue

                    fd = None
                    for c_path in char_cands:
                        if os.path.exists(c_path):
                            try:
                                fd = os.open(c_path, os.O_RDWR | os.O_NONBLOCK)
                                break
                            except PermissionError:
                                permission_error_info = {
                                    "MODEL": hid_name or KNOWN_UPS_VENDORS.get(vid, "USB UPS"),
                                    "MFR": KNOWN_UPS_VENDORS.get(vid, "USB Power Device"),
                                    "STATUS": "PERMISSION_REQUIRED",
                                    "PROTOCOL": "direct_usb_hid",
                                    "PERMISSION_ERROR": True,
                                    "ERROR": (
                                        f"Docker lacks permission to open {c_path}. "
                                        "Add device_cgroup_rules for hidraw or run with privileged: true."
                                    ),
                                    "VENDOR_ID": vid,
                                    "PRODUCT_ID": pid,
                                }
                            except OSError:
                                pass

                    if fd is not None:
                        try:
                            with open(desc_file, "rb") as df:
                                desc_data = df.read()
                            mapping = _parse_hid_report_descriptor(desc_data)
                            out.update(_read_hid_reports(fd, mapping, vid, pid, hid_name))
                            _HID_UPS_CACHE.update(
                                node_dir=node_dir, char=c_path, vid=vid, pid=pid, name=hid_name, mapping=mapping
                            )
                            return out
                        finally:
                            os.close(fd)
            except Exception as e:
                logger.debug(f"[Direct USB] hidraw scan error: {e}")

    # If hidraw was discovered but access was blocked by cgroup permissions
    if permission_error_info:
        return permission_error_info

    # Layer 3: Scan /sys/bus/usb/devices/ to detect connected USB UPS device metadata
    usb_roots = [p for p in USB_DEVICE_ROOTS if os.path.isdir(p)]
    for u_root in usb_roots:
        try:
            for d in sorted(os.listdir(u_root)):
                d_path = os.path.join(u_root, d)
                v_f = os.path.join(d_path, "idVendor")
                p_f = os.path.join(d_path, "idProduct")
                if os.path.isfile(v_f) and os.path.isfile(p_f):
                    with open(v_f) as f:
                        vid = f.read().strip().lower()
                    with open(p_f) as f:
                        pid = f.read().strip().lower()
                    prod, mfr = "", ""
                    if os.path.isfile(os.path.join(d_path, "product")):
                        with open(os.path.join(d_path, "product")) as f:
                            prod = f.read().strip()
                    if os.path.isfile(os.path.join(d_path, "manufacturer")):
                        with open(os.path.join(d_path, "manufacturer")) as f:
                            mfr = f.read().strip()

                    is_ups = (
                        vid in KNOWN_UPS_VENDORS
                        or "ups" in prod.lower()
                        or "power" in prod.lower()
                        or "battery" in prod.lower()
                        or "wallecube" in mfr.lower()
                    )
                    if is_ups:
                        vendor_name = KNOWN_UPS_VENDORS.get(vid, mfr or "Generic USB")
                        model_name = prod or f"{vendor_name} UPS"
                        return {
                            "MODEL": model_name,
                            "MFR": mfr or vendor_name,
                            "STATUS": "ACTION_REQUIRED",
                            "PROTOCOL": "direct_usb_sysfs",
                            "PERMISSION_ERROR": True,
                            "ERROR": (
                                f"Direct USB device detected ({model_name}), but Docker lacks permission to open character device. "
                                "Add device_cgroup_rules for hidraw or privileged: true in container configuration."
                            ),
                            "VENDOR_ID": vid,
                            "PRODUCT_ID": pid,
                        }
        except Exception as e:
            logger.debug(f"[Direct USB] sysfs usb scan error: {e}")

    return out


def discover_ups_sources() -> list[dict[str, Any]]:
    """Auto-discovers locally connected USB HID UPS devices and active LAN power daemons."""
    candidates: list[dict[str, Any]] = []

    # 1. Probe USB HID devices in sysfs (both container and host mounts)
    usb_devices = [d for root in USB_DEVICE_ROOTS for d in sorted(glob.glob(os.path.join(root, "*")))]
    seen_ids: set[str] = set()

    for dev_path in usb_devices:
        try:
            vendor_file = os.path.join(dev_path, "idVendor")
            product_file = os.path.join(dev_path, "idProduct")
            if os.path.isfile(vendor_file) and os.path.isfile(product_file):
                with open(vendor_file) as f:
                    vid = f.read().strip().lower()
                with open(product_file) as f:
                    pid = f.read().strip().lower()

                dev_key = f"{vid}:{pid}"
                if dev_key in seen_ids:
                    continue

                mfr = ""
                mfr_file = os.path.join(dev_path, "manufacturer")
                if os.path.isfile(mfr_file):
                    with open(mfr_file) as f:
                        mfr = f.read().strip()

                prod_name = ""
                prod_file = os.path.join(dev_path, "product")
                if os.path.isfile(prod_file):
                    with open(prod_file) as f:
                        prod_name = f.read().strip()

                is_ups_vendor = vid in KNOWN_UPS_VENDORS
                is_ups_prod = any(
                    k in prod_name.lower() or k in mfr.lower() for k in ("ups", "power", "battery", "wallecube", "open")
                )

                if is_ups_vendor or is_ups_prod:
                    seen_ids.add(dev_key)
                    vendor_title = KNOWN_UPS_VENDORS.get(vid, mfr or "Generic USB")
                    model_title = prod_name or vendor_title
                    candidates.append(
                        {
                            "type": "usb_hid",
                            "mode": "usb_hid",
                            "title": f"{vendor_title} ({model_title})",
                            "label": f"{vendor_title} ({model_title})",
                            "vendor_id": vid,
                            "product_id": pid,
                            "model": model_title,
                            "host": "",
                            "port": None,
                            "description": f"Direct USB Device ({vid}:{pid})",
                            "is_usb": True,
                        }
                    )
        except Exception:
            continue

    # 2. Check /sys/class/power_supply devices
    psy_paths = [d for root in PSY_ROOTS for d in sorted(glob.glob(os.path.join(root, "*")))]
    for p_dir in psy_paths:
        try:
            bname = os.path.basename(p_dir)
            t_file = os.path.join(p_dir, "type")
            psy_type = ""
            if os.path.isfile(t_file):
                with open(t_file) as f:
                    psy_type = f.read().strip().upper()
            if (psy_type in ("UPS", "BATTERY") or "ups" in bname.lower()) and not any(
                c.get("is_usb") for c in candidates
            ):
                candidates.append(
                    {
                        "type": "usb_hid",
                        "mode": "usb_hid",
                        "title": f"Linux Power Supply ({bname})",
                        "label": f"Linux Power Supply ({bname})",
                        "model": bname,
                        "host": "",
                        "port": None,
                        "description": f"Detected sysfs power supply node {bname}",
                        "is_usb": True,
                    }
                )
        except Exception:
            continue

    # 3. Check /dev/usb/hiddev* devices
    hiddev_nodes = glob.glob("/dev/usb/hiddev*") + glob.glob("/host/dev/usb/hiddev*")
    if hiddev_nodes and not candidates:
        candidates.append(
            {
                "type": "usb_hid",
                "mode": "usb_hid",
                "title": f"USB HID Power Device ({os.path.basename(hiddev_nodes[0])})",
                "label": f"USB HID Power Device ({os.path.basename(hiddev_nodes[0])})",
                "model": "Generic USB HID UPS",
                "host": "",
                "port": None,
                "description": f"Detected character node {hiddev_nodes[0]}",
                "is_usb": True,
            }
        )

    # 4. Probe LAN / Host apcupsd and NUT daemons
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
            candidates.append(
                {
                    "type": "apcupsd_client",
                    "mode": "apcupsd_client",
                    "title": f"APCUPSD Server @ {h}:3551",
                    "label": f"APCUPSD Server @ {h}:3551",
                    "model": model,
                    "host": h,
                    "port": 3551,
                    "status": status,
                    "charge": apc_raw.get("BCHARGE"),
                    "description": f"Active APC daemon on {h}:3551 ({status})",
                    "is_usb": False,
                }
            )

        # Check NUT port 3493
        nut_raw = _query_nut_socket(h, 3493, timeout=0.8)
        if nut_raw:
            model = nut_raw.get("MODEL", nut_raw.get("UPSNAME", "NUT UPS"))
            status = nut_raw.get("STATUS", "ONLINE")
            candidates.append(
                {
                    "type": "nut_client",
                    "mode": "nut_client",
                    "title": f"Network UPS Tools (NUT) @ {h}:3493",
                    "label": f"Network UPS Tools (NUT) @ {h}:3493",
                    "model": model,
                    "host": h,
                    "port": 3493,
                    "ups_name": nut_raw.get("UPSNAME", "ups"),
                    "status": status,
                    "charge": nut_raw.get("BCHARGE"),
                    "description": f"Active NUT daemon on {h}:3493 ({status})",
                    "is_usb": False,
                }
            )

    return candidates


def test_ups_connection(
    host: str = "127.0.0.1",
    port: int = 3551,
    mode: str = "auto",
    ups_name: str = "",
    username: str = "",
    password: str = "",
) -> dict[str, Any]:
    """Tests connection to a UPS daemon or Direct USB without modifying persistent configuration."""
    clean_mode = (mode or "auto").lower()

    if clean_mode in ("usb_hid", "usb"):
        raw = _query_direct_usb()
        if raw:
            if raw.get("PERMISSION_ERROR"):
                return {
                    "success": False,
                    "connected": False,
                    "error": raw.get(
                        "ERROR",
                        "Docker lacks permission to open /dev/hidraw. Add device_cgroup_rules or privileged: true.",
                    ),
                    "model": raw.get("MODEL", "USB UPS"),
                }
            bcharge_str = raw.get("BCHARGE", "")
            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", bcharge_str)
            bcharge = float(m.group(1)) if m else None
            return {
                "success": True,
                "connected": True,
                "model": raw.get("MODEL", "USB HID UPS"),
                "status": raw.get("STATUS", "ONLINE"),
                "battery_charge_pct": bcharge,
                "raw_keys": list(raw.keys()),
            }
        return {
            "success": False,
            "connected": False,
            "error": "No USB UPS device detected on local USB bus. Ensure the USB data cable is securely connected to the host.",
        }

    clean_host = (host or "127.0.0.1").strip()
    try:
        ip = ipaddress.ip_address(clean_host)
        if ip.is_link_local:
            return {
                "success": False,
                "connected": False,
                "error": "Probing link-local or cloud metadata addresses is forbidden.",
            }
    except ValueError:
        if clean_host.lower() in ("metadata.google.internal",):
            return {
                "success": False,
                "connected": False,
                "error": "Probing link-local or cloud metadata addresses is forbidden.",
            }
        try:
            for info in socket.getaddrinfo(clean_host, None):
                if ipaddress.ip_address(info[4][0]).is_link_local:
                    return {
                        "success": False,
                        "connected": False,
                        "error": "Probing link-local or cloud metadata addresses is forbidden.",
                    }
        except Exception:
            logger.debug("backend.hardware.ups.test_ups_connection: ignored error", exc_info=True)

    try:
        clean_port = int(port or 3551)
    except (ValueError, TypeError):
        clean_port = 3551
    if clean_port <= 0:
        clean_port = 3493 if clean_mode in ("nut_client", "nut") else 3551

    raw: dict[str, str] = {}

    if clean_mode in ("nut_client", "nut") or clean_port == 3493:
        raw = _query_nut_socket(
            clean_host, clean_port, timeout=2.0, ups_name=ups_name, username=username, password=password
        )
        if not raw and clean_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != clean_host:
                raw = _query_nut_socket(
                    gw, clean_port, timeout=2.0, ups_name=ups_name, username=username, password=password
                )
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
            "connected": True,
            "model": raw.get("MODEL", raw.get("UPSNAME", "Generic UPS")),
            "status": raw.get("STATUS", "ONLINE"),
            "battery_charge_pct": bcharge,
            "raw_keys": list(raw.keys()),
        }
    return {
        "success": False,
        "connected": False,
        "error": f"Unable to reach UPS daemon at {clean_host}:{clean_port}. Ensure service is running and accessible.",
    }


def run_ups_self_test() -> dict[str, Any]:
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
                    s.sendall(f"USERNAME {cfg['username']}\n".encode())
                    s.recv(1024)
                if cfg.get("password"):
                    s.sendall(f"PASSWORD {cfg['password']}\n".encode())
                    s.recv(1024)
                s.sendall(f"INSTCMD {ups_name} test.battery.start.quick\n".encode())
                resp = s.recv(1024).decode("utf-8", errors="replace")
                if "OK" in resp:
                    test_executed = True
                    result_msg = "NUT quick battery self-test accepted."
                else:
                    s.sendall(f"INSTCMD {ups_name} test.battery.start\n".encode())
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
                r = subprocess.run(
                    [
                        bin_path,
                        "-u",
                        cfg.get("username", "monuser"),
                        "-p",
                        cfg.get("password", ""),
                        f"{ups_name}@{host}",
                        "test.battery.start.quick",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                )
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


def read_ups_status(force: bool = False, reprobe: bool = False) -> dict[str, Any]:
    """Reads enriched real-time UPS telemetry across configured protocols. With no UPS set up and
    none found, it looks again only on the back-off schedule (PERF-19); `reprobe` (the Power pane)
    looks at the usual 10 s pace, `force` at once."""
    global _CACHED_UPS, _LAST_UPS_POLL
    now = time.time()
    if not force and _CACHED_UPS and (now - _LAST_UPS_POLL) < _UPS_CACHE_TTL:
        return _CACHED_UPS
    if (
        not force
        and not reprobe
        and _CACHED_UPS.get("protocol") == "offline"
        and now < _NOTHING_FOUND["until"]
        and _usb_devices() == _NOTHING_FOUND["usb"]
    ):
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
        _LAST_UPS_POLL = now
        return disabled_obj

    ups_host = cfg.get("host", "127.0.0.1")
    raw_port = cfg.get("port")
    try:
        ups_port = int(raw_port) if raw_port is not None else 3551
    except (ValueError, TypeError):
        ups_port = 3551
    ups_mode = cfg.get("mode", "auto").lower()
    ups_name = cfg.get("ups_name", "ups")
    ups_user = cfg.get("username", "")
    ups_pass = cfg.get("password", "")

    protocol = None
    raw: dict[str, Any] = {}

    # 0. If configured for Direct USB mode (usb_hid)
    if ups_mode in ("usb_hid", "usb"):
        raw = _query_direct_usb()
        if raw:
            protocol = raw.get("PROTOCOL", "direct_usb_hid")

    # 1. If configured for NUT mode or NUT port 3493
    elif ups_mode in ("nut_client", "nut") or ups_port == 3493:
        target_port = ups_port if ups_port > 0 else 3493
        raw = _query_nut_socket(ups_host, target_port, ups_name=ups_name, username=ups_user, password=ups_pass)
        if raw:
            protocol = "nut_socket"
        elif ups_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != ups_host:
                raw = _query_nut_socket(gw, target_port, ups_name=ups_name, username=ups_user, password=ups_pass)
                if raw:
                    protocol = "nut_socket"
        if not raw:
            raw = _query_nut_cli(ups_name)
            if raw:
                protocol = "upsc_cli"

    # 2. If configured for APCUPSD mode or port 3551
    elif ups_mode in ("apcupsd_client", "apcupsd") or ups_port == 3551:
        target_port = ups_port if ups_port > 0 else 3551
        raw = _query_apcupsd_socket(ups_host, target_port)
        if raw:
            protocol = "apcupsd_socket"
        elif ups_host in ("127.0.0.1", "localhost"):
            gw = _get_docker_gateway()
            if gw and gw != ups_host:
                raw = _query_apcupsd_socket(gw, target_port)
                if raw:
                    protocol = "apcupsd_socket"
        if not raw:
            raw = _query_apcaccess_cli()
            if raw:
                protocol = "apcaccess_cli"

    # 3. Default / Auto Mode: Probe direct USB first, then apcupsd, then NUT, then CLI
    else:
        raw = _query_direct_usb()
        if raw and not raw.get("PERMISSION_ERROR"):
            protocol = raw.get("PROTOCOL", "direct_usb_hid")

        if not raw:
            target_apc_port = ups_port if ups_port > 0 else 3551
            raw = _query_apcupsd_socket(ups_host, target_apc_port)
            if raw:
                protocol = "apcupsd_socket"
            elif ups_host in ("127.0.0.1", "localhost"):
                gw = _get_docker_gateway()
                if gw and gw != ups_host:
                    raw = _query_apcupsd_socket(gw, target_apc_port)
                    if raw:
                        protocol = "apcupsd_socket"

        if not raw:
            target_nut_port = ups_port if (ups_port > 0 and ups_port != 3551) else 3493
            raw = _query_nut_socket(ups_host, target_nut_port, ups_name=ups_name)
            if raw:
                protocol = "nut_socket"
            elif ups_host in ("127.0.0.1", "localhost"):
                gw = _get_docker_gateway()
                if gw and gw != ups_host:
                    raw = _query_nut_socket(gw, target_nut_port, ups_name=ups_name)
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
        _LAST_UPS_POLL = now
        if _ups_set_up():
            _NOTHING_FOUND.update(until=0.0, step=0, usb=None)
        else:
            step = int(_NOTHING_FOUND["step"])
            delay = NOTHING_FOUND_BACKOFF_SECS[min(step, len(NOTHING_FOUND_BACKOFF_SECS) - 1)]
            _NOTHING_FOUND.update(until=now + delay, step=step + 1, usb=_usb_devices())
        return status_obj
    _NOTHING_FOUND.update(until=0.0, step=0, usb=None)

    if raw.get("PERMISSION_ERROR"):
        status_obj = {
            "available": True,
            "status": "Permission Required",
            "model": raw.get("MODEL", "USB UPS"),
            "battery_charge_pct": None,
            "time_left_min": None,
            "load_pct": None,
            "line_volts": None,
            "output_volts": None,
            "output_amps": None,
            "battery_volts": None,
            "power_watts": None,
            "battery_temp_c": None,
            "line_freq_hz": None,
            "protocol": protocol or "direct_usb",
            "mode": ups_mode,
            "on_battery": False,
            "permission_error": True,
            "permission_detail": raw.get("ERROR"),
            "active_policy": cfg.get("shutdown_policy", "runtime_left"),
            "failsafe_active": False,
        }
        _CACHED_UPS = status_obj
        _LAST_UPS_POLL = now
        return status_obj

    def _extract_float(val: Any):
        if val is None or val == "":
            return None
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(val))
        return float(m.group(1)) if m else None

    charge_pct = _extract_float(raw.get("BCHARGE"))
    time_left = _extract_float(raw.get("TIMELEFT"))
    load_pct = _extract_float(raw.get("LOADPCT"))
    line_v = _extract_float(raw.get("LINEV"))
    batt_v = _extract_float(raw.get("BATTV"))
    batt_temp = _extract_float(raw.get("ITEMP"))
    line_freq = _extract_float(raw.get("LINEFREQ"))

    out_v = _extract_float(raw.get("OUTV") or raw.get("OUTPUTV") or raw.get("NOMOUTV"))
    out_curr = _extract_float(raw.get("OUTCURR") or raw.get("OUTPUT_A") or raw.get("BATTCURR"))
    direct_power = _extract_float(raw.get("REALPOWER") or raw.get("APPARENTPOWER"))

    effective_out_v = out_v
    if effective_out_v is None:
        effective_out_v = line_v if line_v is not None and line_v > 0 else batt_v

    nom_power = _extract_float(raw.get("NOMPOWER"))
    model_str = (raw.get("MODEL") or "").lower()
    if nom_power is None and cfg.get("nominal_power_watts"):
        nom_power = _extract_float(cfg.get("nominal_power_watts"))
    if nom_power is None:
        if "w180" in model_str:
            nom_power = 180.0
        elif "w150" in model_str:
            nom_power = 150.0
        elif "w120" in model_str:
            nom_power = 120.0
        elif effective_out_v is not None and effective_out_v <= 60.0:
            nom_power = 180.0
        else:
            nom_power = 900.0

    power_watts = None
    if direct_power is not None and direct_power >= 0:
        power_watts = round(direct_power, 1)
    elif effective_out_v is not None and out_curr is not None and effective_out_v > 0 and out_curr >= 0:
        power_watts = round(effective_out_v * out_curr, 1)

    if load_pct is not None and power_watts is None and nom_power and nom_power > 0:
        power_watts = round((load_pct / 100.0) * nom_power, 1)
    elif load_pct is None and power_watts is not None and nom_power and nom_power > 0:
        load_pct = round(max(0.0, min(150.0, (power_watts / nom_power) * 100.0)), 1)
    elif load_pct is not None:
        load_pct = round(max(0.0, min(150.0, load_pct)), 1)

    status_str = str(raw.get("STATUS", "ONLINE")).strip().upper()
    is_on_batt = any(k in status_str for k in ("OB", "ONBATT", "ON BATT", "LB", "LOWBATT"))

    cable_str = str(raw.get("CABLE", "")).lower()
    driver_str = str(raw.get("DRIVER", "")).lower()
    proto_str = str(protocol or "").lower()
    is_usb = (
        "usb" in cable_str
        or "usb" in driver_str
        or "hid" in driver_str
        or "usb" in proto_str
        or "hid" in proto_str
        or ups_mode == "usb_hid"
    )

    status_obj = {
        "available": True,
        "status": status_str,
        "model": raw.get("MODEL", raw.get("UPSNAME", "Generic UPS")),
        "battery_charge_pct": charge_pct,
        "time_left_min": time_left,
        "load_pct": load_pct,
        "line_volts": line_v,
        "output_volts": out_v or effective_out_v,
        "output_amps": out_curr,
        "battery_volts": batt_v,
        "battery_temp_c": batt_temp,
        "line_freq_hz": line_freq,
        "nominal_power_watts": nom_power,
        "power_watts": power_watts,
        "protocol": protocol or "unknown",
        "is_usb": is_usb,
        "cable": raw.get("CABLE"),
        "driver": raw.get("DRIVER"),
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


def get_ups_diagnostic_telemetry() -> dict[str, Any]:
    """Audits local USB HID devices, cgroup permissions, report descriptors, and active daemon."""
    audit = {
        "active_status": read_ups_status(force=False),
        "config": mask_ups_config(load_ups_config()),
        "discovered_candidates": discover_ups_sources(),
        "hidraw_nodes": [],
        "cgroup_permission_ok": True,
    }
    # Check accessibility of /dev/hidraw* nodes
    candidate_nodes = sorted(list(set(glob.glob("/dev/hidraw*") + glob.glob("/host/dev/hidraw*"))))
    for h in candidate_nodes:
        try:
            fd = os.open(h, os.O_RDWR | os.O_NONBLOCK)
            os.close(fd)
            audit["hidraw_nodes"].append({"node": h, "accessible": True})
        except PermissionError:
            audit["hidraw_nodes"].append({"node": h, "accessible": False, "error": "PermissionDenied"})
            audit["cgroup_permission_ok"] = False
        except OSError as e:
            audit["hidraw_nodes"].append({"node": h, "accessible": False, "error": str(e)})

    return audit
