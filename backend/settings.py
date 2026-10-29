"""Typed settings from environment variables (ARCH-9).

Every operator setting is declared once here with its type, default, limits and a line of
help. A value that can't be used (a port of "abc", an LCD rate of 500) falls back to the
default with a warning that names the variable, instead of stopping ZettNAS at startup with a
traceback. backend.config reads its constants from here; docs/CONFIGURATION.md is generated
from these declarations (python -m backend.settings --markdown) and a test keeps it in sync.
"""

import dataclasses
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field

# Written by the release image's build (Dockerfile); environment variables can't create it.
RELEASE_MARKER = "/etc/zettnas-release"


def test_mode() -> bool:
    """TESTING=1 or ZETTNAS_TEST_MODE=1, honoured only outside the released image (ARC-29).

    The test switches make password hashing fast, allow the shared default password and turn the
    Docker proxy off, so in the image people install they do nothing, whatever a container
    template sets."""
    if os.path.exists(RELEASE_MARKER):
        return False
    return os.environ.get("TESTING") == "1" or os.environ.get("ZETTNAS_TEST_MODE") == "1"


def fast_hash() -> bool:
    """Cheap password hashing for test runs only (ZETTNAS_FAST_HASH=1 or test mode)."""
    if os.path.exists(RELEASE_MARKER):
        return False
    return test_mode() or os.environ.get("ZETTNAS_FAST_HASH") == "1"


from typing import Any

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
        "Warn when ZettNAS itself uses more memory than this, in MB (virtual machines not counted); 0 = off.",
        lo=0,
        hi=1048576,
        group="Host",
    )
    # Web server
    port: int = _s("PORT", 8082, "Port of the web interface.", lo=1, hi=65535, group="Web")
    trusted_proxies: tuple[str, ...] = _s(
        "TRUSTED_PROXIES",
        ("127.0.0.1", "::1"),
        "Reverse proxies whose X-Forwarded-For is believed (comma-separated).",
        group="Web",
    )
    enable_proxy_sso: bool = _s(
        "ENABLE_PROXY_SSO", False, "Accept a signed-in user from a trusted proxy's header.", group="Web"
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
    # File services
    sftp_port: int = _s("SFTP_PORT", 2222, "Port of the built-in SFTP server.", lo=1, hi=65535, group="File services")
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
        "ZETTNAS_IMAGE_VARIANT",
        "full",
        "full ships VMs and the LCD renderer; core leaves them out.",
        choices=("full", "core"),
        group="Updates",
    )
    # Logs
    log_format: str = _s(
        "LOG_FORMAT",
        "text",
        "Log lines as plain text, or as one JSON object per line (with a request id) for log collectors.",
        choices=("text", "json"),
        group="Logs",
    )
    # Power
    ups_mode: str = _s("UPS_MODE", "auto", "How to reach the UPS (auto, nut, usb, ...).", group="Power")
    nut_host: str = _s("NUT_HOST", "127.0.0.1", "Network UPS Tools server.", group="Power")
    nut_port: int = _s("NUT_PORT", 3493, "Network UPS Tools port.", lo=1, hi=65535, group="Power")
    nut_name: str = _s("NUT_NAME", "ups", "UPS name on the NUT server.", group="Power")
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
        name = next((n for n in (*meta["aliases"], meta["env"]) if n in env), None)
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
        "Environment variables ZettNAS reads at startup. Generated from `backend/settings.py`",
        "(`python -m backend.settings --markdown > docs/CONFIGURATION.md`); a value that can't be",
        "used keeps its default, and the log says which variable and why.",
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
