"""The hardware helper's container (SEC-24 step 2): made from the app's image, it alone opens /dev/mem.

Off until turned on and confirmed (the Docker guard lets a container with SYS_RAWIO and /dev/mem
through only then). It has no network, drops every capability but SYS_RAWIO, runs read-only, and
shares one folder with Kiboto: <Kiboto's data folder>/hw, where the helper's socket lives. While it
answers, Kiboto's fans and front button go through it (hardware/hw_client.py), and the next update
leaves SYS_RAWIO and the /dev/mem device rule out of Kiboto's own container (self_updater).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any

from backend import product
from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json
from backend.hardware import hw_client

CONTAINER = "kiboto-hw"
CONFIG_FILE = os.path.join(DATA_DIR, "hw_helper.json")
SOCKET_DIR_IN_HELPER = "/run/kiboto-hw"
ELEVATED = {"X-Kiboto-Elevated": "1"}
NO_DOCKER = "Docker didn't answer, so the helper can't be started."
_lock = threading.Lock()


def config() -> dict[str, Any]:
    data = read_json(CONFIG_FILE, {})
    data = data if isinstance(data, dict) else {}
    # dropped: the last update left raw hardware access out of Kiboto's own container (self_updater)
    return {"enabled": bool(data.get("enabled")), "dropped": bool(data.get("dropped"))}


def _docker(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, Any]:
    from backend.services.container_mutator import docker_request

    try:
        return docker_request(method, path, body=body, headers=headers)
    except (OSError, RuntimeError):
        logger.debug("[hw-helper] Docker did not answer %s %s", method, path, exc_info=True)
        return 0, None


def _self() -> dict[str, Any]:
    from backend.services import nas_name

    return nas_name._self()


def applies() -> bool:
    """Only Zettlab boxes have the fan and button registers the helper serves."""
    from backend.hardware.fans import ZettlabMmioFanController

    try:
        return hw_client.available() or ZettlabMmioFanController().is_available()
    except (OSError, ValueError, RuntimeError):
        return False


def host_data_dir(me: dict[str, Any]) -> str:
    """Where Kiboto's data folder is on the host (the helper's socket folder sits inside it)."""
    for m in me.get("Mounts") or []:
        if m.get("Destination") == DATA_DIR and m.get("Type") == "bind" and str(m.get("Source", "")).startswith("/"):
            return str(m["Source"])
    return ""


def desired(me: dict[str, Any]) -> dict[str, Any]:
    image = (me.get("Config") or {}).get("Image") or product.IMAGE + ":latest"
    data = host_data_dir(me)
    want: dict[str, Any] = {
        "Image": image,
        "Entrypoint": ["python3"],
        "Cmd": ["-m", "backend.hw_helper", "--socket", f"{SOCKET_DIR_IN_HELPER}/hw.sock"],
        "WorkingDir": "/app",
        "Healthcheck": {"Test": ["NONE"]},  # the image's check asks the web app, which isn't here
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "CapAdd": ["SYS_RAWIO"],
            "Devices": [{"PathOnHost": "/dev/mem", "PathInContainer": "/dev/mem", "CgroupPermissions": "rw"}],
            "Binds": [f"{data}/hw:{SOCKET_DIR_IN_HELPER}"],
            "RestartPolicy": {"Name": "unless-stopped"},
        },
    }
    fingerprint = hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()[:16]
    want["Labels"] = {"app": CONTAINER, "managed-by": product.CONTAINER, "kiboto.config": fingerprint}
    return want


def status(running: bool | None = None, error: str = "") -> dict[str, Any]:
    cfg = config()
    if running is None:
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        running = code == 200 and isinstance(info, dict) and bool((info.get("State") or {}).get("Running"))
    return {
        "enabled": cfg["enabled"],
        # Kiboto gave its own access up at an update: the helper keeps running until one gives it back
        "kept_until_update": cfg["dropped"] and not cfg["enabled"],
        "app_without_raw_access": cfg["dropped"],
        "running": bool(running),
        "answering": hw_client.available(force=True) if running else False,
        "applies": applies(),
        "error": error,
    }


def ready() -> bool:
    """On and answering: an update may then leave raw hardware access out of Kiboto's container."""
    return config()["enabled"] and hw_client.available(force=True)


def _remove() -> None:
    _docker("POST", f"/containers/{CONTAINER}/stop?t=3")
    _docker("DELETE", f"/containers/{CONTAINER}?force=true")


def ensure() -> dict[str, Any]:
    """Makes the helper container match the setting: started, recreated after an update, or removed."""
    cfg = config()
    with _lock:
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        exists = code == 200 and isinstance(info, dict)
        if not cfg["enabled"] and cfg["dropped"]:
            # Kiboto has no /dev/mem of its own until the next update gives it back: the fans need the helper
            if exists and not (info.get("State") or {}).get("Running"):
                _docker("POST", f"/containers/{CONTAINER}/start")
            return status()
        if not cfg["enabled"]:
            if exists:
                _remove()
                logger.info("[hw-helper] Turned off; %s removed", CONTAINER)
            hw_client.forget()
            return status(running=False)
        me = _self()
        if not me:
            return status(running=False, error=NO_DOCKER)
        if not host_data_dir(me):
            return status(
                running=False, error="Kiboto's data folder isn't a folder on the host, so the helper can't share it."
            )
        os.makedirs(os.path.join(DATA_DIR, "hw"), mode=0o770, exist_ok=True)
        want = desired(me)
        if exists:
            same = (info.get("Config") or {}).get("Labels", {}).get("kiboto.config") == want["Labels"]["kiboto.config"]
            if same and (info.get("State") or {}).get("Running"):
                return status(running=True)
            if same:
                _docker("POST", f"/containers/{CONTAINER}/start")
                hw_client.forget()
                return status()
            _remove()
        # /dev/mem and SYS_RAWIO: the person said yes when turning it on (Docker guard, ELEVATED)
        created, resp = _docker("POST", f"/containers/create?name={CONTAINER}", want, ELEVATED)
        if created not in (200, 201):
            logger.warning("[hw-helper] Could not create %s: %s %s", CONTAINER, created, resp)
            return status(running=False, error="The hardware helper could not be started.")
        _docker("POST", f"/containers/{CONTAINER}/start")
        hw_client.forget()
        logger.info("[hw-helper] %s started; fans and the button go through it", CONTAINER)
        return status()


def save(enabled: bool) -> dict[str, Any]:
    atomic_write_json(CONFIG_FILE, {**config(), "enabled": bool(enabled)})
    return ensure()


def ensure_soon() -> None:
    """At start: bring the helper back after an update (its image follows the app's)."""
    if config()["enabled"]:
        threading.Thread(target=ensure, name="hw-helper-ensure", daemon=True).start()
