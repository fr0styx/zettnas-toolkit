#!/usr/bin/env python3
"""
ZettNAS Toolkit & LCD Dashboard backend.
Serves a 640x172 status page + /api/stats JSON for the front LCD.
Renders directly to /dev/fb0 via memory-mapped framebuffer streaming.

Optimized for low sustained CPU usage and hardware-agnostic operation.
"""
import os
import io
import re
import time
import glob
import json
import struct
import mmap
import mmap
import base64
import shutil
import socket
import colorsys
import subprocess
import gzip
import threading
_ui_wake = threading.Event()
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image
from playwright.sync_api import sync_playwright

# ---- config via env ----
HOST_PROC = os.environ.get("HOST_PROC", "/host/proc")
HOST_SYS = os.environ.get("HOST_SYS", "/host/sys")
HOST_DEV = os.environ.get("HOST_DEV", "/host/dev")
POOL_PATH = os.environ.get("POOL_PATH", "/mnt/user")
DISKS = os.environ.get("DISKS", "")
OS_NVME = os.environ.get("OS_NVME", "nvme1n1")
STATIC_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "static"))

# LCD & Hardware Tuning
ENABLE_FB = os.environ.get("ENABLE_FB", "1") == "1"
LCD_FPS = int(float(os.environ.get("LCD_FPS", "5")))
SMART_POLL_INTERVAL_HDD = int(os.environ.get("SMART_POLL_HDD", "45"))  # seconds for HDDs
SMART_POLL_INTERVAL_NVME = int(os.environ.get("SMART_POLL_NVME", "15"))  # seconds for NVMe

def get_server_hostname():
    env_name = os.environ.get("NAS_NAME", "").strip()
    if env_name:
        return env_name

    for p in [os.path.join(HOST_PROC, "sys/kernel/hostname"), "/proc/sys/kernel/hostname"]:
        if os.path.exists(p):
            try:
                name = open(p).read().strip()
                if name:
                    return name
            except Exception:
                pass

    try:
        name = socket.gethostname().strip()
        if name:
            return name
    except Exception:
        pass

    return "Server"

# ---- Deltas for CPU, Network, Disk I/O ----
_prev = {"idle": 0, "total": 0}
_prev_net = {"time": 0.0, "rx": 0, "tx": 0}
_prev_disk_io = {}

# ---- Hardware Drivers & State Files ----
LED_PORT = os.environ.get("LED_PORT", "/dev/ttyACM0" if os.path.exists("/dev/ttyACM0") else "/host/dev/ttyACM0")
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
LED_STATE_FILE = os.path.join(DATA_DIR, "led_state.json")
DASH_LAYOUT_FILE = os.environ.get("LAYOUT_PATH", os.path.join(DATA_DIR, "dash_layout.json"))
FAN_STATE_FILE = os.path.join(DATA_DIR, "fan_state.json")
SCREEN_STATE_FILE = os.path.join(DATA_DIR, "screen_state.json")

_cached_hwmon = None
_cached_cpu_temp_path = None
_known_active_fans = set()

_cached_disk_list = None
_cached_disk_list_time = 0.0
_DISK_LIST_TTL = 60.0  # seconds

_cached_chassis_model = None

_lcd_renderer_active = False

EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
_event_log = []
_event_log_lock = threading.Lock()

def _load_events():
    global _event_log
    try:
        if os.path.exists(EVENTS_FILE):
            import json
            with open(EVENTS_FILE, "r") as f:
                _event_log = json.load(f)
    except Exception:
        pass

def add_event(level, title, message, details=None):
    global _event_log
    now = int(time.time())
    with _event_log_lock:
        if _event_log and _event_log[0].get("title") == title and _event_log[0].get("message") == message and (now - _event_log[0].get("ts", 0) < 3600):
            return
        entry = {"ts": now, "level": level, "title": title, "message": message}
        if details is not None:
            entry["details"] = details
        _event_log.insert(0, entry)
        _event_log = _event_log[:100]
        try:
            with open(EVENTS_FILE, "w") as f:
                json.dump(_event_log, f)
        except Exception:
            pass


def is_in_time_window(start_str, end_str):
    try:
        now = time.localtime()
        curr_min = now.tm_hour * 60 + now.tm_min
        s_h, s_m = map(int, start_str.split(":"))
        e_h, e_m = map(int, end_str.split(":"))
        s_val = s_h * 60 + s_m
        e_val = e_h * 60 + e_m
        if s_val <= e_val:
            return s_val <= curr_min < e_val
        else:
            return curr_min >= s_val or curr_min < e_val
    except Exception:
        return False

def get_screen_state():
    state = {
        "brightness": 100,
        "night_mode": False,
        "night_start": "23:00",
        "night_end": "07:00",
        "night_brightness": 10
    }
    if os.path.exists(SCREEN_STATE_FILE):
        try:
            with open(SCREEN_STATE_FILE, "r") as f:
                state.update(json.load(f))
        except Exception:
            pass
    return state

def set_screen_brightness(pct):
    pct = max(0, min(100, int(pct)))
    backlight_dir = "/sys/class/backlight/intel_backlight"
    if not os.path.exists(backlight_dir):
        for bl in sorted(glob.glob("/sys/class/backlight/*")):
            if os.path.exists(os.path.join(bl, "brightness")):
                backlight_dir = bl
                break
    if not os.path.exists(backlight_dir):
        return False
    try:
        max_val = 192000
        max_path = os.path.join(backlight_dir, "max_brightness")
        if os.path.exists(max_path):
            max_val = int(open(max_path).read().strip() or 192000)
        target = int((pct / 100.0) * max_val)
        with open(os.path.join(backlight_dir, "brightness"), "w") as f:
            f.write(f"{target}\n")
        return True
    except Exception:
        return False

CRC_TABLE = [
    0x00, 0x07, 0x0e, 0x09, 0x1c, 0x1b, 0x12, 0x15, 0x38, 0x3f, 0x36, 0x31, 0x24, 0x23, 0x2a, 0x2d,
    0x70, 0x77, 0x7e, 0x79, 0x6c, 0x6b, 0x62, 0x65, 0x48, 0x4f, 0x46, 0x41, 0x54, 0x53, 0x5a, 0x5d,
    0xe0, 0xe7, 0xee, 0xe9, 0xfc, 0xfb, 0xf2, 0xf5, 0xd8, 0xdf, 0xd6, 0xd1, 0xc4, 0xc3, 0xca, 0xcd,
    0x90, 0x97, 0x9e, 0x99, 0x8c, 0x8b, 0x82, 0x85, 0xa8, 0xaf, 0xa6, 0xa1, 0xb4, 0xb3, 0xba, 0xbd,
    0xc7, 0xc0, 0xc9, 0xce, 0xdb, 0xdc, 0xd5, 0xd2, 0xff, 0xf8, 0xf1, 0xf6, 0xe3, 0xe4, 0xed, 0xea,
    0xb7, 0xb0, 0xb9, 0xbe, 0xab, 0xac, 0xa5, 0xa2, 0x8f, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9d, 0x9a,
    0x27, 0x20, 0x29, 0x2e, 0x3b, 0x3c, 0x35, 0x32, 0x1f, 0x18, 0x11, 0x16, 0x03, 0x04, 0x0d, 0x0a,
    0x57, 0x50, 0x59, 0x5e, 0x4b, 0x4c, 0x45, 0x42, 0x6f, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7d, 0x7a,
    0x89, 0x8e, 0x87, 0x80, 0x95, 0x92, 0x9b, 0x9c, 0xb1, 0xb6, 0xbf, 0xb8, 0xad, 0xaa, 0xa3, 0xa4,
    0xf9, 0xfe, 0xf7, 0xf0, 0xe5, 0xe2, 0xeb, 0xec, 0xc1, 0xc6, 0xcf, 0xc8, 0xdd, 0xda, 0xd3, 0xd4,
    0x69, 0x6e, 0x67, 0x60, 0x75, 0x72, 0x7b, 0x7c, 0x51, 0x56, 0x5f, 0x58, 0x4d, 0x4a, 0x43, 0x44,
    0x19, 0x1e, 0x17, 0x10, 0x05, 0x02, 0x0b, 0x0c, 0x21, 0x26, 0x2f, 0x28, 0x3d, 0x3a, 0x33, 0x34,
    0x4e, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5c, 0x5b, 0x76, 0x71, 0x78, 0x7f, 0x6a, 0x6d, 0x64, 0x63,
    0x3e, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2c, 0x2b, 0x06, 0x01, 0x08, 0x0f, 0x1a, 0x1d, 0x14, 0x13,
    0xae, 0xa9, 0xa0, 0xa7, 0xb2, 0xb5, 0xbc, 0xbb, 0x96, 0x91, 0x98, 0x9f, 0x8a, 0x8d, 0x84, 0x83,
    0xde, 0xd9, 0xd0, 0xd7, 0xc2, 0xc5, 0xcc, 0xcb, 0xe6, 0xe1, 0xe8, 0xef, 0xfa, 0xfd, 0xf4, 0xf3
]

_alert_active = False
_rainbow_thread = None
_rainbow_stop = threading.Event()

_fan_state_tracker = {
    "pwm1": {"current": 67, "last_up_time": 0.0},
    "pwm2": {"current": 67, "last_up_time": 0.0},
    "pwm3": {"current": 85, "last_up_time": 0.0},
}

def get_current_layout():
    layout = {
        "order": ["metric-storage", "metric-cpu", "metric-mem", "metric-fans", "metric-net", "metric-disks"],
        "vis": {
            "metric-storage": True,
            "metric-cpu": True,
            "metric-mem": True,
            "metric-fans": True,
            "metric-net": True,
            "metric-disks": True
        },
        "sizes": {},
        "clock_format": "24",
        "timezone": "America/New_York",
        "version": 1
    }
    if os.path.exists(DASH_LAYOUT_FILE):
        try:
            with open(DASH_LAYOUT_FILE, "r") as f:
                layout = json.load(f)
        except Exception:
            pass
    return layout

def send_led_packet(mode, r1, g1, b1, r2=0, g2=0, b2=0, speed=5):
    port = LED_PORT
    by_id = glob.glob("/dev/serial/by-id/*ZettOS_RGB*")
    if by_id and os.path.exists(by_id[0]):
        port = by_id[0]
    elif os.path.exists(LED_PORT):
        port = LED_PORT
    elif os.path.exists("/dev/ttyACM0"):
        port = "/dev/ttyACM0"
    elif os.path.exists("/host/dev/ttyACM0"):
        port = "/host/dev/ttyACM0"

    if not os.path.exists(port):
        return False, f"Device {port} not found"

    subprocess.run(["stty", "-F", port, "115200", "cs8", "-cstopb", "-parenb", "raw", "-echo"],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raw_delay = max(1, min(255, int(speed))) & 0xFF
    payload = bytes([mode, r1, g1, b1, r2, g2, b2, raw_delay])
    crc = 0
    for byte in payload:
        crc = CRC_TABLE[crc ^ byte]
    frame = bytes([0xFF, 0xFF]) + payload + bytes([crc])
    try:
        with open(port, "wb", buffering=0) as f:
            f.write(frame)
        return True, "OK"
    except Exception as e:
        return False, str(e)


def _rainbow_worker(brightness, slider_speed):
    hue = 0.0
    interval = max(0.04, 0.16 - (slider_speed / 100.0) * 0.12)
    while not _rainbow_stop.is_set():
        r_f, g_f, b_f = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        scale = brightness / 100.0
        r = int(r_f * 255 * scale)
        g = int(g_f * 255 * scale)
        b = int(b_f * 255 * scale)
        send_led_packet(6, r, g, b, r, g, b, speed=5)
        hue = (hue + 0.015) % 1.0
        time.sleep(interval)


def apply_led_state(data):
    global _rainbow_thread, _rainbow_stop
    _rainbow_stop.set()
    if _rainbow_thread and _rainbow_thread.is_alive():
        _rainbow_thread.join(timeout=0.4)

    power = data.get("power", "on")
    brightness = int(data.get("brightness", 25))
    color_hex = data.get("color", "25c2a0").lstrip("#")
    color2_hex = data.get("color2", "ff0055").lstrip("#")
    effect = data.get("mode", "solid")
    slider_speed = max(1, min(100, int(data.get("speed", 50))))

    if power == "off" or brightness <= 0:
        return send_led_packet(0, 0, 0, 0, 0, 0, 0, 0)

    if effect == "rainbow":
        _rainbow_stop.clear()
        _rainbow_thread = threading.Thread(target=_rainbow_worker, args=(brightness, slider_speed), daemon=True)
        _rainbow_thread.start()
        return True, "Rainbow Active"

    factor = (100 - slider_speed) / 99.0
    hw_delay = max(1, min(255, int(1 + (factor ** 2.2) * 254)))

    r_raw = int(color_hex[0:2], 16)
    g_raw = int(color_hex[2:4], 16)
    b_raw = int(color_hex[4:6], 16)
    scale = brightness / 100.0
    r = max(0, min(255, int(r_raw * scale)))
    g = max(0, min(255, int(g_raw * scale)))
    b = max(0, min(255, int(b_raw * scale)))

    if len(color2_hex) >= 6:
        r2_raw = int(color2_hex[0:2], 16)
        g2_raw = int(color2_hex[2:4], 16)
        b2_raw = int(color2_hex[4:6], 16)
    else:
        r2_raw, g2_raw, b2_raw = 255, 0, 85

    r2 = max(0, min(255, int(r2_raw * scale)))
    g2 = max(0, min(255, int(g2_raw * scale)))
    b2 = max(0, min(255, int(b2_raw * scale)))

    if effect == "breathe":
        return send_led_packet(1, r, g, b, 0, 0, 0, speed=hw_delay)
    elif effect == "flow":
        return send_led_packet(2, r, g, b, 0, 0, 0, speed=hw_delay)
    elif effect == "chase":
        return send_led_packet(3, r, g, b, 0, 0, 0, speed=hw_delay)
    elif effect == "gradient":
        return send_led_packet(4, r, g, b, r2, g2, b2, speed=hw_delay)
    elif effect == "flashing":
        return send_led_packet(5, r, g, b, 0, 0, 0, speed=hw_delay)
    else:
        return send_led_packet(6, r, g, b, r, g, b, speed=5)


def read_cpu_util():
    try:
        with open(os.path.join(HOST_PROC, "stat")) as f:
            parts = f.readline().split()[1:]
        vals = list(map(int, parts))
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        d_idle = idle - _prev["idle"]
        d_total = total - _prev["total"]
        _prev["idle"], _prev["total"] = idle, total
        if d_total <= 0:
            return 0
        return round(100 * (1 - d_idle / d_total))
    except Exception:
        return 0


def read_mem():
    info = {}
    try:
        with open(os.path.join(HOST_PROC, "meminfo")) as f:
            for line in f:
                k, v = line.split(":")
                info[k.strip()] = int(v.split()[0])
        total = info.get("MemTotal", 0) / 1024 / 1024
        avail = info.get("MemAvailable", 0) / 1024 / 1024
        used = total - avail
        pct = round(100 * used / total) if total else 0
        return {"used_gb": round(used, 1), "total_gb": round(total, 1), "pct": pct}
    except Exception:
        return {"used_gb": 0, "total_gb": 0, "pct": 0}


def _find_hwmon():
    global _cached_hwmon
    if _cached_hwmon and os.path.exists(_cached_hwmon):
        return _cached_hwmon
    for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
        try:
            with open(os.path.join(h, "name")) as f:
                n = f.read().strip()
                if n in ("zettlab_d8_fans", "zettos_pwm_fan", "nct6775", "it87"):
                    _cached_hwmon = h
                    return h
        except Exception:
            continue
    for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
        if glob.glob(os.path.join(h, "pwm*")):
            _cached_hwmon = h
            return h
    return None


def read_cpu_temp():
    global _cached_cpu_temp_path
    if _cached_cpu_temp_path and os.path.exists(_cached_cpu_temp_path):
        try:
            val = int(open(_cached_cpu_temp_path).read().strip() or 0) / 1000
            if val > 0:
                return round(val)
        except Exception:
            _cached_cpu_temp_path = None

    for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
        try:
            name = open(os.path.join(h, "name")).read().strip()
            if name in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
                for t in sorted(glob.glob(os.path.join(h, "temp*_input"))):
                    val = int(open(t).read().strip() or 0) / 1000
                    if val > 0:
                        _cached_cpu_temp_path = t
                        return round(val)
        except Exception:
            continue
    return 0


def read_fans():
    global _known_active_fans
    hw = _find_hwmon()
    fans = []
    if hw:
        for f in sorted(glob.glob(os.path.join(hw, "fan*_input"))):
            try:
                rpm = int(open(f).read().strip() or 0)
                fans.append(rpm)
            except Exception:
                fans.append(0)
    else:
        for h in sorted(glob.glob(os.path.join(HOST_SYS, "class/hwmon/hwmon*"))):
            for f in sorted(glob.glob(os.path.join(h, "fan*_input"))):
                try:
                    rpm = int(open(f).read().strip() or 0)
                    if rpm > 0:
                        fans.append(rpm)
                except Exception:
                    pass
    # Sanitize fan readings (e.g. spurious 8000 RPM or 65535 spikes from I2C bugs)
    for i in range(len(fans)):
        if fans[i] >= 6000:
            fans[i] = 0
            
    for idx, rpm in enumerate(fans):
        if rpm > 300:
            _known_active_fans.add(idx)
    return fans


def detect_chassis_model():
    global _cached_chassis_model
    if _cached_chassis_model is not None:
        return _cached_chassis_model
    dmi_path = os.path.join(HOST_SYS, "class/dmi/id/product_name")
    if os.path.exists(dmi_path):
        try:
            prod = open(dmi_path).read().strip().lower()
            if "d8" in prod:
                _cached_chassis_model = "d8u"
                return _cached_chassis_model
            if "d6" in prod:
                _cached_chassis_model = "d6u"
                return _cached_chassis_model
            if "d4" in prod:
                _cached_chassis_model = "d4"
                return _cached_chassis_model
        except Exception:
            pass

    disks = _discover_disks()
    count = len(disks)
    if count > 6:
        _cached_chassis_model = "d8u"
    elif count <= 4 and count > 0:
        _cached_chassis_model = "d4"
    else:
        _cached_chassis_model = "d6u"
    return _cached_chassis_model


def calc_curve_pwm(temp, min_pwm=58, max_pwm=183, temp_min=37, temp_max=50, curve_points=None):
    if temp is None or temp <= 0:
        return min_pwm

    if curve_points and len(curve_points) >= 2:
        pts = sorted(curve_points, key=lambda x: x[0])
        if temp <= pts[0][0]:
            pct = pts[0][1]
        elif temp >= pts[-1][0]:
            pct = pts[-1][1]
        else:
            pct = pts[0][1]
            for i in range(len(pts)-1):
                t1, p1 = pts[i]
                t2, p2 = pts[i+1]
                if t1 <= temp <= t2:
                    span = max(1, t2 - t1)
                    ratio = (temp - t1) / float(span)
                    pct = p1 + ratio * (p2 - p1)
                    break
        val = int((pct / 100.0) * max_pwm)
        return max(0, min(max_pwm, val))

    if temp >= temp_max:
        return max_pwm
    if temp <= temp_min:
        return min_pwm
    span = max(1, temp_max - temp_min)
    ratio = (temp - temp_min) / float(span)
    val = int(min_pwm + ratio * (max_pwm - min_pwm))
    return max(min_pwm, min(max_pwm, val))


def apply_zone_pwm(pwm_index, target_pwm, hold_secs=120):
    now = time.time()
    pwm_key = f"pwm{pwm_index}"
    if pwm_key not in _fan_state_tracker:
        _fan_state_tracker[pwm_key] = {"current": 67, "last_up_time": 0.0}
    state = _fan_state_tracker[pwm_key]
    current = state["current"]

    if target_pwm > current:
        state["current"] = target_pwm
        state["last_up_time"] = now
        return target_pwm
    elif target_pwm < current:
        if (now - state["last_up_time"]) >= hold_secs:
            state["current"] = target_pwm
            return target_pwm
        else:
            return current
    return current


def get_hold_remaining(pwm_key, hold_secs=120):
    state = _fan_state_tracker.get(pwm_key, {})
    last_up = state.get("last_up_time", 0.0)
    rem = hold_secs - (time.time() - last_up)
    return max(0, int(rem))


def set_fan_pwm(profile, manual_pct=60, custom_pwms=None, ctrl_cpu_fan=False):
    hw = _find_hwmon()
    if not hw:
        return False

    applied = 0
    available_pwms = sorted(glob.glob(os.path.join(hw, "pwm[1-9]")))

    if custom_pwms:
        targets = {}
        for p in available_pwms:
            key = os.path.basename(p)
            if key == "pwm3" and not ctrl_cpu_fan:
                continue
            targets[p] = custom_pwms.get(key, 67)
    else:
        pct_map = {"quiet": 67, "balanced": 120, "performance": 155, "full": 183}
        raw = pct_map.get(profile, int((manual_pct / 100.0) * 183))
        raw = max(58, min(183, raw))
        targets = {p: raw for p in available_pwms if not (os.path.basename(p) == "pwm3" and not ctrl_cpu_fan)}

    pwm3_enable_file = os.path.join(hw, "pwm3_enable")
    if os.path.exists(pwm3_enable_file):
        try:
            with open(pwm3_enable_file, "w") as f:
                f.write("1\n" if ctrl_cpu_fan else "2\n")
        except Exception:
            pass

    for path, val in targets.items():
        if os.path.exists(path):
            try:
                with open(path, "w") as f:
                    f.write(f"{val}\n")
                applied += 1
            except Exception:
                pass

    return applied > 0


def _discover_disks():
    global _cached_disk_list, _cached_disk_list_time
    now = time.time()
    if _cached_disk_list is not None and (now - _cached_disk_list_time) < _DISK_LIST_TTL:
        return _cached_disk_list

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
        _cached_disk_list = result
        _cached_disk_list_time = now
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
    except Exception:
        pass
    _cached_disk_list = disks
    _cached_disk_list_time = now
    return disks


def _short_name(dev, idx_nvme):
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


_cached_smart_data = {}
_last_smart_scan = {}  # {dev_name: float}

def read_disk_temps_and_io():
    global _prev_disk_io, _cached_smart_data, _last_smart_scan
    now = time.time()
    curr_io = {}
    try:
        with open(os.path.join(HOST_PROC, "diskstats")) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14:
                    dev = parts[2]
                    curr_io[dev] = int(parts[3]) + int(parts[7])
    except Exception:
        pass

    out = []
    show_os = os.environ.get("SHOW_OS_DISK", "1") == "1"
    for d in _discover_disks():
        dev_name = d["dev"]
        role = d["role"]
        if role == "os" and not show_os:
            continue
        dev = HOST_DEV.rstrip("/") + "/" + dev_name
        is_nvme = dev_name.startswith("nvme")
        dtype = "nvme" if is_nvme else "sat"

        poll_interval = SMART_POLL_INTERVAL_NVME if is_nvme else SMART_POLL_INTERVAL_HDD
        last_scan = _last_smart_scan.get(dev_name, 0.0)
        should_poll_smart = (now - last_scan) >= poll_interval

        is_standby = False
        if should_poll_smart or dev_name not in _cached_smart_data:
            _last_smart_scan[dev_name] = now
            try:
                cmd = ["smartctl"]
                if not is_nvme:
                    cmd.extend(["-n", "standby"])
                cmd.extend(["-H", "-A", "-d", dtype, dev])

                r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)

                if not is_nvme and (r.returncode == 2 or "STANDBY" in r.stdout.upper() or "SLEEP" in r.stdout.upper()):
                    is_standby = True
                    prev_t, _ = _cached_smart_data.get(dev_name, (None, "standby"))
                    temp = prev_t
                    health = "standby"
                    _cached_smart_data[dev_name] = (temp, health)
                else:
                    temp, health = _parse_smart(r.stdout, is_nvme)
                    _cached_smart_data[dev_name] = (temp, health)
            except Exception:
                temp, health = _cached_smart_data.get(dev_name, (None, "ok"))
        else:
            temp, health = _cached_smart_data.get(dev_name, (None, "ok"))
            is_standby = (health == "standby")

        prev_count = _prev_disk_io.get(dev_name, 0)
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

    _prev_disk_io = curr_io
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


def read_network_rates():
    global _prev_net
    now = time.time()
    rx_bytes = 0
    tx_bytes = 0
    try:
        with open(os.path.join(HOST_PROC, "net/dev")) as f:
            for line in f:
                if ":" in line:
                    iface, data = line.split(":", 1)
                    iface = iface.strip()
                    if iface in ("lo",) or iface.startswith(("veth", "br-", "docker")):
                        continue
                    fields = data.split()
                    if len(fields) >= 9:
                        rx_bytes += int(fields[0])
                        tx_bytes += int(fields[8])
    except Exception:
        pass

    dt = max(0.1, now - _prev_net["time"])
    rx_rate = 0.0
    tx_rate = 0.0
    if _prev_net["time"] > 0:
        rx_rate = max(0.0, (rx_bytes - _prev_net["rx"]) / dt)
        tx_rate = max(0.0, (tx_bytes - _prev_net["tx"]) / dt)

    _prev_net = {"time": now, "rx": rx_bytes, "tx": tx_bytes}

    def fmt_speed(b):
        if b >= 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MB/s"
        elif b >= 1024:
            return f"{b / 1024:.0f} KB/s"
        return f"{b:.0f} B/s"

    return {"rx": fmt_speed(rx_rate), "tx": fmt_speed(tx_rate)}


def read_storage():
    try:
        u = shutil.disk_usage(POOL_PATH)
        total_gb = u.total / 1e9
        used_gb = u.used / 1e9
        pct = round(100 * u.used / u.total) if u.total else 0
        def fmt(g): return f"{g/1000:.0f}TB" if g >= 1000 else f"{g:.0f}GB"
        return {"used": fmt(used_gb), "total": fmt(total_gb), "pct": pct}
    except Exception:
        return {"used": "0GB", "total": "0GB", "pct": 0}


def read_uptime():
    try:
        with open(os.path.join(HOST_PROC, "uptime")) as f:
            secs = float(f.read().split()[0])
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        return f"{h//24}d {h%24}h" if h >= 24 else f"{h}h {m}m"
    except Exception:
        return "?"


_discovered_host_ip = None

def read_ip():
    global _discovered_host_ip

    env_ip = os.environ.get("HOST_IP", "").strip()
    if env_ip:
        return env_ip

    if _discovered_host_ip:
        return _discovered_host_ip

    for p in ["/boot/config/network.cfg", "/host/etc/network/interfaces"]:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    content = f.read()
                matches = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', content)
                for ip in matches:
                    if not (ip.startswith("127.") or ip.startswith("172.") or ip.endswith(".255") or ip == "0.0.0.0"):
                        _discovered_host_ip = ip
                        return ip
            except Exception:
                pass

    return "?"



_copy_active = False
_copy_status = "idle"
_copy_confirm_event = threading.Event()
_copy_abort_flag = False
_copy_overwrite_choice = 'skip'
_copy_progress = {"total": 0, "copied": 0, "start": 0, "file": ""}
BUTTON_CFG_FILE = os.path.join(DATA_DIR, "button_state.json")

def button_listener_daemon():
    global _copy_active, _copy_status
    MMIO_BASE = 0xE0D20000
    COPY_OFFSET = 0x6C0

    try:
        fd = os.open(os.path.join(HOST_DEV, "mem"), os.O_RDWR | os.O_SYNC)
        mem = mmap.mmap(fd, 4096, offset=MMIO_BASE)
    except Exception as e:
        print(f"[ZettNAS] Hardware button mapping failed: {e}")
        return

    last_state = 1
    while True:
        try:
            copy_val = struct.unpack("<I", mem[COPY_OFFSET:COPY_OFFSET+4])[0]
            current_state = (copy_val & 2) >> 1
            
            if current_state == 0 and last_state == 1:
                cfg = {"enabled": False, "source": "/mnt/disks/", "dest": "/mnt/user/Media/"}
                if os.path.exists(BUTTON_CFG_FILE):
                    try:
                        with open(BUTTON_CFG_FILE, "r") as f:
                            cfg.update(json.load(f))
                    except: pass
                
                if cfg.get("enabled") and not _copy_active:
                    _copy_active = True
                    _copy_status = "copying"
                    _ui_wake.set()
                    add_event("info", "Copy Started", "Starting ingest from SD Card reader...")
                    threading.Thread(target=_do_copy, args=(cfg,), daemon=True).start()
            
            last_state = current_state
        except Exception:
            pass
        time.sleep(0.1)

def _do_copy(cfg):
    global _copy_active, _copy_status, _copy_progress, _copy_confirm_event, _copy_overwrite_choice
    src_mode = cfg.get("source", "sd").strip()
    dst = cfg.get("dest", "/mnt/user/").strip()
    
    _copy_progress = {"total": 0, "copied": 0, "start": time.time(), "file": "Initializing...", "files_total": 0, "files_done": 0}
    tmp_mount = False
    mounted_path = None
    try:
        target_lun = "1" if src_mode == "sd" else "0"
        found_dev = None
        import glob
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
            except: pass
            
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
        except: pass
        
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

        _copy_progress["file"] = "Scanning for collisions..."
        _ui_wake.set()
        
        collisions = []
        for dirpath, _, filenames in os.walk(src_path):
            for f in filenames:
                src_file = os.path.join(dirpath, f)
                rel_path = os.path.relpath(src_file, src_path)
                dst_file = os.path.join(dst_path, rel_path)
                if os.path.exists(dst_file):
                    collisions.append(rel_path)

        if collisions:
            _copy_status = "awaiting_confirmation"
            _copy_progress["file"] = f"{len(collisions)} files already exist in destination."
            add_event("warning", "Copy Collision", f"{len(collisions)} files already exist. Waiting for confirmation.")
            _ui_wake.set()
            
            _copy_confirm_event.clear()
            _copy_confirm_event.wait(timeout=300.0)
            
            if not _copy_confirm_event.is_set():
                raise Exception("Aborted: Timed out waiting for overwrite confirmation.")
            
            if _copy_overwrite_choice == "cancel":
                raise Exception("Aborted by user.")

        _copy_progress["file"] = "Calculating total size..."
        _ui_wake.set()
        total_size = 0
        files_to_copy = []
        
        for dirpath, _, filenames in os.walk(src_path):
            for f in filenames:
                src_file = os.path.join(dirpath, f)
                rel_path = os.path.relpath(src_file, src_path)
                dst_file = os.path.join(dst_path, rel_path)
                
                if os.path.exists(dst_file) and collisions:
                    if _copy_overwrite_choice == "skip":
                        continue
                        
                if not os.path.islink(src_file):
                    total_size += os.path.getsize(src_file)
                    files_to_copy.append((src_file, dst_file))

        _copy_progress["total"] = total_size
        _copy_progress["files_total"] = len(files_to_copy)
        _copy_progress["files_done"] = 0
        global _copy_abort_flag
        _copy_abort_flag = False
        _copy_progress["start"] = time.time()
        _copy_status = "copying"
        _ui_wake.set()
        
        for src_f, dst_f in files_to_copy:
            if _copy_abort_flag:
                break
            os.makedirs(os.path.dirname(dst_f), exist_ok=True)
            _copy_progress["file"] = os.path.basename(src_f)
            length = 1024 * 1024 * 4
            try:
                with open(src_f, 'rb') as fsrc, open(dst_f, 'wb') as fdst:
                    while True:
                        if _copy_abort_flag: break
                        buf = fsrc.read(length)
                        if not buf:
                            break
                        fdst.write(buf)
                        _copy_progress["copied"] += len(buf)
                if _copy_abort_flag: os.remove(dst_f); break
                import shutil
                shutil.copystat(src_f, dst_f)
                _copy_progress['files_done'] += 1
            except Exception as e:
                print(f"[ZettNAS] Error copying {src_f}: {e}")

        if _copy_abort_flag:
            _copy_status = "aborted"
            _copy_progress["file"] = "Aborted."
            add_event("warning", "Copy Aborted", "User aborted the copy operation.")
            raise Exception("Aborted by user.")
        else:
            _copy_status = "success"
            add_event("success", "Copy Completed", f"Successfully copied {_copy_progress['files_done']} files.")
        _copy_progress["file"] = "Finished successfully." 
        
    except Exception as e:
        print(f"[ZettNAS] Copy failed: {e}")
        _copy_status = "error"
        _copy_progress["file"] = f"Error: {e}"
        add_event("error", "Copy Failed", str(e))
        try: send_led_packet(5, 255, 0, 0, 0, 0, 0, speed=10)
        except: pass
    finally:
        if tmp_mount and mounted_path:
            subprocess.run(["umount", mounted_path])
        _copy_active = False
        _ui_wake.set()
        time.sleep(8)
        _copy_status = "idle"
        _ui_wake.set()



_cached_stats = None

_cached_stats_lock = threading.Lock()


def read_media_slots():
    slots = {"sd": {"size": 0, "dev": None}, "tf": {"size": 0, "dev": None}}
    try:
        import glob
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
            except Exception:
                pass
    except Exception:
        pass
    return slots

def stats_collector_daemon():
    global _cached_stats, _alert_active
    _prev_crit = False
    _prev_warn = False
    _prev_throttle = False
    _prev_fan_stall = False
    while True:
        try:
            disks = read_disk_temps_and_io()
            net = read_network_rates()
            bad = [d for d in disks if d.get("health") in ("warn", "crit")]
            has_crit = any(d.get("health") == "crit" for d in disks)
            if has_crit:
                status = f"{len(bad)} ALERT"
            elif bad:
                status = f"{len(bad)} WARN"
            else:
                status = f"{len(disks)} OK"

            cpu_temp = read_cpu_temp()
            fans = read_fans()

            fan_cfg = {"profile": "auto", "manual_pct": 60, "ctrl_cpu_fan": False, "temp_min": 37, "temp_max": 50}
            if os.path.exists(FAN_STATE_FILE):
                try:
                    with open(FAN_STATE_FILE, "r") as f:
                        fan_cfg.update(json.load(f))
                except Exception:
                    pass

            profile = fan_cfg.get("profile", "auto")
            ctrl_cpu_fan = fan_cfg.get("ctrl_cpu_fan", False)
            temp_min = fan_cfg.get("temp_min", 37)
            temp_max = fan_cfg.get("temp_max", 50)

            sata_disks = [d for d in disks if d.get("role") == "data" or d.get("dev", "").startswith("sd")]
            midpoint = max(1, len(sata_disks) // 2)

            zone1_disks = sata_disks[:midpoint]
            zone2_disks = sata_disks[midpoint:]

            # Only calculate zone max temps from active/awake drives so sleeping drives stay quiet
            active_z1 = [d["temp"] for d in zone1_disks if d.get("temp") is not None and not d.get("standby", False)]
            active_z2 = [d["temp"] for d in zone2_disks if d.get("temp") is not None and not d.get("standby", False)]

            t_zone1 = max(active_z1, default=32)
            t_zone2 = max(active_z2, default=32)

            curve_points = fan_cfg.get("curve_points", None)
            raw_pwm1 = calc_curve_pwm(t_zone1, min_pwm=58, max_pwm=183, temp_min=temp_min, temp_max=temp_max, curve_points=curve_points)
            raw_pwm2 = calc_curve_pwm(t_zone2, min_pwm=58, max_pwm=183, temp_min=temp_min, temp_max=temp_max, curve_points=curve_points)

            if cpu_temp >= 85:
                raw_pwm3 = 183
            elif cpu_temp >= 70:
                raw_pwm3 = 145
            elif cpu_temp >= 55:
                raw_pwm3 = 115
            else:
                raw_pwm3 = 85

            if profile == "auto":
                active_pwm1 = apply_zone_pwm(1, raw_pwm1, hold_secs=120)
                active_pwm2 = apply_zone_pwm(2, raw_pwm2, hold_secs=120)

                custom_pwms = {"pwm1": active_pwm1, "pwm2": active_pwm2}

                if ctrl_cpu_fan:
                    active_pwm3 = apply_zone_pwm(3, raw_pwm3, hold_secs=90)
                    custom_pwms["pwm3"] = active_pwm3
                else:
                    active_pwm3 = 0

                set_fan_pwm("auto", custom_pwms=custom_pwms, ctrl_cpu_fan=ctrl_cpu_fan)
            else:
                pct_map = {"quiet": 67, "balanced": 120, "performance": 155, "full": 183}
                man_pwm = pct_map.get(profile, int((fan_cfg.get("manual_pct", 60) / 100.0) * 183))
                active_pwm1 = man_pwm
                active_pwm2 = man_pwm
                active_pwm3 = man_pwm if ctrl_cpu_fan else 0
                set_fan_pwm(profile, manual_pct=fan_cfg.get("manual_pct", 60), ctrl_cpu_fan=ctrl_cpu_fan)

            # Screen Backlight Management & Schedule
            screen_cfg = get_screen_state()
            in_screen_night = screen_cfg.get("night_mode", False) and is_in_time_window(screen_cfg.get("night_start", "23:00"), screen_cfg.get("night_end", "07:00"))
            target_bl = screen_cfg.get("night_brightness", 10) if in_screen_night else screen_cfg.get("brightness", 100)
            set_screen_brightness(target_bl)

            # LED Lighting & Night Schedule
            cfg = {}
            if os.path.exists(LED_STATE_FILE):
                try:
                    with open(LED_STATE_FILE, "r") as f:
                        cfg = json.load(f)
                except Exception:
                    pass

            in_led_night = cfg.get("night_mode", False) and is_in_time_window(cfg.get("night_start", "23:00"), cfg.get("night_end", "07:00"))

            if cfg.get("reactive", True):
                is_failing_fan = any(fans[i] == 0 for i in _known_active_fans if i < len(fans)) if _known_active_fans else False
                is_crit = has_crit or (cpu_temp >= 85) or is_failing_fan
                is_warn = (len(bad) > 0) or (cpu_temp >= 70)

                if is_failing_fan:
                    add_event("error", "Fan Stall Detected", "One or more cooling fans have stalled (0 RPM).", details={"fans": fans})

                if cpu_temp >= 85:
                    add_event("error", "CPU Thermal Critical", f"CPU temperature reached {cpu_temp}°C. Hardware throttling active.", details={"cpu_temp": cpu_temp})
                elif cpu_temp >= 75:
                    add_event("warning", "CPU Thermal Warning", f"CPU temperature is elevated ({cpu_temp}°C).", details={"cpu_temp": cpu_temp})

                for d in bad:
                    d_name = d.get("name", "Unknown")
                    d_health = d.get("health", "warn")
                    d_temp = d.get("temp", 0)
                    if d_health == "crit":
                        add_event("error", f"Drive Critical: {d_name}", f"Drive reached critical health or extreme temp ({d_temp}°C)", details=d)
                    elif d_health == "warn":
                        add_event("warning", f"Drive Warning: {d_name}", f"Drive is running hot or has warnings ({d_temp}°C)", details=d)


                is_disk_active = any(d.get("active", False) for d in disks)
                if is_crit:
                    _alert_active = True
                    send_led_packet(5, 255, 0, 0, 0, 0, 0, speed=10)
                elif _copy_active:
                    _alert_active = True
                    if _copy_status == "copying":
                        send_led_packet(2, 0, 100, 255, 0, 0, 0, speed=20)
                    elif _copy_status == "success":
                        send_led_packet(1, 0, 255, 0, 0, 0, 0, speed=10)
                    elif _copy_status == "error":
                        send_led_packet(5, 255, 0, 0, 0, 0, 0, speed=10)
                elif is_warn:
                    _alert_active = True
                    send_led_packet(1, 255, 120, 0, 0, 0, 0, speed=18)
                elif is_disk_active and not in_led_night:
                    _alert_active = True
                    # Cylon / Scanning effect for active disk IO (Cyan/Blue flow)
                    send_led_packet(2, 0, 200, 255, 0, 0, 0, speed=40)
                elif in_led_night:
                    _alert_active = False
                    send_led_packet(0, 0, 0, 0, 0, 0, 0, 0)
                elif _alert_active:
                    _alert_active = False
                    apply_led_state(cfg)
            elif in_led_night:
                send_led_packet(0, 0, 0, 0, 0, 0, 0, 0)

            disk_hold_rem = max(get_hold_remaining("pwm1", 120), get_hold_remaining("pwm2", 120))
            cpu_hold_rem = get_hold_remaining("pwm3", 90)

            data = {
                "name": get_server_hostname(),
                "status": status,
                "ip": read_ip(),
                "storage": read_storage(),
                "cpu": {"temp": cpu_temp, "util": read_cpu_util()},
                "mem": read_mem(),
                "fans": fans,
                "copy_state": {"active": _copy_active, "status": _copy_status, "progress": _copy_progress},
                "media_slots": read_media_slots(),
        "fan_control": {
                    "zone1_temp": t_zone1,
                    "zone1_pwm": active_pwm1,
                    "zone2_temp": t_zone2,
                    "zone2_pwm": active_pwm2,
                    "cpu_temp": cpu_temp,
                    "cpu_pwm": active_pwm3,
                    "disk_hold_remaining": disk_hold_rem,
                    "cpu_hold_remaining": cpu_hold_rem,
                    "ctrl_cpu_fan": ctrl_cpu_fan,
                    "profile": profile,
                    "temp_min": temp_min,
                    "temp_max": temp_max,
                    "curve_points": fan_cfg.get("curve_points", None)
                },
                "net": net,
                "uptime": read_uptime(),
                "disks": disks,
                "chassis": detect_chassis_model(),
                "layout": get_current_layout(), "copy_status": _copy_status
            }
            with _cached_stats_lock:
                _cached_stats = data
        except Exception as e:
            import traceback
            print('CRASH:', e)
            traceback.print_exc()
        if _ui_wake.wait(2.0):
                        _ui_wake.clear()


def collect():
    with _cached_stats_lock:
        data = dict(_cached_stats) if _cached_stats else {
            "name": get_server_hostname(), "status": "-- OK", "ip": read_ip(),
            "storage": {"used": "0GB", "total": "0GB", "pct": 0}, "cpu": {"temp": 0, "util": 0}, "mem": {"used_gb": 0, "total_gb": 0, "pct": 0},
            "fans": [], "copy_state": {"active": False, "status": "idle", "progress": {}},
            "net": {"tx": "0 B/s", "rx": "0 B/s"}, "uptime": "0s", "disks": []
        }
    with _event_log_lock:
        data["events"] = list(_event_log)
    return data

def _old_collect_wrapper():
    return {
        "name": get_server_hostname(),
        "status": "-- OK",
        "ip": read_ip(),
        "storage": {"used": "0GB", "total": "0GB", "pct": 0},
        "cpu": {"temp": 0, "util": 0},
        "mem": {"used_gb": 0, "total_gb": 0, "pct": 0},
        "fans": [],
        "media_slots": {"sd": {"size": 0, "dev": None}, "tf": {"size": 0, "dev": None}},
        "copy_state": {"active": _copy_active, "status": _copy_status, "progress": _copy_progress},
        "fan_control": {
            "zone1_temp": 35,
            "zone1_pwm": 67,
            "zone2_temp": 35,
            "zone2_pwm": 67,
            "cpu_temp": 40,
            "cpu_pwm": 85,
            "disk_hold_remaining": 0,
            "cpu_hold_remaining": 0,
            "ctrl_cpu_fan": False,
            "profile": "auto"
        },
        "net": {"rx": "0 KB/s", "tx": "0 KB/s"},
        "uptime": "--",
        "disks": [],
        "chassis": "d6u",
        "layout": get_current_layout(), "copy_status": _copy_status
    }


def render_lcd_loop():
    global _lcd_renderer_active
    """
    Active Framebuffer Streamer to /dev/fb0:
    - Viewport oriented 172x640 via CSS 90deg rotation (No CPU matrix rotate overhead).
    - Captures at LCD_FPS with single-pass memory line assembly.
    - Single mmap memory block write into video memory per frame.
    """
    if not ENABLE_FB or not os.path.exists("/dev/fb0"):
        print("[LCD] Framebuffer /dev/fb0 not present or disabled. Running web-only.", flush=True)
        return

    time.sleep(2)
    port = int(os.environ.get("PORT", "8082"))
    url = f"http://127.0.0.1:{port}/?mode=lcd"

    backlight_path = "/sys/class/backlight/intel_backlight/brightness"
    if os.path.exists(backlight_path):
        try:
            with open(backlight_path, "w") as bl_f:
                bl_f.write("192000\n")
        except OSError:
            pass

    stride = 704
    fb_height = 640
    fb_width = 172
    row_bytes = fb_width * 4
    total_fb_bytes = fb_height * stride
    
    target_fps = max(1, LCD_FPS)
    frame_interval = 1.0 / target_fps
    lcd_format = os.environ.get("LCD_FORMAT", "png").lower()

    print(f"[LCD] Starting active renderer: {fb_width}x{fb_height} @ {target_fps} FPS -> /dev/fb0 (stride {stride}, format {lcd_format})", flush=True)

    chromium_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-extensions",
        "--disable-component-update",
        "--disable-sync",
        "--disable-translate",
        "--mute-audio",
        "--no-first-run",
        "--disable-default-apps",
        "--hide-scrollbars",
        "--disable-breakpad",
        "--disable-features=Translate,OptimizationHints,MediaRouter",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--ignore-gpu-blocklist",
        "--js-flags=--max-old-space-size=64",
        "--disk-cache-size=1",
        "--media-cache-size=1",
    ]

    while True:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=chromium_args
                )
                context = browser.new_context(
                    viewport={"width": fb_width, "height": fb_height},
                    device_scale_factor=1
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                _lcd_renderer_active = True

                cdp = context.new_cdp_session(page)
                shot_params = {
                    "format": "jpeg" if lcd_format == "jpeg" else "png",
                    "optimizeForSpeed": True
                }
                if lcd_format == "jpeg":
                    shot_params["quality"] = 95

                with open("/dev/fb0", "r+b") as fb_file:
                    fb_mem = mmap.mmap(fb_file.fileno(), total_fb_bytes, mmap.MAP_SHARED, mmap.PROT_WRITE)
                    # Pre-fill line padding once
                    fb_mem[:total_fb_bytes] = b"\x00" * total_fb_bytes
                    prev_raw_b64 = None

                    while True:
                        t0 = time.time()

                        try:
                            res = cdp.send("Page.captureScreenshot", shot_params)
                            raw_b64 = res.get("data")
                            if raw_b64 and raw_b64 == prev_raw_b64:
                                elapsed = time.time() - t0
                                sleep_time = max(0.01, frame_interval - elapsed)
                                time.sleep(sleep_time)
                                continue
                            prev_raw_b64 = raw_b64
                            raw_bytes = base64.b64decode(raw_b64)
                        except Exception:
                            # Fallback if CDP session encounters an issue
                            raw_bytes = page.screenshot(type="png")

                        img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
                        raw_pixels = img.tobytes("raw", "BGRA")
                        mv = memoryview(raw_pixels)

                        src_pos = 0
                        dst_pos = 0
                        for _ in range(fb_height):
                            fb_mem[dst_pos : dst_pos + row_bytes] = mv[src_pos : src_pos + row_bytes]
                            src_pos += row_bytes
                            dst_pos += stride

                        elapsed = time.time() - t0
                        sleep_time = max(0.01, frame_interval - elapsed)
                        time.sleep(sleep_time)

        except Exception as e:
            _lcd_renderer_active = False

EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
_event_log = []
_event_log_lock = threading.Lock()

def _load_events():
    global _event_log
    try:
        if os.path.exists(EVENTS_FILE):
            import json
            with open(EVENTS_FILE, "r") as f:
                _event_log = json.load(f)
    except Exception:
        pass

def add_event(level, title, message, details=None):
    global _event_log
    now = int(time.time())
    with _event_log_lock:
        if _event_log and _event_log[0].get("title") == title and _event_log[0].get("message") == message and (now - _event_log[0].get("ts", 0) < 3600):
            return
        entry = {"ts": now, "level": level, "title": title, "message": message}
        if details is not None:
            entry["details"] = details
        _event_log.insert(0, entry)
        _event_log = _event_log[:100]
        try:
            with open(EVENTS_FILE, "w") as f:
                json.dump(_event_log, f)
        except Exception:
            pass

            print(f"[LCD] Active render loop error: {e}", flush=True)
            time.sleep(2)


_static_cache = {}  # {filepath: (bytes, etag, gzip_bytes)}
_static_cache_lock = threading.Lock()

def _load_static_file(fp):
    """Load a static file into cache with ETag and mtime validation."""
    with _static_cache_lock:
        try:
            mtime = __import__('os').path.getmtime(fp)
        except Exception:
            return None
        if fp in _static_cache:
            entry = _static_cache[fp]
            if len(entry) == 4 and entry[3] == mtime:
                return entry
        try:
            with open(fp, "rb") as f:
                content = f.read()
        except Exception:
            return None
        import hashlib
        etag = '"' + hashlib.md5(content).hexdigest()[:16] + '"'
        # Pre-compress if worth it (>1KB)
        gz_content = None
        if len(content) > 1024:
            import io, gzip
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=6) as gz:
                gz.write(content)
            gz_content = buf.getvalue()
        entry = (content, etag, gz_content, mtime)
        _static_cache[fp] = entry
        return entry


class Handler(BaseHTTPRequestHandler):

    def _handle_browse(self, query):
        from urllib.parse import parse_qs
        qs = parse_qs(query)
        target = qs.get("path", ["/mnt/user/"])[0]
        abs_target = os.path.abspath(target)
        if not abs_target.startswith("/mnt/"):
            abs_target = "/mnt/"
        if not abs_target.endswith("/"):
            abs_target += "/"
        dirs = []
        try:
            if abs_target != "/mnt/":
                dirs.append({"name": "..", "path": os.path.abspath(os.path.join(abs_target, "..")) + "/"})
            for entry in os.scandir(abs_target):
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": os.path.join(abs_target, entry.name) + "/"})
        except Exception:
            pass
        dirs = sorted(dirs, key=lambda d: (d["name"] != "..", d["name"].lower()))
        self._send(200, json.dumps({"current": abs_target, "dirs": dirs}).encode(), "application/json")

    def _handle_mkdir(self, query):
        from urllib.parse import parse_qs
        qs = parse_qs(query)
        target = qs.get("path", [""])[0]
        if target:
            abs_target = os.path.abspath(target)
            if abs_target.startswith("/mnt/"):
                try:
                    os.makedirs(abs_target, exist_ok=True)
                    self._send(200, b'{"status": "ok"}', "application/json")
                    return
                except Exception as e:
                    self._send(400, b'{"error": "creation failed"}', "application/json")
                    return
        self._send(400, b'{"error": "invalid path"}', "application/json")

    def _handle_copy_cancel(self):
        global _copy_abort_flag, _copy_confirm_event
        _copy_abort_flag = True
        _copy_confirm_event.set()
        self._send(200, b'{"status":"ok"}', "application/json")

    def _handle_copy_confirm(self, body=None):
        global _copy_overwrite_choice, _copy_confirm_event
        if body is None:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                body = self.rfile.read(length)
        if body:
            try:
                import json
                data = json.loads(body)
                _copy_overwrite_choice = data.get("action", "skip")
                _copy_confirm_event.set()
                self._send(200, b'{"status":"ok"}', "application/json")
                return
            except Exception:
                pass
        self._send(400, b'{"error":"invalid"}', "application/json")

    def _handle_buttons(self, body=None):
        import json
        state = {"enabled": False, "source": "/mnt/disks/", "dest": "/mnt/user/Media/"}
        if os.path.exists(BUTTON_CFG_FILE):
            try:
                with open(BUTTON_CFG_FILE, "r") as f:
                    state.update(json.load(f))
            except Exception: pass
            
        if body:
            try:
                data = json.loads(body)
                dest_val = str(data.get("dest", state["dest"])).strip()
                
                if "dest" in data:
                    if not os.path.exists(dest_val):
                        self._send(400, json.dumps({"error": f"Path does not exist: {dest_val}"}).encode(), "application/json")
                        return
                    if not dest_val.startswith("/mnt/"):
                        self._send(400, json.dumps({"error": "Path must be within /mnt/"}).encode(), "application/json")
                        return
                
                if "enabled" in data: state["enabled"] = bool(data["enabled"])
                if "source" in data: state["source"] = str(data["source"]).strip()
                if "dest" in data: state["dest"] = dest_val
                with open(BUTTON_CFG_FILE, "w") as f:
                    json.dump(state, f)
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
                return
            
        self._send(200, json.dumps(state).encode(), "application/json")

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        global _copy_abort_flag, _copy_confirm_event, _copy_overwrite_choice
        global _discovered_host_ip

        host_header = self.headers.get("Host", "")
        if host_header:
            client_ip = host_header.split(":")[0].strip()
            if re.fullmatch(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", client_ip):
                if not (client_ip.startswith("127.") or client_ip.startswith("172.") or client_ip == "0.0.0.0"):
                    _discovered_host_ip = client_ip

        parsed = urlparse(self.path)
        clean_path = parsed.path
        query = parsed.query

        if clean_path == "/api/stats/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            last_version = None
            try:
                while True:
                    data = collect()
                    ver = data.get("layout", {}).get("version", 0)
                    payload = json.dumps(data)
                    msg = f"data: {payload}\n\n"
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
                    if _ui_wake.wait(2.0):
                        _ui_wake.clear()
            except Exception:
                pass
            return

        if clean_path == "/api/events/clear":
            global _event_log
            with _event_log_lock:
                _event_log = []
                try:
                    with open(EVENTS_FILE, "w") as fw:
                        fw.write("[]")
                except: pass
            self._send(200, b'{"status":"ok"}', "application/json")
            return
        if clean_path == "/api/lcd_status":
            body = json.dumps({
                "enabled": ENABLE_FB,
                "fb_present": os.path.exists("/dev/fb0"),
                "fps": LCD_FPS,
                "active": _lcd_renderer_active
            }).encode()
            self._send(200, body, "application/json")
            return

        if clean_path == "/api/stats":
            body = json.dumps(collect()).encode()
            self._send(200, body, "application/json")
            return

        if clean_path == "/api/disk_detail":
            query_params = dict(qc.split("=") for qc in query.split("&") if "=" in qc)
            dev_name = query_params.get("dev", "sda")
            if not re.fullmatch(r"^(sd[a-z]{1,2}|nvme[0-9]+n[0-9]+)$", dev_name):
                self._send(400, b"Invalid device parameter.", "text/plain")
                return

            detail = fetch_disk_smart_detail(dev_name)
            self._send(200, json.dumps(detail).encode(), "application/json")
            return

        if clean_path == "/api/screen":
            self._send(200, json.dumps(get_screen_state()).encode(), "application/json")
            return


        if clean_path.startswith("/api/browse"):
            self._handle_browse(parsed.query)
            return


        if clean_path.startswith("/api/mkdir"):
            self._handle_mkdir(parsed.query)
            return


        if clean_path == "/api/copy/cancel":
            self._handle_copy_cancel()
            return

        if clean_path == "/api/copy/confirm":
            self._handle_copy_confirm(None)
            return

        if clean_path == "/api/buttons":
            self._handle_buttons(None)
            return

        if clean_path == "/api/fans":
            fan_cfg = {"profile": "auto", "manual_pct": 60, "ctrl_cpu_fan": False, "temp_min": 37, "temp_max": 50}
            if os.path.exists(FAN_STATE_FILE):
                try:
                    with open(FAN_STATE_FILE, "r") as f:
                        fan_cfg.update(json.load(f))
                except Exception:
                    pass
            self._send(200, json.dumps(fan_cfg).encode(), "application/json")
            return

        if clean_path == "/api/led":
            state = {
                "power": "on",
                "brightness": 25,
                "color": "25c2a0",
                "color2": "ff0055",
                "mode": "solid",
                "speed": 50,
                "reactive": True,
                "night_mode": False,
                "night_start": "23:00",
                "night_end": "07:00"
            }
            if os.path.exists(LED_STATE_FILE):
                try:
                    with open(LED_STATE_FILE, "r") as f:
                        state.update(json.load(f))
                except Exception:
                    pass
            self._send(200, json.dumps(state).encode(), "application/json")
            return

        if clean_path == "/api/layout":
            self._send(200, json.dumps(get_current_layout()).encode(), "application/json")
            return

        rel_path = "index.html" if clean_path in ("/", "") else clean_path.lstrip("/")
        fp = os.path.realpath(os.path.join(STATIC_DIR, rel_path))

        if not fp.startswith(STATIC_DIR + os.sep) and fp != os.path.join(STATIC_DIR, "index.html"):
            self._send(403, b"forbidden", "text/plain")
            return

        if os.path.isfile(fp):
            if fp.endswith(".html"):
                ctype = "text/html; charset=utf-8"
            elif fp.endswith(".css"):
                ctype = "text/css; charset=utf-8"
            elif fp.endswith(".js"):
                ctype = "application/javascript; charset=utf-8"
            elif fp.endswith(".png"):
                ctype = "image/png"
            elif fp.endswith(".jpg") or fp.endswith(".jpeg"):
                ctype = "image/jpeg"
            elif fp.endswith(".svg"):
                ctype = "image/svg+xml"
            else:
                ctype = "application/octet-stream"

            entry = _load_static_file(fp)
            if entry is None:
                self._send(404, b"not found", "text/plain")
                return
            content, etag, gz_content = entry[:3]

            if fp.endswith("index.html"):
                html_str = content.decode("utf-8")
                if "mode=lcd" in query:
                    html_str = html_str.replace('<body class="studio-workbench">', '<body class="studio-workbench lcd-direct">')
                content = html_str.encode("utf-8")
                etag = None  # Don't cache dynamic HTML
                gz_content = None

            # ETag check (skip for dynamic index.html)
            if etag:
                if_none_match = self.headers.get("If-None-Match", "")
                if if_none_match == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    return

            accept_enc = self.headers.get("Accept-Encoding", "")
            if gz_content and "gzip" in accept_enc:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(gz_content)))
                if etag:
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "max-age=3600")
                else:
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(gz_content)
            else:
                if etag:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self._send(200, content, ctype)
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        global _copy_abort_flag, _copy_confirm_event, _copy_overwrite_choice
        parsed = urlparse(self.path)
        clean_path = parsed.path

        if clean_path == "/api/screen":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw)
                cur = get_screen_state()
                if "brightness" in data:
                    cur["brightness"] = max(5, min(100, int(data["brightness"])))
                if "night_mode" in data:
                    cur["night_mode"] = bool(data["night_mode"])
                if "night_brightness" in data:
                    cur["night_brightness"] = max(0, min(100, int(data["night_brightness"])))
                if "night_start" in data:
                    cur["night_start"] = str(data["night_start"])
                if "night_end" in data:
                    cur["night_end"] = str(data["night_end"])

                with open(SCREEN_STATE_FILE, "w") as f:
                    json.dump(cur, f)

                in_screen_night = cur.get("night_mode", False) and is_in_time_window(cur.get("night_start", "23:00"), cur.get("night_end", "07:00"))
                target_bl = cur.get("night_brightness", 10) if in_screen_night else cur.get("brightness", 100)
                set_screen_brightness(target_bl)

                self._send(200, json.dumps({"status": "ok", **cur}).encode(), "application/json")
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            return


        if clean_path.startswith("/api/browse"):
            self._handle_browse(parsed.query)
            return


        if clean_path.startswith("/api/mkdir"):
            self._handle_mkdir(parsed.query)
            return


        if clean_path == "/api/copy/cancel":
            self._handle_copy_cancel()
            return

        if clean_path == "/api/copy/confirm":
            self._handle_copy_confirm(None)
            return

        if clean_path == "/api/buttons":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            self._handle_buttons(raw)
            return

        if clean_path == "/api/fans":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw)
                profile = data.get("profile", "auto")
                manual_pct = int(data.get("manual_pct", 60))
                ctrl_cpu_fan = bool(data.get("ctrl_cpu_fan", False))
                temp_min = max(25, min(50, int(data.get("temp_min", 37))))
                temp_max = max(temp_min + 5, min(75, int(data.get("temp_max", 50))))
                curve_points = data.get("curve_points", None)

                if profile == "auto":
                    for k in _fan_state_tracker:
                        _fan_state_tracker[k]["last_up_time"] = 0.0
                    ok = True
                    pct = 60
                else:
                    ok = set_fan_pwm(profile, manual_pct, ctrl_cpu_fan=ctrl_cpu_fan)
                    pct = manual_pct

                state_to_save = {
                    "profile": profile,
                    "manual_pct": pct,
                    "ctrl_cpu_fan": ctrl_cpu_fan,
                    "temp_min": temp_min,
                    "temp_max": temp_max
                }
                if curve_points:
                    state_to_save["curve_points"] = curve_points
                with open(FAN_STATE_FILE, "w") as f:
                    json.dump(state_to_save, f)
                self._send(200, json.dumps({"status": "ok" if ok else "unsupported", **state_to_save}).encode(), "application/json")
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            return

        if clean_path == "/api/led":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw)
                cur_led = {}
                if os.path.exists(LED_STATE_FILE):
                    try:
                        with open(LED_STATE_FILE, "r") as f:
                            cur_led = json.load(f)
                    except Exception:
                        pass
                cur_led.update(data)
                ok, msg = apply_led_state(cur_led)
                with open(LED_STATE_FILE, "w") as f:
                    json.dump(cur_led, f)
                self._send(200, json.dumps({"status": "ok" if ok else "error", "message": msg, **cur_led}).encode(), "application/json")
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            return

        if clean_path == "/api/layout":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw)
                data["version"] = int(time.time() * 1000)
                with open(DASH_LAYOUT_FILE, "w") as f:
                    json.dump(data, f)

                with _cached_stats_lock:
                    if _cached_stats:
                        _cached_stats["layout"] = data

                self._send(200, json.dumps({"status": "ok", "layout": data}).encode(), "application/json")
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            return

        self._send(404, b"not found", "text/plain")


if __name__ == "__main__":
    read_cpu_util()
    _layout_dir = os.path.dirname(DASH_LAYOUT_FILE)
    if _layout_dir:
        os.makedirs(_layout_dir, exist_ok=True)
    port = int(os.environ.get("PORT", "8082"))
    print(f"ZettNAS LCD dashboard on :{port}", flush=True)
    _load_events()
    read_ip()  # Pre-populate IP cache at startup
    detect_chassis_model()  # Pre-populate chassis model cache

    if os.path.exists(LED_STATE_FILE):
        try:
            with open(LED_STATE_FILE, "r") as f:
                apply_led_state(json.load(f))
        except Exception:
            pass

    threading.Thread(target=stats_collector_daemon, daemon=True).start()
    threading.Thread(target=button_listener_daemon, daemon=True).start()
    threading.Thread(target=render_lcd_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
