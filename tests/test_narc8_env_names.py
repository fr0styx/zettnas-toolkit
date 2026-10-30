"""NARC-8: settings come from backend/settings.py, where each has a type, a default, limits and a
line in docs/CONFIGURATION.md. Code elsewhere may not start reading a new environment variable
of its own; the ones that still do are listed here and only go down."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
READ = re.compile(
    r"""os\.(?:environ\.get|getenv|environ\.setdefault)\(\s*["']([A-Z][A-Z0-9_]+)["']|os\.environ\[\s*["']([A-Z][A-Z0-9_]+)["']\s*\]"""
)
LEFT = {
    "AI_CONVERSATIONS_DB_PATH",
    "AUTO_INGEST_ENABLED",
    "BACKUP_DIR",
    "BROWSE_ROOTS",
    "BUILD_COMMIT",
    "BUILD_DATE",
    "CONTAINERIZED",
    "CREDENTIALS_DIRECTORY",
    "DATA_DIR",
    "DOCKER_CONFIG_JSON",
    "EMBEDDING_TOKEN",
    "FAN_WATCHDOG_CHECK_SECS",
    "FAN_WATCHDOG_DRY_RUN",
    "FAN_WATCHDOG_HEARTBEAT",
    "FAN_WATCHDOG_STALE_SECS",
    "FORCE_ZETTLAB_MMIO",
    "FRAMEBUFFER",
    "HEALTH_SIGNAL_URL",
    "HOST_ETC",
    "HOST_IP",
    "HOST_NET_IFACE",
    "LAYOUT_PATH",
    "LED_PORT",
    "LLM_HOST",
    "NAS_NAME",
    "NUT_UPS_NAME",
    "OLLAMA_HOST",
    "PHOTO_VECTOR_TOKEN",
    "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
    "POOL_PATH",
    "SECRET_KEY",
    "SECRET_KEY_FILE",
    "SQLITE_VEC_PATH",
    "STORAGE_POOL_PATH",
    "STRUCTURED_LOGS",
    "TAILSCALE_STATE_DIR",
    "TRUENAS_API_KEY",
    "TRUENAS_URL",
    "TRUENAS_VERIFY_TLS",
    "TZ",
    "UNRAID_API_CA",
    "UNRAID_API_KEY",
    "UNRAID_API_URL",
    "UNRAID_API_VERIFY_TLS",
    "UNRAID_EMHTTP_DIR",
    "UPS_FAILSAFE_BATTERY_MIN",
    "UPS_FAILSAFE_RUNTIME_MIN",
    "UPS_HOST",
    "UPS_PORT",
    "UPS_TYPE",
    "USERS_DB_PATH",
    "VM_ISO_DIR",
    "WEB_PASSWORD",
    "ZETTNAS_AI_NUM_CTX",
    "ZETTNAS_ALLOW_DEFAULT_PASSWORD",
    "ZETTNAS_AUTH_FAIL_LOG",
    "ZETTNAS_DATA_HOST_PATHS",
    "ZETTNAS_DOCKER_PROXY",
    "ZETTNAS_DOCKER_PROXY_SOCK",
    "ZETTNAS_DOCKER_SOCK",
    "ZETTNAS_DOCKER_UPSTREAM",
    "ZETTNAS_ENFORCE_PASSWORD_CHANGE",
    "ZETTNAS_LCD_CAPTURE",
    "ZETTNAS_LOG_FILE",
    "ZETTNAS_OBSERVER_ADAPTER",
    "ZETTNAS_OBSERVER_MODE",
    "ZETTNAS_PAL_MODE",
    "ZETTNAS_PLATFORM",
    "ZETTNAS_PUSH_CONTACT",
    "ZETTNAS_STANDBY_UNKNOWN",
    "ZETTNAS_THUMB_CACHE_DIR",
    "ZETTNAS_THUMB_CACHE_MB",
    "ZETTNAS_TRUSTED_IPS",
    "ZETTNAS_VIDEO_HWENC",
}


def read_outside_settings():
    names = set()
    for path in (ROOT / "backend").rglob("*.py"):
        if path.name == "settings.py":
            continue
        for m in READ.finditer(path.read_text(encoding="utf-8")):
            names.add(m.group(1) or m.group(2))
    return names


def declared():
    import dataclasses

    from backend.settings import Settings

    out = set()
    for f in dataclasses.fields(Settings):
        out.add(f.metadata["env"])
        out.update(f.metadata["aliases"])
    return out


def test_no_new_variable_is_read_outside_settings():
    new = read_outside_settings() - LEFT - declared()
    assert not new, f"declare these in backend/settings.py (and regenerate docs/CONFIGURATION.md): {sorted(new)}"


def test_the_list_only_goes_down():
    gone = LEFT - read_outside_settings()
    assert not gone, f"no longer read outside settings.py; remove from LEFT: {sorted(gone)}"
    both = LEFT & declared()
    assert not both, f"declared in settings.py now; remove from LEFT: {sorted(both)}"


def test_a_typo_no_longer_stops_startup():
    from backend.settings import load_settings

    s, problems = load_settings({"ZETTNAS_AUDIT_RETENTION_DAYS": "a year", "ZETTNAS_GIL_SWITCH_SECS": "fast"})
    assert s.audit_retention_days == 365 and s.gil_switch_secs == 0.02
    assert len(problems) == 2 and "ZETTNAS_AUDIT_RETENTION_DAYS" in problems[0]
