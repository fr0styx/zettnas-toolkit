import json
import logging
import os
import secrets
import socket
import time

from backend.settings import test_mode

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("ZettNAS")

from backend.settings import load_settings  # noqa: E402

# Typed settings (ARCH-9): unusable values keep their default and are reported here
SETTINGS, SETTINGS_PROBLEMS = load_settings()
for _problem in SETTINGS_PROBLEMS:
    logger.warning(f"[config] {_problem}")

# ---- Host paths & mounts ----
HOST_PROC = SETTINGS.host_proc
HOST_SYS = SETTINGS.host_sys
HOST_DEV = SETTINGS.host_dev
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
DISKS = SETTINGS.disks
OS_NVME = SETTINGS.os_nvme
SYNC_ROUTE_THREADS = SETTINGS.sync_route_threads
STATIC_DIR = os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"))

# ---- Runtime & tuning ----
ENABLE_FB = SETTINGS.enable_fb
LCD_FPS = SETTINGS.lcd_fps
SMART_POLL_INTERVAL_HDD = SETTINGS.smart_poll_hdd
SMART_IDLE_ADAPTIVE = SETTINGS.smart_idle_adaptive
SMART_IDLE_POLL = SETTINGS.smart_idle_poll
SMART_POLL_INTERVAL_NVME = SETTINGS.smart_poll_nvme
APP_MEMORY_WARN_MB = SETTINGS.app_memory_warn_mb
LCD_RENDERER = SETTINGS.lcd_renderer
UPDATE_SIGNATURES = SETTINGS.update_signatures
LCD_FORMAT = SETTINGS.lcd_format  # jpeg: cheaper to encode than png (PERF-2)
PORT = SETTINGS.port
SHOW_OS_DISK = SETTINGS.show_os_disk


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
# How long the security audit log keeps an event (B11, SEC-32); 0 keeps everything
AUDIT_RETENTION_DAYS = max(0, int(os.environ.get("ZETTNAS_AUDIT_RETENTION_DAYS", "365") or 365))
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
SFTP_PORT = SETTINGS.sftp_port
TAILSCALE_STATE_DIR = os.environ.get("TAILSCALE_STATE_DIR", os.path.join(DATA_DIR, "tailscale"))
UPDATE_CHANNEL = SETTINGS.update_channel
UPS_MODE = SETTINGS.ups_mode.lower()
NUT_HOST = SETTINGS.nut_host
NUT_PORT = SETTINGS.nut_port
NUT_NAME = SETTINGS.nut_name
LCD_SLEEP_SEC = SETTINGS.lcd_sleep_sec

# ---- Security & Auth ----
from backend.passwords import hash_password, verify_password  # noqa: E402

RAW_DOCKER_SOCK = "/var/run/docker.sock"

# "full" ships VMs and the LCD renderer; "core" leaves them out (OPS-11)
IMAGE_VARIANT = SETTINGS.image_variant


def variant_tag(tag: str) -> str:
    """The image tag for this variant: latest -> latest-core on the core image."""
    return f"{tag}-core" if IMAGE_VARIANT == "core" and not tag.endswith("-core") else tag


def docker_sock() -> str:
    """The Docker API socket: the allow-list proxy when it runs (SEC-09), else the raw socket."""
    return os.environ.get("ZETTNAS_DOCKER_SOCK") or RAW_DOCKER_SOCK


# No shared default: empty means "generate a first-time password" (users_db bootstrap).
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "")


def initial_password_hash(password: str) -> str:
    """Hash of the configured first-time password, or "" when none is configured."""
    return hash_password(password) if password else ""


STORED_PASSWORD_HASH = initial_password_hash(WEB_PASSWORD)
ZETTNAS_USERNAME = "admin"
ZETTNAS_EMAIL = ""
SESSION_TTL = 7 * 86400  # a sign-in without "remember me" lasts a week (SEC-12)
SESSION_IDLE_SECS = 3 * 86400  # ... and ends after three days unused
REMEMBERED_SESSION_IDLE_SECS = 14 * 86400  # "remember me": 30 days, ends after two weeks unused
MIN_PASSWORD_LENGTH = 8

# Reverse Proxy SSO (Sprint 3)
TRUSTED_PROXIES = list(SETTINGS.trusted_proxies)
ENABLE_PROXY_SSO = SETTINGS.enable_proxy_sso

# Random per-process token handed only to the headless LCD renderer.
# Replaces the old "trust every request from 127.0.0.1" bypass.
LCD_INTERNAL_TOKEN = secrets.token_urlsafe(32)

# Persistent Cryptographic Secret Key for HMAC signing and session protection
SECRET_KEY_FILE = os.path.join(DATA_DIR, "secret.key")


def _secret_key_from_file() -> str:
    """SECRET_KEY_FILE (a Docker or Compose secret) or $CREDENTIALS_DIRECTORY/secret_key (a systemd
    credential): the key kept apart from the data it protects (SEC-35)."""
    paths = [os.environ.get("SECRET_KEY_FILE", "").strip()]
    creds = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if creds:
        paths.append(os.path.join(creds, "secret_key"))
    for path in filter(None, paths):
        try:
            with open(path, encoding="utf-8") as f:
                key = f.read().strip()
        except OSError as e:
            raise RuntimeError(f"Cannot read the secret key from {path} ({e}).") from e
        if key:
            return key
    return ""


def _get_or_create_secret_key() -> str:
    env_key = os.environ.get("SECRET_KEY", "").strip() or _secret_key_from_file()
    if env_key:
        return env_key
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL  # never over an existing key (ARC-20)
    if os.path.exists(SECRET_KEY_FILE):
        try:
            with open(SECRET_KEY_FILE, encoding="utf-8") as f:
                k = f.read().strip()
        except OSError as e:
            # It seals the two-factor secrets and backup passphrases: replacing it would lose them.
            raise RuntimeError(
                f"Cannot read {SECRET_KEY_FILE} ({e}). It was not replaced. Fix its permissions or "
                "restore it from a backup, then start ZettNAS again."
            ) from e
        if k:
            return k
        flags = os.O_WRONLY | os.O_TRUNC  # an empty file holds nothing to lose

    new_key = secrets.token_hex(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        fd = os.open(SECRET_KEY_FILE, flags, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            f.write(new_key)
    except OSError as e:
        logger.warning(f"Failed to persist {SECRET_KEY_FILE}: {e}")
    return new_key


SECRET_KEY = _get_or_create_secret_key()

# Universal WebDAV & Remote Storage (Sprint 4)
REMOTES_PATH = SETTINGS.remotes_path
WEBDAV_PORT = SETTINGS.webdav_port
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
ENABLE_API_DOCS = SETTINGS.enable_api_docs


# Reject request bodies larger than this (wallpaper uploads are base64 JSON).
MAX_BODY_BYTES = SETTINGS.max_body_mb * 1024 * 1024
MAX_WALLPAPER_BYTES = SETTINGS.max_wallpaper_mb * 1024 * 1024
MAX_UPLOAD_BYTES = SETTINGS.max_upload_gb * 1024 * 1024 * 1024

# ---- Fan safety ----
FAN_MIN_PWM = 58  # Lowest PWM the chassis fans reliably spin at
FAN_MAX_PWM = 183  # Chassis maximum
FAN_FAILSAFE_PWM = SETTINGS.fan_failsafe_pwm
FAN_KICKSTART_PWM = SETTINGS.fan_kickstart_pwm
FAN_KICKSTART_SECS = SETTINGS.fan_kickstart_secs
FAN_SPINUP_GRACE_SECS = SETTINGS.fan_spinup_grace_secs
FAN_DISK_HOLD_SECS = SETTINGS.fan_disk_hold_secs
FAN_CPU_HOLD_SECS = SETTINGS.fan_cpu_hold_secs
ZERO_RPM_ENABLED = SETTINGS.zero_rpm_enabled
FAN_ZERO_RPM_STOP_DELAY = SETTINGS.zero_rpm_stop_delay
FAN_ZERO_RPM_DEFAULT_NVME_CEILING = SETTINGS.zero_rpm_nvme_ceiling
FAN_ZERO_RPM_DEFAULT_STOP_TEMP = SETTINGS.zero_rpm_stop_temp
FAN_ZERO_RPM_DEFAULT_START_TEMP = SETTINGS.zero_rpm_start_temp
HDD_CRITICAL_TEMP = SETTINGS.hdd_critical_temp
NVME_CRITICAL_TEMP = SETTINGS.nvme_critical_temp
HDD_WARN_TEMP = SETTINGS.hdd_warn_temp
NVME_WARN_TEMP = SETTINGS.nvme_warn_temp
COLLECTOR_WATCHDOG_SECS = SETTINGS.collector_watchdog_secs

_default_pw_cache = {"hash": None, "value": False, "file": False, "file_at": float("-inf")}
DEFAULT_PW_FILE_RECHECK_SECS = 30.0


# Sessions that must change their password are limited to the password-change
# endpoints (SEC-23). Only the test suite turns this off.
# Show user tiles on the login screen (SEC-19). Off by default: it lists account names
# to anyone who can open the login page.
LOGIN_USER_CHOOSER = SETTINGS.login_user_chooser

# Extra origins allowed to send cookie-authenticated writes (e.g. "https://nas.example.com"),
# for reverse proxies that don't pass the original Host. Comma-separated.
CSRF_TRUSTED_ORIGINS = list(SETTINGS.csrf_trusted_origins)

ENFORCE_PASSWORD_CHANGE = not (test_mode() and os.environ.get("ZETTNAS_ENFORCE_PASSWORD_CHANGE") == "0")


def initial_password_file() -> str:
    """Where a fresh install keeps its generated first-time admin password until it is changed."""
    return os.path.join(DATA_DIR, "initial-admin-password")


def is_using_default_password() -> bool:
    """True while the admin still has 'admin' or the generated first-time password.

    The 'admin' check is cached per hash (scrypt is slow by design).
    """
    if _default_pw_cache["hash"] != STORED_PASSWORD_HASH:
        _default_pw_cache["hash"] = STORED_PASSWORD_HASH
        _default_pw_cache["value"] = verify_password("admin", STORED_PASSWORD_HASH)
        _default_pw_cache["file_at"] = float("-inf")
    now = time.monotonic()
    if now - _default_pw_cache["file_at"] >= DEFAULT_PW_FILE_RECHECK_SECS:
        _default_pw_cache["file"] = os.path.exists(initial_password_file())
        _default_pw_cache["file_at"] = now
    return bool(_default_pw_cache["value"]) or bool(_default_pw_cache["file"])


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
    sock_path = docker_sock()
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
