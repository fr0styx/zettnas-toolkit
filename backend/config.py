import json
import logging
import os
import secrets
import socket

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ZettNAS")

# ---- Host paths & mounts ----
HOST_PROC = os.environ.get("HOST_PROC", "/host/proc")
HOST_SYS = os.environ.get("HOST_SYS", "/host/sys")
HOST_DEV = os.environ.get("HOST_DEV", "/host/dev")
POOL_PATH = os.environ.get("POOL_PATH", "/mnt/user")
DISKS = os.environ.get("DISKS", "")
OS_NVME = os.environ.get("OS_NVME", "nvme1n1")
STATIC_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"))

# ---- Runtime & tuning ----
ENABLE_FB = os.environ.get("ENABLE_FB", "1") == "1"
LCD_FPS = int(float(os.environ.get("LCD_FPS", "5")))
SMART_POLL_INTERVAL_HDD = int(os.environ.get("SMART_POLL_HDD", "45"))
SMART_POLL_INTERVAL_NVME = int(os.environ.get("SMART_POLL_NVME", "15"))
LCD_FORMAT = os.environ.get("LCD_FORMAT", "png").lower()
PORT = int(os.environ.get("PORT", "8082"))
SHOW_OS_DISK = os.environ.get("SHOW_OS_DISK", "1") == "1"

# ---- Data directories & persistent files ----
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "history.db")
LED_STATE_FILE = os.path.join(DATA_DIR, "led_state.json")
DASH_LAYOUT_FILE = os.environ.get("LAYOUT_PATH", os.path.join(DATA_DIR, "dash_layout.json"))
FAN_STATE_FILE = os.path.join(DATA_DIR, "fan_state.json")
SCREEN_STATE_FILE = os.path.join(DATA_DIR, "screen_state.json")
EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
BUTTON_CFG_FILE = os.path.join(DATA_DIR, "button_state.json")
SECURITY_FILE = os.path.join(DATA_DIR, "security.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
WALLPAPER_CONFIG_FILE = os.path.join(DATA_DIR, "wallpaper_config.json")
WALLPAPERS_DIR = os.path.join(DATA_DIR, "wallpapers")

# ---- Security & Auth ----
from backend.passwords import hash_password, verify_password  # noqa: E402

WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
STORED_PASSWORD_HASH = hash_password(WEB_PASSWORD)
ZETTNAS_USERNAME = "admin"
ZETTNAS_EMAIL = ""
SESSION_TTL = 30 * 86400  # 30 days
MIN_PASSWORD_LENGTH = 8

# Random per-process token handed only to the headless LCD renderer.
# Replaces the old "trust every request from 127.0.0.1" bypass.
LCD_INTERNAL_TOKEN = secrets.token_urlsafe(32)

# Folder browser / mkdir / copy destination are confined to these roots.
ALLOWED_BROWSE_ROOTS = [p.strip() for p in os.environ.get("BROWSE_ROOTS", POOL_PATH).split(",") if p.strip()]

# OpenAPI docs (/docs, /redoc, /openapi.json): disabled unless explicitly enabled,
# and always require authentication when enabled.
ENABLE_API_DOCS = os.environ.get("ENABLE_API_DOCS", "0") == "1"

# Reject request bodies larger than this (wallpaper uploads are base64 JSON).
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_MB", "16")) * 1024 * 1024
MAX_WALLPAPER_BYTES = int(os.environ.get("MAX_WALLPAPER_MB", "10")) * 1024 * 1024

# ---- Fan safety ----
FAN_MIN_PWM = 58  # Lowest PWM the chassis fans reliably spin at
FAN_MAX_PWM = 183  # Chassis maximum
FAN_FAILSAFE_PWM = int(os.environ.get("FAN_FAILSAFE_PWM", "150"))
FAN_KICKSTART_PWM = int(os.environ.get("FAN_KICKSTART_PWM", "150"))
FAN_KICKSTART_SECS = float(os.environ.get("FAN_KICKSTART_SECS", "2.0"))
FAN_SPINUP_GRACE_SECS = float(os.environ.get("FAN_SPINUP_GRACE_SECS", "6.0"))
FAN_ZERO_RPM_STOP_DELAY = int(os.environ.get("FAN_ZERO_RPM_STOP_DELAY", "180"))
FAN_ZERO_RPM_DEFAULT_NVME_CEILING = int(os.environ.get("FAN_ZERO_RPM_NVME_CEILING", "50"))
FAN_ZERO_RPM_DEFAULT_STOP_TEMP = int(os.environ.get("FAN_ZERO_RPM_STOP_TEMP", "34"))
FAN_ZERO_RPM_DEFAULT_START_TEMP = int(os.environ.get("FAN_ZERO_RPM_START_TEMP", "38"))
HDD_CRITICAL_TEMP = int(os.environ.get("HDD_CRITICAL_TEMP", "55"))
NVME_CRITICAL_TEMP = int(os.environ.get("NVME_CRITICAL_TEMP", "75"))
HDD_WARN_TEMP = int(os.environ.get("HDD_WARN_TEMP", "50"))
NVME_WARN_TEMP = int(os.environ.get("NVME_WARN_TEMP", "70"))
COLLECTOR_WATCHDOG_SECS = int(os.environ.get("COLLECTOR_WATCHDOG_SECS", "20"))

_default_pw_cache = {"hash": None, "value": False}


def is_using_default_password() -> bool:
    """True if the stored hash matches 'admin'. Cached per hash (scrypt is slow by design)."""
    if _default_pw_cache["hash"] != STORED_PASSWORD_HASH:
        _default_pw_cache["hash"] = STORED_PASSWORD_HASH
        _default_pw_cache["value"] = verify_password("admin", STORED_PASSWORD_HASH)
    return _default_pw_cache["value"]


def _load_security():
    global STORED_PASSWORD_HASH, ZETTNAS_USERNAME, ZETTNAS_EMAIL
    if os.path.exists(SECURITY_FILE):
        try:
            with open(SECURITY_FILE) as f:
                sec = json.load(f)
                if "password_hash" in sec:
                    STORED_PASSWORD_HASH = sec["password_hash"]
                if "username" in sec:
                    ZETTNAS_USERNAME = sec["username"]
                if "email" in sec:
                    ZETTNAS_EMAIL = sec["email"]
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load security.json: {e}")


def get_server_hostname():
    name = os.environ.get("NAS_NAME")
    if name:
        return name
    try:
        ident_file = "/etc/unraid-ident.cfg"
        if os.path.exists(ident_file):
            with open(ident_file) as f:
                for line in f:
                    if line.startswith("NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
    except (OSError, IndexError):
        pass
    try:
        return socket.gethostname().split(".")[0].upper()
    except Exception:
        return "NAS"
