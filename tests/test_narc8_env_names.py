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
    "BROWSE_ROOTS",
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
    "LED_PORT",
    "NAS_NAME",
    "NUT_UPS_NAME",
    "PHOTO_VECTOR_TOKEN",
    "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
    "POOL_PATH",
    "SECRET_KEY",
    "SECRET_KEY_FILE",
    "STORAGE_POOL_PATH",
    "STRUCTURED_LOGS",
    "TRUENAS_API_KEY",
    "TRUENAS_URL",
    "TZ",
    "UNRAID_API_CA",
    "UNRAID_API_KEY",
    "UNRAID_API_URL",
    "UPS_HOST",
    "UPS_PORT",
    "UPS_TYPE",
    "USERS_DB_PATH",
    "WEB_PASSWORD",
    "ZETTNAS_ALLOW_DEFAULT_PASSWORD",
    "ZETTNAS_AUTH_FAIL_LOG",
    "ZETTNAS_DATA_HOST_PATHS",
    "ZETTNAS_DOCKER_PROXY",
    "ZETTNAS_DOCKER_PROXY_SOCK",
    "ZETTNAS_DOCKER_SOCK",
    "ZETTNAS_DOCKER_UPSTREAM",
    "ZETTNAS_ENFORCE_PASSWORD_CHANGE",
    "ZETTNAS_LOG_FILE",
    "ZETTNAS_THUMB_CACHE_DIR",
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


def test_a_setting_read_while_running_follows_the_environment(monkeypatch):
    from backend import settings

    monkeypatch.setenv("HOST_IP", " 10.1.2.3 ")
    assert settings.current("host_ip") == "10.1.2.3"
    monkeypatch.delenv("HOST_IP")
    assert settings.current("host_ip") == ""
    monkeypatch.setenv("SFTP_PORT", "not a port")
    assert settings.current("sftp_port") == 2222  # unusable: the default, as at startup
