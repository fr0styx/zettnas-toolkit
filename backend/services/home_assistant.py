"""Home Assistant: Kiboto's health as sensors, through MQTT discovery.

Every minute (by default) Kiboto connects to the broker Home Assistant uses, announces its sensors
once per start (retained discovery messages under homeassistant/…) and publishes their values in
one retained JSON message. The sensors expire when updates stop, so Home Assistant shows them as
unavailable instead of a stale value. Off until someone sets a broker; the password is sealed.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from backend import __version__
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, locked_json, read_json
from backend.services import mqtt_lite

CONFIG_FILE = os.path.join(DATA_DIR, "home_assistant.json")
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "host": "",
    "port": 1883,
    "username": "",
    "password": "",
    "tls": False,
    "discovery_prefix": "homeassistant",
    "interval_s": 60,
}
_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {"last_ok": None, "last_error": "", "last_at": None, "sensors": 0}


def load_config() -> dict[str, Any]:
    from backend.secret_box import SecretBoxError, unseal

    data = read_json(CONFIG_FILE, default={}) or {}
    cfg = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    try:
        cfg["password"] = unseal(str(cfg.get("password") or ""))
    except SecretBoxError:
        cfg["password"] = ""
    return cfg


def public_config() -> dict[str, Any]:
    cfg = load_config()
    has_password = bool(cfg.pop("password"))
    with _LOCK:
        status = dict(_STATUS)
    return {**cfg, "has_password": has_password, "status": status}


def save_config(changes: dict[str, Any]) -> dict[str, Any]:
    """Merges changes; a password of None keeps the saved one, "" clears it."""
    from backend.secret_box import seal

    with locked_json(CONFIG_FILE):
        cfg = load_config()
        for key in DEFAULTS:
            if key in changes and changes[key] is not None:
                cfg[key] = changes[key]
        if cfg["enabled"] and not str(cfg["host"]).strip():
            raise ValueError("Set the broker's address first.")
        stored = {**cfg, "password": seal(str(cfg["password"])) if cfg["password"] else ""}
        atomic_write_json(CONFIG_FILE, stored)
    return public_config()


def node_id() -> str:
    """The id Home Assistant knows this NAS by: its name on the network."""
    from backend.services import nas_name

    return re.sub(r"[^a-z0-9_]", "_", str(nas_name.config().get("name") or "kiboto").lower())[:40] or "kiboto"


def sensors(stats: dict[str, Any]) -> list[dict[str, Any]]:
    """What Kiboto reports, from its live stats: (key, name, unit, device_class, value, component)."""
    out: list[dict[str, Any]] = []

    def add(key, name, value, unit=None, device_class=None, component="sensor", icon=None):
        if value is None:
            return
        out.append(
            {
                "key": key,
                "name": name,
                "value": value,
                "unit": unit,
                "device_class": device_class,
                "component": component,
                "icon": icon,
            }
        )

    cpu = stats.get("cpu") or {}
    add("cpu_usage", "CPU usage", cpu.get("util", cpu.get("usage")), "%", None, icon="mdi:cpu-64-bit")
    add("cpu_temperature", "CPU temperature", cpu.get("temp"), "°C", "temperature")
    mem = stats.get("mem") or {}
    add("memory_usage", "Memory usage", mem.get("pct", mem.get("percent")), "%", None, icon="mdi:memory")
    hottest = None
    for d in stats.get("disks") or []:
        name = str(d.get("name") or "")
        if not name or d.get("temp") is None:
            continue
        add(
            f"disk_{re.sub(r'[^a-z0-9]', '_', name.lower())}_temperature",
            f"Disk {name} temperature",
            d.get("temp"),
            "°C",
            "temperature",
        )
        hottest = max(hottest or d["temp"], d["temp"])
    add("hottest_disk_temperature", "Hottest disk", hottest, "°C", "temperature")
    ups = stats.get("ups") or {}
    if ups.get("available"):
        add("ups_battery", "UPS battery", ups.get("battery_charge_pct"), "%", "battery")
        add("ups_runtime", "UPS time left", ups.get("time_left_min"), "min", "duration")
        add("ups_load", "UPS load", ups.get("load_pct"), "%", None, icon="mdi:flash")
        add("ups_on_battery", "UPS on battery", bool(ups.get("on_battery")), None, "power", component="binary_sensor")
    try:
        from backend.services.ransomware_guard import get_guard

        add(
            "ransomware_frozen",
            "Ransomware guard froze writes",
            bool(get_guard().frozen),
            None,
            "problem",
            component="binary_sensor",
        )
    except (AttributeError, ImportError, OSError, RuntimeError):  # the guard may not be set up yet
        logger.debug("home_assistant: guard state unavailable", exc_info=True)
    return out


def _template(key: str, binary: bool) -> str:
    """Home Assistant's Jinja template that reads this sensor's value out of the state message."""
    return "{{ 'ON' if value_json." + key + " else 'OFF' }}" if binary else "{{ value_json." + key + " }}"


def messages(cfg: dict[str, Any], stats: dict[str, Any], announce: bool = True) -> list[tuple[str, str, bool]]:
    node = node_id()
    state_topic = f"kiboto/{node}/state"
    device = {
        "identifiers": [f"kiboto_{node}"],
        "name": node,
        "manufacturer": "Kiboto",
        "model": "Kiboto NAS",
        "sw_version": __version__,
    }
    found = sensors(stats)
    out: list[tuple[str, str, bool]] = []
    if announce:
        prefix = str(cfg.get("discovery_prefix") or "homeassistant").strip("/")
        for s in found:
            binary = s["component"] == "binary_sensor"
            conf: dict[str, Any] = {
                "name": s["name"],
                "unique_id": f"kiboto_{node}_{s['key']}",
                "object_id": f"kiboto_{node}_{s['key']}",
                "state_topic": state_topic,
                "value_template": _template(s["key"], binary),
                "expire_after": int(cfg.get("interval_s") or 60) * 3,
                "device": device,
            }
            if s["unit"]:
                conf["unit_of_measurement"] = s["unit"]
            if s["device_class"]:
                conf["device_class"] = s["device_class"]
            if s["icon"]:
                conf["icon"] = s["icon"]
            if not binary:
                conf["state_class"] = "measurement"
            out.append((f"{prefix}/{s['component']}/kiboto_{node}/{s['key']}/config", json.dumps(conf), True))
    out.append((state_topic, json.dumps({s["key"]: s["value"] for s in found}), True))
    return out


def publish_once(
    cfg: dict[str, Any] | None = None, stats: dict[str, Any] | None = None, announce: bool = True
) -> dict[str, Any]:
    cfg = cfg or load_config()
    if stats is None:
        from backend.state import Z_STATE

        stats = Z_STATE.cached_stats or {}
    msgs = messages(cfg, stats, announce)
    try:
        sent = mqtt_lite.publish(
            str(cfg["host"]).strip(),
            int(cfg.get("port") or 1883),
            msgs,
            username=str(cfg.get("username") or ""),
            password=str(cfg.get("password") or ""),
            client_id=f"kiboto-{node_id()}",
            tls=bool(cfg.get("tls")),
        )
    except OSError as e:
        with _LOCK:
            _STATUS.update(last_ok=False, last_error=str(e) or e.__class__.__name__, last_at=time.time())
        raise
    count = len(msgs) - 1 if announce else len(json.loads(msgs[-1][1]))
    with _LOCK:
        _STATUS.update(last_ok=True, last_error="", last_at=time.time(), sensors=count)
    return {"sent": sent, "sensors": count}


def _loop(stop: threading.Event) -> None:
    announced = False
    while not stop.is_set():
        cfg = load_config()
        if cfg["enabled"] and str(cfg["host"]).strip():
            try:
                publish_once(cfg, announce=not announced)
                announced = True
            except OSError as e:
                announced = False  # announce again once the broker is back
                logger.info("home_assistant: couldn't reach the broker: %s", e)
        else:
            announced = False
        stop.wait(max(15, int(cfg.get("interval_s") or 60)))


_THREAD: dict[str, Any] = {}


def start() -> None:
    """Starts the background publisher once (it does nothing while switched off)."""
    if _THREAD.get("t"):
        return
    stop = threading.Event()
    t = threading.Thread(target=_loop, args=(stop,), name="HomeAssistant", daemon=True)
    _THREAD.update(t=t, stop=stop)
    t.start()
