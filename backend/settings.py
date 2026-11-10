"""Typed settings from environment variables (ARCH-9).

Every operator setting is declared once here with its type, default, limits and a line of
help. A value that can't be used (a port of "abc", an LCD rate of 500) falls back to the
default with a warning that names the variable, instead of stopping Kiboto at startup with a
traceback. backend.config reads its constants from here; docs/CONFIGURATION.md is generated
from these declarations (python -m backend.settings --markdown) and a test keeps it in sync.
"""

import dataclasses
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field

# Written by the release image's build (Dockerfile); environment variables can't create it.
RELEASE_MARKER = "/etc/kiboto-release"


def test_mode() -> bool:
    """TESTING=1 or KIBOTO_TEST_MODE=1, honoured only outside the released image (ARC-29).

    The test switches make password hashing fast, allow the shared default password and turn the
    Docker proxy off, so in the image people install they do nothing, whatever a container
    template sets."""
    if os.path.exists(RELEASE_MARKER):
        return False
    return os.environ.get("TESTING") == "1" or legacy_names.getenv("KIBOTO_TEST_MODE") == "1"


def fast_hash() -> bool:
    """Cheap password hashing for test runs only (KIBOTO_FAST_HASH=1 or test mode)."""
    if os.path.exists(RELEASE_MARKER):
        return False
    return test_mode() or legacy_names.getenv("KIBOTO_FAST_HASH") == "1"


from typing import Any

from backend import legacy_names

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off", "")


def _s(
    env: str,
    default: Any,
    help: str,
    *,
    aliases: tuple[str, ...] = (),
    lo: float | None = None,
    hi: float | None = None,
    choices: tuple[str, ...] = (),
    group: str = "General",
    secret: bool = False,
) -> Any:
    return field(
        default=default,
        metadata={
            "env": env,
            "aliases": aliases,
            "help": help,
            "lo": lo,
            "hi": hi,
            "choices": choices,
            "group": group,
            "secret": secret,
        },
    )


@dataclass(frozen=True)
class Settings:
    # Host access
    host_proc: str = _s("HOST_PROC", "/host/proc", "Where the host's /proc is mounted.", group="Host")
    host_sys: str = _s("HOST_SYS", "/host/sys", "Where the host's /sys is mounted.", group="Host")
    host_dev: str = _s("HOST_DEV", "/host/dev", "Where the host's /dev is mounted.", group="Host")
    disks: str = _s("DISKS", "", "Comma-separated disks to show when they can't be detected.", group="Host")
    os_nvme: str = _s(
        "OS_NVME", "nvme1n1", "The NVMe device the operating system runs from, hidden from data disks.", group="Host"
    )
    show_os_disk: bool = _s("SHOW_OS_DISK", True, "Show the operating-system disk in the disk list.", group="Host")
    remotes_path: str = _s("REMOTES_PATH", "/mnt/remotes", "Where cloud and network remotes are mounted.", group="Host")
    host_etc: str = _s("HOST_ETC", "/host/etc", "Where the host's /etc is mounted.", group="Host")
    observer_mode: bool = _s(
        "KIBOTO_OBSERVER_MODE",
        False,
        "Only watch the host on an unknown system: read-only telemetry, no changes.",
        group="Host",
    )
    sqlite_vec_path: str = _s(
        "SQLITE_VEC_PATH", "", "Extra place to look for the sqlite-vec library (vec0.so) for AI search.", group="Host"
    )
    host_net_iface: str = _s(
        "HOST_NET_IFACE",
        "",
        "Network interface whose traffic the dashboard shows; empty = all physical ones.",
        group="Host",
    )
    containerized: bool = _s(
        "CONTAINERIZED", False, "Say Kiboto runs in a container when it can't tell by itself.", group="Host"
    )
    thumb_cache_mb: int = _s(
        "KIBOTO_THUMB_CACHE_MB",
        1024,
        "Size of the preview thumbnail cache, in MB (at least 16).",
        lo=0,
        hi=1048576,
        group="Host",
    )
    video_cache_mb: int = _s(
        "KIBOTO_VIDEO_CACHE_MB",
        4096,
        "Size of the cache of videos converted for browsers that can't play the original, in MB (at least 64).",
        lo=0,
        hi=1048576,
        group="Host",
    )
    sync_route_threads: int = _s(
        "SYNC_ROUTE_THREADS",
        40,
        "Threads for API requests that wait on files, disks or Docker; more serve more people at once and use more memory.",
        lo=8,
        hi=256,
        group="Host",
    )
    app_memory_warn_mb: int = _s(
        "APP_MEMORY_WARN_MB",
        1536,
        "Warn when Kiboto itself uses more memory than this, in MB (virtual machines not counted); 0 = off.",
        lo=0,
        hi=1048576,
        group="Host",
    )
    # Web server
    push_contact: str = _s(
        "KIBOTO_PUSH_CONTACT",
        "https://github.com/fr0styx/zettnas-toolkit",
        "Contact address sent to browser push services with each notification.",
        group="Web",
    )
    port: int = _s("PORT", 8082, "Port of the web interface.", lo=1, hi=65535, group="Web")
    trusted_proxies: tuple[str, ...] = _s(
        "TRUSTED_PROXIES",
        ("127.0.0.1", "::1"),
        "Reverse proxies whose X-Forwarded-For is believed (comma-separated).",
        group="Web",
    )
    enable_proxy_sso: bool = _s(
        "ENABLE_PROXY_SSO",
        False,
        "Accept a signed-in user from a trusted proxy's header. Since 1.12 the header reaches only accounts "
        "the proxy created; other accounts, admins included, sign in with their own password.",
        group="Web",
    )
    csrf_trusted_origins: tuple[str, ...] = _s(
        "CSRF_TRUSTED_ORIGINS",
        (),
        "Extra origins allowed to send requests that change things (comma-separated).",
        group="Web",
    )
    enable_api_docs: bool = _s(
        "ENABLE_API_DOCS", False, "Serve the interactive API documentation at /api/docs.", group="Web"
    )
    login_user_chooser: bool = _s("LOGIN_USER_CHOOSER", False, "Show a list of users on the sign-in page.", group="Web")
    max_body_mb: int = _s(
        "MAX_BODY_MB", 16, "Largest request body accepted, in MB (uploads excepted).", lo=1, hi=4096, group="Web"
    )
    max_wallpaper_mb: int = _s("MAX_WALLPAPER_MB", 10, "Largest wallpaper upload, in MB.", lo=1, hi=1024, group="Web")
    max_upload_gb: int = _s("MAX_UPLOAD_GB", 64, "Largest file upload, in GB.", lo=1, hi=100000, group="Web")
    trusted_ips: tuple[str, ...] = _s(
        "KIBOTO_TRUSTED_IPS",
        (),
        "Addresses or networks (CIDR) never blocked after failed sign-ins, comma-separated.",
        group="Web",
    )
    # File services
    auto_ingest_enabled: bool = _s(
        "AUTO_INGEST_ENABLED",
        False,
        "Copy a card as soon as it is inserted, even when Automatic Slot Ingest is off in the settings.",
        group="File services",
    )
    sftp_port: int = _s("SFTP_PORT", 2222, "Port of the built-in SFTP server.", lo=1, hi=65535, group="File services")
    nas_name: str = _s(
        "KIBOTO_NAS_NAME",
        "",
        "The NAS's name on the home network (<name>.local); empty: zettnas.",
        group="File services",
    )
    webdav_port: int = _s(
        "WEBDAV_PORT", 8084, "Port of the built-in WebDAV server.", lo=1, hi=65535, group="File services"
    )
    # Updates and image
    update_channel: str = _s(
        "UPDATE_CHANNEL", "stable", "Release channel to follow.", choices=("stable", "beta", "edge"), group="Updates"
    )
    update_signatures: str = _s(
        "UPDATE_SIGNATURES",
        "enforce",
        "In-app updates check the image's signature from this project's CI first: enforce (refuse "
        "an unsigned or wrongly signed image), warn (log it and install anyway) or off.",
        choices=("enforce", "warn", "off"),
        group="Updates",
    )
    image_variant: str = _s(
        "KIBOTO_IMAGE_VARIANT",
        "full",
        "full ships VMs and the LCD renderer; core leaves them out.",
        choices=("full", "core"),
        group="Updates",
    )
    health_signal_url: str = _s(
        "HEALTH_SIGNAL_URL",
        "",
        "Where the opt-in anonymous health report goes; empty uses the project's receiver.",
        group="Updates",
    )
    build_commit: str = _s(
        "BUILD_COMMIT", "", "The commit the image was built from; set by the image build.", group="Updates"
    )
    build_date: str = _s("BUILD_DATE", "", "When the image was built; set by the image build.", group="Updates")
    # Logs
    log_format: str = _s(
        "LOG_FORMAT",
        "text",
        "Log lines as plain text, or as one JSON object per line (with a request id) for log collectors.",
        choices=("text", "json"),
        group="Logs",
    )
    audit_retention_days: int = _s(
        "KIBOTO_AUDIT_RETENTION_DAYS",
        365,
        "Days the security audit log keeps an event; 0 keeps everything.",
        lo=0,
        hi=36500,
        group="Logs",
    )
    structured_logs: bool = _s("STRUCTURED_LOGS", False, "Older name for LOG_FORMAT=json.", group="Logs")
    log_file: bool = _s(
        "KIBOTO_LOG_FILE", True, "Keep a rotating log file in the data folder for the support bundle.", group="Logs"
    )
    gil_switch_secs: float = _s(
        "KIBOTO_GIL_SWITCH_SECS",
        0.02,
        "How long a Python thread runs before handing over to another, in seconds; longer means fewer wakeups.",
        lo=0.001,
        hi=1.0,
        group="Host",
    )
    dash_layout_path: str = _s(
        "LAYOUT_PATH", "", "The desktop layout file; empty keeps it in the data folder.", group="Host"
    )
    backup_dir: str = _s(
        "BACKUP_DIR", "", "Where settings backups go; empty keeps them in the data folder.", group="Host"
    )
    vm_iso_dir: str = _s(
        "VM_ISO_DIR", "", "The ISO library for virtual machines; empty keeps it in the data folder.", group="Host"
    )
    tailscale_state_dir: str = _s(
        "TAILSCALE_STATE_DIR", "", "Tailscale's state folder; empty keeps it in the data folder.", group="Host"
    )
    host_ip: str = _s("HOST_IP", "", "The server's address, when it can't be found by itself.", group="Host")
    # Power
    ups_mode: str = _s("UPS_MODE", "auto", "How to reach the UPS (auto, nut, usb, ...).", group="Power")
    nut_host: str = _s("NUT_HOST", "127.0.0.1", "Network UPS Tools server.", group="Power")
    nut_port: int = _s("NUT_PORT", 3493, "Network UPS Tools port.", lo=1, hi=65535, group="Power")
    nut_name: str = _s("NUT_NAME", "ups", "UPS name on the NUT server.", group="Power")
    ups_failsafe_battery_min: float = _s(
        "UPS_FAILSAFE_BATTERY_MIN",
        20.0,
        "Battery percent that counts as low when the UPS settings can't be read.",
        lo=0,
        hi=100,
        group="Power",
    )
    ups_failsafe_runtime_min: float = _s(
        "UPS_FAILSAFE_RUNTIME_MIN",
        5.0,
        "Minutes of runtime that count as low when the UPS settings can't be read.",
        lo=0,
        hi=1440,
        group="Power",
    )
    ups_host: str = _s(
        "UPS_HOST", "", "Older setups: the apcupsd or NUT server, when the Power pane has none.", group="Power"
    )
    ups_port: str = _s("UPS_PORT", "", "Older setups: that server's port (3551 apcupsd, 3493 NUT).", group="Power")
    ups_type: str = _s("UPS_TYPE", "", "Older setups: nut for a NUT server, else apcupsd.", group="Power")
    nut_ups_name: str = _s("NUT_UPS_NAME", "", "Older setups: the UPS name on the NUT server.", group="Power")
    # Front panel
    enable_fb: bool = _s("ENABLE_FB", True, "Drive the front LCD.", group="Front panel")
    lcd_fps: int = _s("LCD_FPS", 5, "Frames per second sent to the front LCD.", lo=1, hi=30, group="Front panel")
    lcd_format: str = _s(
        "LCD_FORMAT", "jpeg", "Image format of LCD frames.", choices=("jpeg", "png"), group="Front panel"
    )
    lcd_renderer: str = _s(
        "LCD_RENDERER",
        "auto",
        "What draws the front LCD: chromium (the web dashboard), pil (drawn directly, no browser) "
        "or auto (chromium when installed, otherwise pil).",
        choices=("auto", "chromium", "pil"),
        group="Front panel",
    )
    lcd_sleep_sec: int = _s(
        "LCD_SLEEP_SEC", 300, "Seconds without activity before the LCD dims.", lo=0, hi=86400, group="Front panel"
    )
    lcd_capture: str = _s(
        "KIBOTO_LCD_CAPTURE",
        "screencast",
        "How the front LCD gets its frames: pushed when the page changes, or a screenshot every frame.",
        choices=("screencast", "poll"),
        group="Front panel",
    )
    framebuffer: str = _s(
        "FRAMEBUFFER", "", "The front LCD's framebuffer device, when it isn't /dev/fb0.", group="Front panel"
    )
    led_port: str = _s(
        "LED_PORT", "", "The light bar's serial port, when it isn't found by itself.", group="Front panel"
    )
    chromium_path: str = _s(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
        "",
        "The Chromium that draws the front LCD; empty uses the image's.",
        group="Front panel",
    )
    # Disks and health
    smart_poll_hdd: int = _s(
        "SMART_POLL_HDD", 45, "Seconds between SMART reads of spinning disks.", lo=5, hi=86400, group="Disks"
    )
    smart_poll_nvme: int = _s(
        "SMART_POLL_NVME", 60, "Seconds between SMART reads of NVMe disks.", lo=5, hi=86400, group="Disks"
    )
    smart_idle_adaptive: bool = _s(
        "SMART_IDLE_ADAPTIVE",
        True,
        "Read SMART less often from spinning disks with no recent activity, so they can spin down.",
        group="Disks",
    )
    smart_idle_poll: int = _s(
        "SMART_IDLE_POLL", 1800, "Seconds between SMART reads of an idle spinning disk.", lo=60, hi=86400, group="Disks"
    )
    hdd_warn_temp: int = _s(
        "HDD_WARN_TEMP", 50, "Hard disk temperature that raises a warning, °C.", lo=20, hi=100, group="Disks"
    )
    hdd_critical_temp: int = _s(
        "HDD_CRITICAL_TEMP", 55, "Hard disk temperature that forces full fan speed, °C.", lo=20, hi=100, group="Disks"
    )
    nvme_warn_temp: int = _s(
        "NVME_WARN_TEMP", 70, "NVMe temperature that raises a warning, °C.", lo=20, hi=110, group="Disks"
    )
    nvme_critical_temp: int = _s(
        "NVME_CRITICAL_TEMP", 75, "NVMe temperature that forces full fan speed, °C.", lo=20, hi=110, group="Disks"
    )
    collector_watchdog_secs: int = _s(
        "COLLECTOR_WATCHDOG_SECS",
        20,
        "Seconds without fresh stats before health reports degraded.",
        lo=5,
        hi=3600,
        group="Disks",
    )
    standby_unknown: str = _s(
        "KIBOTO_STANDBY_UNKNOWN",
        "defer",
        "When it can't tell which disk holds a folder: defer the work (it may be asleep) or check anyway.",
        choices=("defer", "allow"),
        group="Disks",
    )
    # Fans
    fan_failsafe_pwm: int = _s(
        "FAN_FAILSAFE_PWM", 150, "Fan PWM when the CPU temperature can't be read.", lo=0, hi=255, group="Fans"
    )
    fan_kickstart_pwm: int = _s(
        "FAN_KICKSTART_PWM", 150, "PWM used to start a stopped fan.", lo=0, hi=255, group="Fans"
    )
    fan_kickstart_secs: float = _s("FAN_KICKSTART_SECS", 2.0, "Seconds of kick-start PWM.", lo=0, hi=60, group="Fans")
    fan_spinup_grace_secs: float = _s(
        "FAN_SPINUP_GRACE_SECS",
        6.0,
        "Seconds a starting fan may show 0 RPM before it counts as stalled.",
        lo=0,
        hi=120,
        group="Fans",
    )
    fan_disk_hold_secs: int = _s(
        "FAN_DISK_HOLD_SECS",
        30,
        "Seconds disk fans hold a higher speed before slowing down.",
        lo=0,
        hi=3600,
        group="Fans",
    )
    fan_cpu_hold_secs: int = _s(
        "FAN_CPU_HOLD_SECS",
        30,
        "Seconds the CPU fan holds a higher speed before slowing down.",
        lo=0,
        hi=3600,
        group="Fans",
    )
    zero_rpm_enabled: bool = _s(
        "ZERO_RPM_ENABLED", False, "Default for stopping the disk fans while all disks sleep.", group="Fans"
    )
    zero_rpm_stop_delay: int = _s(
        "FAN_ZERO_RPM_STOP_DELAY", 30, "Seconds disks must sleep before the fans stop.", lo=0, hi=3600, group="Fans"
    )
    zero_rpm_nvme_ceiling: int = _s(
        "FAN_ZERO_RPM_NVME_CEILING",
        50,
        "Highest NVMe temperature at which fans may stop, °C.",
        aliases=("ZERO_RPM_NVME",),
        lo=20,
        hi=100,
        group="Fans",
    )
    zero_rpm_stop_temp: int = _s(
        "FAN_ZERO_RPM_STOP_TEMP",
        34,
        "Disk bay temperature at or below which fans may stop, °C.",
        aliases=("ZERO_RPM_TEMP",),
        lo=15,
        hi=80,
        group="Fans",
    )
    zero_rpm_start_temp: int = _s(
        "FAN_ZERO_RPM_START_TEMP",
        38,
        "Disk bay temperature that restarts stopped fans, °C.",
        lo=15,
        hi=90,
        group="Fans",
    )
    force_zettlab_mmio: str = _s(
        "FORCE_ZETTLAB_MMIO", "", "1 forces the Zettlab fan registers on, 0 off; empty detects the board.", group="Fans"
    )
    # AI and media
    ai_num_ctx: int = _s(
        "KIBOTO_AI_NUM_CTX",
        0,
        "Chat context window in tokens; 0 uses the built-in size, values under 2048 are ignored.",
        lo=0,
        hi=1048576,
        group="AI and media",
    )
    video_hwenc: str = _s(
        "KIBOTO_VIDEO_HWENC",
        "auto",
        "Convert videos with the iGPU when it can (auto) or always in software (off).",
        choices=("auto", "off"),
        group="AI and media",
    )
    ollama_host: str = _s(
        "OLLAMA_HOST", "", "The Ollama server (host, host:port or URL); empty finds it.", group="AI and media"
    )
    llm_host: str = _s("LLM_HOST", "", "Older name for OLLAMA_HOST, read when that is empty.", group="AI and media")
    # Platforms
    truenas_verify_tls: bool = _s(
        "TRUENAS_VERIFY_TLS", True, "Check the TrueNAS certificate; off accepts a self-signed one.", group="Platforms"
    )
    unraid_api_verify_tls: bool = _s(
        "UNRAID_API_VERIFY_TLS", True, "Check the Unraid API certificate; off accepts any.", group="Platforms"
    )
    unraid_emhttp_dir: str = _s(
        "UNRAID_EMHTTP_DIR", "", "Unraid's emhttp state folder, when it isn't in a usual place.", group="Platforms"
    )
    platform: str = _s(
        "KIBOTO_PLATFORM",
        "",
        "Which host this is (unraid, truenas, zettos, ...); empty detects it.",
        group="Platforms",
    )
    observer_adapter: str = _s(
        "KIBOTO_OBSERVER_ADAPTER",
        "",
        "The host to read in observer mode; empty or auto detects it.",
        group="Platforms",
    )
    pal_mode: str = _s(
        "KIBOTO_PAL_MODE",
        "",
        "observer, readonly or telemetry: only read the host, never change it.",
        group="Platforms",
    )
    truenas_url: str = _s("TRUENAS_URL", "", "The TrueNAS address for its API (https://...).", group="Platforms")
    truenas_user: str = _s(
        "TRUENAS_USER",
        "",
        "The TrueNAS user the API key belongs to (TrueNAS 28 signs in with both).",
        group="Platforms",
    )
    unraid_api_url: str = _s("UNRAID_API_URL", "", "The Unraid API address (https://...).", group="Platforms")
    unraid_api_ca: str = _s("UNRAID_API_CA", "", "Another CA file to trust for the Unraid API.", group="Platforms")


def _convert(raw: str, typ: Any, meta: Mapping[str, Any]) -> Any:
    v = raw.strip()
    if typ is bool:
        low = v.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError("expected 1/0, true/false, yes/no or on/off")
    if typ is int or typ is float:
        try:
            num = typ(float(v)) if typ is int else float(v)
        except ValueError:
            raise ValueError("expected a number") from None
        if meta["lo"] is not None and num < meta["lo"] or meta["hi"] is not None and num > meta["hi"]:
            raise ValueError(f"expected {meta['lo']} to {meta['hi']}")
        return num
    if typ == tuple[str, ...]:
        return tuple(p.strip() for p in v.split(",") if p.strip())
    if meta["choices"]:
        low = v.lower()
        if low not in meta["choices"]:
            raise ValueError("expected one of " + ", ".join(meta["choices"]))
        return low
    return v


_FIELD_CACHE: dict[str, Any] = {}


def _env_names(meta) -> tuple[str, ...]:
    """The names a setting is read from, in order: older aliases, its own, then its pre-rebrand
    ZETTNAS_ name (legacy_names), so a KIBOTO_ value wins over a ZETTNAS_ one."""
    old = legacy_names.old_env_name(meta["env"])
    return (*meta["aliases"], meta["env"], *((old,) if old else ()))


def current(name: str) -> Any:
    """One setting as the environment holds it now, for the few read while Kiboto runs (and changed
    by tests while it does); declared, converted and checked like the others."""
    if not _FIELD_CACHE:
        import typing

        hints = typing.get_type_hints(Settings)
        _FIELD_CACHE.update({f.name: (f, hints[f.name]) for f in dataclasses.fields(Settings)})
    f, typ = _FIELD_CACHE[name]
    meta = f.metadata
    key = next((n for n in _env_names(meta) if n in os.environ), None)
    if key is None:
        return f.default
    try:
        return _convert(os.environ[key], typ, meta)
    except ValueError:
        return f.default


def load_settings(env: Mapping[str, str] | None = None) -> tuple[Settings, list[str]]:
    """(settings, problems): unusable values keep their default and are reported."""
    env = os.environ if env is None else env
    values: dict[str, Any] = {}
    problems: list[str] = []
    hints = {f.name: f.type for f in dataclasses.fields(Settings)}
    import typing

    hints = typing.get_type_hints(Settings)
    for f in dataclasses.fields(Settings):
        meta = f.metadata
        name = next((n for n in _env_names(meta) if n in env), None)
        if name is None:
            continue
        try:
            values[f.name] = _convert(env[name], hints[f.name], meta)
        except ValueError as e:
            shown = "(hidden)" if meta["secret"] else repr(env[name])
            problems.append(f"{name}={shown} can't be used ({e}); using {f.default!r}")
    return Settings(**values), problems


def markdown() -> str:
    """docs/CONFIGURATION.md, generated from the declarations above."""
    out = [
        "# Configuration",
        "",
        "Environment variables Kiboto reads at startup. Generated from `backend/settings.py`",
        "(`python -m backend.settings --markdown > docs/CONFIGURATION.md`); a value that can't be",
        "used keeps its default, and the log says which variable and why. Before Kiboto 2.0 the",
        "`KIBOTO_*` variables were named `ZETTNAS_*`; the old names still work until 2.2, and a new",
        "name set beside an old one wins.",
    ]
    group = None
    for f in dataclasses.fields(Settings):
        m = f.metadata
        if m["group"] != group:
            group = m["group"]
            out += ["", f"## {group}", "", "| Variable | Default | Meaning |", "|---|---|---|"]
        default = f.default
        if isinstance(default, bool):
            shown = "on" if default else "off"
        elif isinstance(default, tuple):
            shown = ", ".join(default) or "(none)"
        else:
            shown = str(default) if default != "" else "(empty)"
        extra = []
        if m["lo"] is not None:
            extra.append(f"{m['lo']:g}–{m['hi']:g}")
        if m["choices"]:
            extra.append("one of " + ", ".join(f"`{c}`" for c in m["choices"]))
        if m["aliases"]:
            extra.append("also read as " + ", ".join(f"`{a}`" for a in m["aliases"]))
        help_text = m["help"] + (f" ({'; '.join(extra)})" if extra else "")
        out.append(f"| `{m['env']}` | `{shown}` | {help_text} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if "--markdown" in sys.argv:
        sys.stdout.write(markdown())
    else:
        s, probs = load_settings()
        for p in probs:
            print("problem:", p)
        print(s)
