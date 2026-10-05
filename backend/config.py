import os
import json
import socket
import hashlib
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
STORED_PASSWORD_HASH = hashlib.sha256(WEB_PASSWORD.encode()).hexdigest()
ZETTNAS_USERNAME = "admin"
ZETTNAS_EMAIL = ""
SESSION_TTL = 30 * 86400  # 30 days

def is_using_default_password() -> bool:
    default_hash = hashlib.sha256(b"admin").hexdigest()
    return STORED_PASSWORD_HASH == default_hash

def _load_security():
    global STORED_PASSWORD_HASH, ZETTNAS_USERNAME, ZETTNAS_EMAIL
    if os.path.exists(SECURITY_FILE):
        try:
            with open(SECURITY_FILE, "r") as f:
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
            with open(ident_file, "r") as f:
                for line in f:
                    if line.startswith("NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
    except (OSError, IndexError):
        pass
    try:
        return socket.gethostname().split(".")[0].upper()
    except Exception:
        return "NAS"
