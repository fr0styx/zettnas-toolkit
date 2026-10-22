import json
import logging
import os
import secrets
import socket
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ZettNAS")

# ---- Host paths & mounts ----
HOST_PROC = os.environ.get("HOST_PROC", "/host/proc")
HOST_SYS = os.environ.get("HOST_SYS", "/host/sys")
HOST_DEV = os.environ.get("HOST_DEV", "/host/dev")
_env_pool = os.environ.get("STORAGE_POOL_PATH") or os.environ.get("POOL_PATH")
if not _env_pool:
    if os.path.exists("/mnt/user") and (
        os.path.ismount("/mnt/user") or (os.path.isdir("/mnt/user") and len(os.listdir("/mnt/user")) > 1)
    ):
        POOL_PATH = "/mnt/user"
    else:
        # Check ZettOS pool directories across all Zettlab appliance models (D4, D6, D6U, D8U)
        _found_pool = None
        for _zp in (
            "/zettos/pool/1",
            "/zettos/pool/data",
            "/zettos/pool/storage",
            "/zettos/pool/2",
            "/zettos/pool",
        ):
            if os.path.exists(_zp) and os.path.isdir(_zp):
                _found_pool = _zp
                break
        if _found_pool:
            POOL_PATH = _found_pool
        elif os.path.exists("/mnt/storage"):
            POOL_PATH = "/mnt/storage"
        else:
            POOL_PATH = "/mnt/user"
elif (
    _env_pool == "/mnt/storage"
    and os.path.exists("/mnt/user")
    and (os.path.ismount("/mnt/user") or (os.path.isdir("/mnt/user") and len(os.listdir("/mnt/user")) > 1))
):
    POOL_PATH = "/mnt/user"
elif _env_pool == "/mnt/storage" and not (
    os.path.exists("/mnt/user")
    and (os.path.ismount("/mnt/user") or (os.path.isdir("/mnt/user") and len(os.listdir("/mnt/user")) > 1))
):
    _found_pool = None
    for _zp in (
        "/zettos/pool/1",
        "/zettos/pool/data",
        "/zettos/pool/storage",
        "/zettos/pool/2",
        "/zettos/pool",
    ):
        if os.path.exists(_zp) and os.path.isdir(_zp):
            _found_pool = _zp
            break
    if _found_pool:
        POOL_PATH = _found_pool
    else:
        POOL_PATH = _env_pool
else:
    POOL_PATH = _env_pool
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
def _default_data_dir() -> str:
    if "DATA_DIR" in os.environ:
        return os.environ["DATA_DIR"]
    if os.path.exists("/app/data") or (os.path.exists("/app") and os.access("/app", os.W_OK)):
        return "/app/data"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, "data")


DATA_DIR = _default_data_dir()
DB_PATH = os.path.join(DATA_DIR, "history.db")
USERS_DB_PATH = os.environ.get("USERS_DB_PATH", os.path.join(DATA_DIR, "users.db"))
LED_STATE_FILE = os.path.join(DATA_DIR, "led_state.json")
DASH_LAYOUT_FILE = os.environ.get("LAYOUT_PATH", os.path.join(DATA_DIR, "dash_layout.json"))
FAN_STATE_FILE = os.path.join(DATA_DIR, "fan_state.json")
SCREEN_STATE_FILE = os.path.join(DATA_DIR, "screen_state.json")
EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
BUTTON_CFG_FILE = os.path.join(DATA_DIR, "button_state.json")
SECURITY_FILE = os.path.join(DATA_DIR, "security.json")
SMART_SCHEDULE_FILE = os.path.join(DATA_DIR, "smart_schedule.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
WALLPAPER_CONFIG_FILE = os.path.join(DATA_DIR, "wallpaper_config.json")
WALLPAPERS_DIR = os.path.join(DATA_DIR, "wallpapers")
CLIENT_PREFS_FILE = os.path.join(DATA_DIR, "client_preferences.json")
UPS_CONFIG_FILE = os.path.join(DATA_DIR, "ups_config.json")
NETWORK_CONFIG_FILE = os.path.join(DATA_DIR, "network_config.json")
BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(DATA_DIR, "backups"))
VM_ISO_DIR = os.environ.get("VM_ISO_DIR", os.path.join(DATA_DIR, "vms", "isos"))
SFTP_PORT = int(os.environ.get("SFTP_PORT", "2222"))
TAILSCALE_STATE_DIR = os.environ.get("TAILSCALE_STATE_DIR", os.path.join(DATA_DIR, "tailscale"))
UPDATE_CHANNEL = os.environ.get("UPDATE_CHANNEL", "stable").lower()
UPS_MODE = os.environ.get("UPS_MODE", "auto").lower()
NUT_HOST = os.environ.get("NUT_HOST", "127.0.0.1")
NUT_PORT = int(os.environ.get("NUT_PORT", "3493"))
NUT_NAME = os.environ.get("NUT_NAME", "ups")
LCD_SLEEP_SEC = int(os.environ.get("LCD_SLEEP_SEC", "300"))

# ---- Security & Auth ----
from backend.passwords import hash_password, verify_password  # noqa: E402

WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
STORED_PASSWORD_HASH = hash_password(WEB_PASSWORD)
ZETTNAS_USERNAME = "admin"
ZETTNAS_EMAIL = ""
SESSION_TTL = 30 * 86400  # 30 days
MIN_PASSWORD_LENGTH = 8

# Reverse Proxy SSO (Sprint 3)
TRUSTED_PROXIES = [p.strip() for p in os.environ.get("TRUSTED_PROXIES", "127.0.0.1,::1").split(",") if p.strip()]
ENABLE_PROXY_SSO = os.environ.get("ENABLE_PROXY_SSO", "0").lower() in ("1", "true", "yes")

# Random per-process token handed only to the headless LCD renderer.
# Replaces the old "trust every request from 127.0.0.1" bypass.
LCD_INTERNAL_TOKEN = secrets.token_urlsafe(32)

# Persistent Cryptographic Secret Key for HMAC signing and session protection
SECRET_KEY_FILE = os.path.join(DATA_DIR, "secret.key")


def _get_or_create_secret_key() -> str:
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    if os.path.exists(SECRET_KEY_FILE):
        try:
            with open(SECRET_KEY_FILE, encoding="utf-8") as f:
                k = f.read().strip()
                if k:
                    return k
        except OSError as e:
            logger.warning(f"Failed to read {SECRET_KEY_FILE}: {e}")

    new_key = secrets.token_hex(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(SECRET_KEY_FILE, flags, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            f.write(new_key)
    except OSError as e:
        logger.warning(f"Failed to persist {SECRET_KEY_FILE}: {e}")
    return new_key


SECRET_KEY = _get_or_create_secret_key()

# Universal WebDAV & Remote Storage (Sprint 4)
REMOTES_PATH = os.environ.get("REMOTES_PATH", "/mnt/remotes")
WEBDAV_PORT = int(os.environ.get("WEBDAV_PORT", "8084"))
WEBDAV_CONFIG_FILE = os.path.join(DATA_DIR, "webdav_config.json")
RCLONE_CONFIG_FILE = os.path.join(DATA_DIR, "rclone", "rclone.conf")
RCLONE_CACHE_DIR = os.path.join(DATA_DIR, "rclone", "vfs_cache")

# Folder browser / mkdir / copy destination are confined to these roots.
_default_roots = f"{POOL_PATH},{REMOTES_PATH}" if os.environ.get("BROWSE_ROOTS") is None else os.environ["BROWSE_ROOTS"]
_roots_list = [p.strip() for p in _default_roots.split(",") if p.strip()]
for _cand in (
    "/mnt",
    "/mnt/user",
    "/mnt/storage",
    "/mnt/remotes",
    "/mnt/cache",
    "/mnt/disks",
    "/boot",
    "/zettos",
    "/zettos/pool",
):
    if os.path.exists(_cand) and _cand not in _roots_list:
        _roots_list.append(_cand)
ALLOWED_BROWSE_ROOTS = _roots_list

# OpenAPI docs (/docs, /redoc, /openapi.json): disabled unless explicitly enabled,
# and always require authentication when enabled.
ENABLE_API_DOCS = os.environ.get("ENABLE_API_DOCS", "0") == "1"


# Reject request bodies larger than this (wallpaper uploads are base64 JSON).
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_MB", "16")) * 1024 * 1024
MAX_WALLPAPER_BYTES = int(os.environ.get("MAX_WALLPAPER_MB", "10")) * 1024 * 1024
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_GB", "64")) * 1024 * 1024 * 1024

# ---- Fan safety ----
FAN_MIN_PWM = 58  # Lowest PWM the chassis fans reliably spin at
FAN_MAX_PWM = 183  # Chassis maximum
FAN_FAILSAFE_PWM = int(os.environ.get("FAN_FAILSAFE_PWM", "150"))
FAN_KICKSTART_PWM = int(os.environ.get("FAN_KICKSTART_PWM", "150"))
FAN_KICKSTART_SECS = float(os.environ.get("FAN_KICKSTART_SECS", "2.0"))
FAN_SPINUP_GRACE_SECS = float(os.environ.get("FAN_SPINUP_GRACE_SECS", "6.0"))
FAN_DISK_HOLD_SECS = int(os.environ.get("FAN_DISK_HOLD_SECS", "30"))
FAN_CPU_HOLD_SECS = int(os.environ.get("FAN_CPU_HOLD_SECS", "30"))
ZERO_RPM_ENABLED = os.environ.get("ZERO_RPM_ENABLED", "0").lower() in ("1", "true", "yes")
FAN_ZERO_RPM_STOP_DELAY = int(os.environ.get("FAN_ZERO_RPM_STOP_DELAY", "30"))
FAN_ZERO_RPM_DEFAULT_NVME_CEILING = int(
    os.environ.get("ZERO_RPM_NVME") or os.environ.get("FAN_ZERO_RPM_NVME_CEILING", "50")
)
FAN_ZERO_RPM_DEFAULT_STOP_TEMP = int(os.environ.get("ZERO_RPM_TEMP") or os.environ.get("FAN_ZERO_RPM_STOP_TEMP", "34"))
FAN_ZERO_RPM_DEFAULT_START_TEMP = int(os.environ.get("FAN_ZERO_RPM_START_TEMP", "38"))
HDD_CRITICAL_TEMP = int(os.environ.get("HDD_CRITICAL_TEMP", "55"))
NVME_CRITICAL_TEMP = int(os.environ.get("NVME_CRITICAL_TEMP", "75"))
HDD_WARN_TEMP = int(os.environ.get("HDD_WARN_TEMP", "50"))
NVME_WARN_TEMP = int(os.environ.get("NVME_WARN_TEMP", "70"))
COLLECTOR_WATCHDOG_SECS = int(os.environ.get("COLLECTOR_WATCHDOG_SECS", "20"))

_default_pw_cache = {"hash": None, "value": False}


# Sessions that must change their password are limited to the password-change
# endpoints (SEC-23). Only the test suite turns this off.
# Show user tiles on the login screen (SEC-19). Off by default: it lists account names
# to anyone who can open the login page.
LOGIN_USER_CHOOSER = os.environ.get("LOGIN_USER_CHOOSER", "0").lower() in ("1", "true", "yes", "on")

# Extra origins allowed to send cookie-authenticated writes (e.g. "https://nas.example.com"),
# for reverse proxies that don't pass the original Host. Comma-separated.
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

ENFORCE_PASSWORD_CHANGE = not (
    os.environ.get("TESTING") == "1" and os.environ.get("ZETTNAS_ENFORCE_PASSWORD_CHANGE") == "0"
)


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


def _is_container_id(val: str | None) -> bool:
    """Checks whether a string resembles an auto-generated Docker/container ID
    (12 to 64 hexadecimal characters, e.g. '425dae47b7b9').
    """
    if not val:
        return True
    s = val.strip()
    return bool(12 <= len(s) <= 64 and all(c in "0123456789abcdefABCDEF" for c in s))


_cached_server_hostname: str | None = None
_cached_server_hostname_ts: float = 0.0


def clear_hostname_cache():
    """Resets the cached server hostname (useful for tests and dynamic updates)."""
    global _cached_server_hostname, _cached_server_hostname_ts
    _cached_server_hostname = None
    _cached_server_hostname_ts = 0.0


def get_server_hostname() -> str:
    """Discovers the true human-friendly server hostname.
    Resolution order:
    1. Explicit NAS_NAME environment variable (if not 'NAS' or container ID)
    2. Host /etc/hostname (/host/etc/hostname or /etc/hostname)
    3. Unraid config files (/boot/config/ident.cfg, /var/local/emhttp/var.ini, etc.)
    4. Docker daemon engine info via /var/run/docker.sock
    5. Local socket.gethostname() if not a container hex ID
    6. Explicit NAS_NAME if 'NAS'
    7. Fallback: 'ZettNAS'
    """
    global _cached_server_hostname, _cached_server_hostname_ts

    now = time.time()
    if _cached_server_hostname and (now - _cached_server_hostname_ts < 60):
        return _cached_server_hostname

    # 1. Environment variable override (if customized and not a container hex ID)
    env_name = os.environ.get("NAS_NAME", "").strip()
    if env_name and not _is_container_id(env_name) and env_name.upper() != "NAS":
        _cached_server_hostname = env_name
        _cached_server_hostname_ts = now
        return env_name

    # 2. Unraid ident files (primary appliance NAS identity)
    unraid_paths = (
        "/boot/config/ident.cfg",
        "/host/boot/config/ident.cfg",
        "/var/local/emhttp/var.ini",
        "/host/var/local/emhttp/var.ini",
        "/etc/unraid-ident.cfg",
    )
    for u_path in unraid_paths:
        try:
            if os.path.exists(u_path):
                with open(u_path, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("NAME="):
                            parsed = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if parsed and not _is_container_id(parsed):
                                _cached_server_hostname = parsed
                                _cached_server_hostname_ts = now
                                return parsed
        except OSError:
            pass

    # 3. Host /etc/hostname (/host/etc/hostname or /etc/hostname)
    for h_path in ("/host/etc/hostname", "/etc/hostname"):
        try:
            if os.path.exists(h_path):
                with open(h_path, encoding="utf-8") as f:
                    content = f.read().strip()
                    if content and not _is_container_id(content):
                        _cached_server_hostname = content
                        _cached_server_hostname_ts = now
                        return content
        except OSError:
            pass

    # 4. Docker daemon via Unix Domain Socket
    sock_path = "/var/run/docker.sock"
    if os.path.exists(sock_path):
        try:
            import httpx

            transport = httpx.HTTPTransport(uds=sock_path)
            with httpx.Client(transport=transport, timeout=0.8) as client:
                res = client.get("http://docker/info")
                if res.status_code == 200:
                    d_name = res.json().get("Name", "").strip()
                    if d_name and not _is_container_id(d_name):
                        _cached_server_hostname = d_name
                        _cached_server_hostname_ts = now
                        return d_name
        except Exception:
            logger.debug("backend.config.get_server_hostname: ignored error", exc_info=True)

    # 5. Local socket hostname (if not a raw container ID)
    try:
        raw_sock = socket.gethostname().split(".")[0].strip()
        if raw_sock and not _is_container_id(raw_sock):
            _cached_server_hostname = raw_sock
            _cached_server_hostname_ts = now
            return raw_sock
    except Exception:
        logger.debug("backend.config.get_server_hostname: ignored error", exc_info=True)

    # 6. Fallback to env_name if set to "NAS", otherwise "ZettNAS"
    fallback = env_name if env_name and not _is_container_id(env_name) else "ZettNAS"
    _cached_server_hostname = fallback
    _cached_server_hostname_ts = now
    return fallback
