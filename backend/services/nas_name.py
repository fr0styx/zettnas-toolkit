"""Find the NAS by name (NFEAT-8): <name>.local on the home network, in Finder and Windows.

The responder (mdns_responder.py) needs the host's network to reach the LAN's multicast, which the
app's own container doesn't have, so it runs in a small container of its own on the host network,
made from the app's image (D17). This module starts, updates and removes that container and keeps
the setting: off until the person turns it on and confirms (the Docker guard lets a container on
the host's network through only then; the yes is remembered, so an update or a rename can make it
again), the name, and the names the NAS had before.

The rebrand: DEFAULT_NAME is the one place the product's name is used. After the rebrand, the old
name goes into PREVIOUS_NAMES so bookmarks, saved shares and Finder favourites keep working; a name
the family changes in the settings is kept the same way.
"""

import hashlib
import json
import os
import re
import socket
import threading
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

DEFAULT_NAME = "zettnas"  # the rebrand changes this, and adds "zettnas" to PREVIOUS_NAMES
DEFAULT_LABEL = "ZettNAS"  # how Finder lists the NAS when it has the default name
PREVIOUS_NAMES: tuple[str, ...] = ()  # names that still answer after a rename of the product
KEEP_OLD = 3  # names the family used before that still answer
CONTAINER = "zettnas-name"
RESPONDER = "/app/backend/services/mdns_responder.py"
STATE_FILE = os.path.join(DATA_DIR, "nas_name.json")
ELEVATED = {"X-ZettNAS-Elevated": "1"}
_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_lock = threading.Lock()
NO_DOCKER = "Docker is not reachable, so the name can't be announced."


def valid(name: str) -> bool:
    return bool(_NAME.match(name or ""))


def config() -> dict[str, Any]:
    """{enabled, name, previous}: what is saved, else off with the default name (or KIBOTO_NAS_NAME)."""
    from backend import settings

    data = read_json(STATE_FILE, {})
    data = data if isinstance(data, dict) else {}
    name = str(data.get("name") or settings.current("nas_name") or DEFAULT_NAME).lower()
    previous = [p for p in data.get("previous", []) if isinstance(p, str) and valid(p)]
    return {
        "enabled": bool(data.get("enabled", False)),
        "name": name if valid(name) else DEFAULT_NAME,
        "previous": previous,
    }


def answering_names(cfg: dict[str, Any]) -> list[str]:
    """The name first, then the names it had before (the family's and the product's)."""
    out: list[str] = []
    for n in [cfg["name"], *cfg.get("previous", []), *PREVIOUS_NAMES]:
        if valid(n) and n not in out:
            out.append(n)
    return out


def label(name: str) -> str:
    return DEFAULT_LABEL if name == DEFAULT_NAME else name


def save(enabled: bool | None = None, name: str | None = None) -> dict[str, Any]:
    """Changes the setting; a new name keeps the old one answering. Raises ValueError for a bad name."""
    with _lock:
        cfg = config()
        if name is not None:
            name = name.strip().lower().removesuffix(".local")
            if not valid(name):
                raise ValueError("Use letters, digits and dashes (up to 63), not starting or ending with a dash.")
            if name != cfg["name"]:
                cfg["previous"] = [cfg["name"], *[p for p in cfg["previous"] if p not in (cfg["name"], name)]][
                    :KEEP_OLD
                ]
                cfg["name"] = name
        if enabled is not None:
            cfg["enabled"] = bool(enabled)
        atomic_write_json(STATE_FILE, cfg)
    return ensure()


# --- the container ---------------------------------------------------------------------------------
def _docker(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, Any]:
    from backend.services.container_mutator import docker_request

    try:
        return docker_request(method, path, body=body, headers=headers)
    except (OSError, RuntimeError):  # no Docker socket (or it refused): the same as no answer
        logger.debug("[NasName] Docker did not answer %s %s", method, path, exc_info=True)
        return 0, None


def _self() -> dict[str, Any]:
    for ref in (socket.gethostname(), "zettnas-toolkit"):
        code, info = _docker("GET", f"/containers/{ref}/json")
        if code == 200 and isinstance(info, dict):
            return info
    return {}


def web_port(me: dict[str, Any]) -> int:
    """The port the web page has on the host: the app's own when it shares the host's network, else
    the host port published for it."""
    from backend import settings

    inner = int(settings.current("port") or 8082)
    host_cfg = me.get("HostConfig") or {}
    if host_cfg.get("NetworkMode") == "host":
        return inner
    for binding in (host_cfg.get("PortBindings") or {}).get(f"{inner}/tcp") or []:
        if str(binding.get("HostPort") or "").isdigit():
            return int(binding["HostPort"])
    return inner


def timemachine_shares() -> list[str]:
    """ZettNAS's own Time Machine shares, while its own Samba serves them. A host's Samba (Unraid's,
    TrueNAS's) announces its Time Machine shares itself."""
    from backend.services.samba_engine import get_samba_engine

    engine = get_samba_engine()
    if engine.check_sidecar().get("state") != "running":
        return []
    return sorted(s.name for s in engine.list_shares() if s.timemachine)


def desired(me: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """The container: the app's image, the responder, the host's network, nothing mounted."""
    names = answering_names(cfg)
    cmd = [RESPONDER, "--names", ",".join(names), "--label", label(cfg["name"]), "--http-port", str(web_port(me))]
    for share in timemachine_shares():
        cmd += ["--timemachine", share]
    image = (me.get("Config") or {}).get("Image") or "ghcr.io/fr0styx/zettnas-toolkit:latest"
    want: dict[str, Any] = {
        "Image": image,
        "Entrypoint": ["python3"],
        "Cmd": cmd,
        "Healthcheck": {"Test": ["NONE"]},  # the image's own check asks the web app, which isn't here
        "HostConfig": {"NetworkMode": "host", "RestartPolicy": {"Name": "unless-stopped"}, "ReadonlyRootfs": True},
    }
    fingerprint = hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()[:16]
    want["Labels"] = {"app": CONTAINER, "managed-by": "zettnas-toolkit", "zettnas.config": fingerprint}
    return want


def refresh() -> None:
    """After a share change: the name service announces the Time Machine shares there are now."""
    if config()["enabled"]:
        threading.Thread(target=ensure, name="nas-name-refresh", daemon=True).start()


def _remove() -> None:
    _docker("POST", f"/containers/{CONTAINER}/stop?t=3")  # it says goodbye, so devices drop the name at once
    _docker("DELETE", f"/containers/{CONTAINER}?force=true")


def ensure() -> dict[str, Any]:
    """Makes the container match the setting (started, recreated after an update or a rename, or
    removed) and says how it stands."""
    cfg = config()
    with _lock:
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        exists = code == 200 and isinstance(info, dict)
        if not cfg["enabled"]:
            if exists:
                _remove()
                logger.info("[NasName] Turned off; %s removed", CONTAINER)
            return status(cfg, running=False)
        me = _self()
        if not me:
            return status(cfg, running=False, error=NO_DOCKER)
        want = desired(me, cfg)
        if exists:
            same = (info.get("Config") or {}).get("Labels", {}).get("zettnas.config") == want["Labels"][
                "zettnas.config"
            ]
            running = bool((info.get("State") or {}).get("Running"))
            if same and running:
                return status(cfg, running=True, port=web_port(me))
            if same:
                start, _ = _docker("POST", f"/containers/{CONTAINER}/start")
                return status(cfg, running=start in (200, 204, 304), port=web_port(me))
            _remove()
        # the host's network: the person said yes when turning it on (Docker guard, ELEVATED)
        created, resp = _docker("POST", f"/containers/create?name={CONTAINER}", want, ELEVATED)
        if created not in (200, 201):
            logger.warning("[NasName] Could not create %s: %s %s", CONTAINER, created, resp)
            return status(cfg, running=False, error="The name service could not be started.")
        started, _ = _docker("POST", f"/containers/{CONTAINER}/start")
        logger.info("[NasName] %s answers for %s", CONTAINER, ", ".join(f"{n}.local" for n in answering_names(cfg)))
        return status(cfg, running=started in (200, 204, 304), port=web_port(me))


def status(
    cfg: dict[str, Any] | None = None, running: bool | None = None, port: int | None = None, error: str = ""
) -> dict[str, Any]:
    cfg = cfg or config()
    if running is None:
        code, info = _docker("GET", f"/containers/{CONTAINER}/json")
        running = code == 200 and bool(((info or {}).get("State") or {}).get("Running"))
        if code == 0 and cfg["enabled"]:
            error = error or NO_DOCKER
    if port is None:
        port = web_port(_self())
    host = f"{cfg['name']}.local"
    return {
        "enabled": cfg["enabled"],
        "name": cfg["name"],
        "also_answers": answering_names(cfg)[1:],
        "running": running,
        "address": host,
        "url": f"http://{host}" + ("" if port == 80 else f":{port}"),
        "error": error,
    }


def ensure_soon() -> None:
    """At startup, on a thread: the app's image may have changed with an update."""

    def run() -> None:
        try:
            ensure()
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("[NasName] Could not check the name service", exc_info=True)

    threading.Thread(target=run, name="nas-name", daemon=True).start()
