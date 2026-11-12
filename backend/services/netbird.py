"""NetBird, a second way in beside Tailscale and Headscale (SET-16N; the owner's yes of 12 Nov 2026).

Kiboto runs the official NetBird client in a container on the host's network, joined with a setup
key from NetBird Cloud (free for 5 people and 100 devices) or from the person's own NetBird server
(its management address). Nothing is opened on the router. Disconnect leaves the network and keeps
the container and its sign-in for next time.
"""

import json
import os
import re
from typing import Any

from backend import config
from backend.config import logger
from backend.fsutil import atomic_write_json, read_json

CONTAINER = "netbird"
IMAGE = "netbirdio/netbird"
TAG = "latest"
SETTINGS_FILE = os.path.join(config.DATA_DIR, "netbird.json")
# a setup key is a UUID (NetBird Cloud and self-hosted); refuse anything that could reach a shell
_KEY = re.compile(r"^[A-Za-z0-9-]{20,64}$")
_URL = re.compile(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?/?$")


class NetbirdError(Exception):
    """A connection that could not be made, in words the page shows."""


def settings() -> dict[str, Any]:
    data = read_json(SETTINGS_FILE, {})
    return data if isinstance(data, dict) else {}


def _docker(method: str, path: str, body: Any = None, headers: dict | None = None) -> tuple[int, Any]:
    from backend.services.container_mutator import _docker_request

    try:
        return _docker_request(method, path, body=body, headers=headers)
    except RuntimeError as e:  # no Docker socket: said as a NetBird failure, never a 500
        raise NetbirdError(f"Docker can't be reached: {e}") from None


def _pull() -> None:
    """Fetches the NetBird image when it is not here; a pull streams for minutes, so it is read as a stream."""
    from backend.hardware.docker_stats import UnixHTTPConnection
    from backend.hardware.net import common

    st, _ = _docker("GET", f"/images/{IMAGE}:{TAG}/json")
    if st == 200:
        return
    conn = UnixHTTPConnection(common.docker_sock(), timeout=300.0)
    try:
        conn.request("POST", f"/images/create?fromImage={IMAGE}&tag={TAG}")
        res = conn.getresponse()
        while res.read(4096):
            pass
    except OSError as e:
        logger.warning("[NetBird] image pull: %s", e)
    finally:
        conn.close()


def container() -> dict[str, Any]:
    """{exists, running} of the NetBird container."""
    try:
        st, info = _docker("GET", f"/containers/{CONTAINER}/json")
    except NetbirdError:
        return {"exists": False, "running": False}
    if st != 200 or not isinstance(info, dict):
        return {"exists": False, "running": False}
    return {"exists": True, "running": bool((info.get("State") or {}).get("Running"))}


def _exec(args: list[str]) -> tuple[int, str]:
    from backend.services.compose_synthesizer import execute_in_container

    res = execute_in_container(CONTAINER, ["netbird", *args])
    if not res.get("success"):
        return 1, str(res.get("error") or "the NetBird container did not answer")
    return int(res.get("exit_code", 0)), str(res.get("output") or "").strip()


def parse_status(out: str) -> dict[str, Any]:
    """`netbird status --json` in the words the card uses (unknown fields are ignored)."""
    try:
        doc = json.loads(out[out.index("{") :]) if "{" in out else {}
    except ValueError:
        doc = {}
    mgmt = doc.get("management") or {}
    peers = doc.get("peers") or {}
    ip = str(doc.get("netbirdIp") or "").split("/")[0]
    return {
        "connected": bool(mgmt.get("connected")) and bool(ip),
        "ip": ip,
        "name": str(doc.get("fqdn") or ""),
        "management": str(mgmt.get("url") or ""),
        "peers_connected": int(peers.get("connected") or 0),
        "peers_total": int(peers.get("total") or 0),
    }


def status() -> dict[str, Any]:
    """NotInstalled, Stopped, Disconnected or Connected, with the address when connected."""
    c = container()
    if not c["exists"]:
        return {"state": "NotInstalled"}
    if not c["running"]:
        return {"state": "Stopped"}
    code, out = _exec(["status", "--json"])
    s = parse_status(out) if code == 0 else {"connected": False}
    return {"state": "Connected" if s.get("connected") else "Disconnected", **s}


def _checked(setup_key: str, management_url: str) -> tuple[str, str]:
    key = (setup_key or "").strip()
    url = (management_url or "").strip().rstrip("/")
    if not _KEY.fullmatch(key):
        raise NetbirdError("Paste the setup key from NetBird (Setup Keys in its dashboard).")
    if url and not _URL.fullmatch(url):
        raise NetbirdError("Your own NetBird server's address starts with https:// and has no path.")
    return key, url


def _state_dir() -> str:
    """Where NetBird keeps its sign-in: appdata on Unraid, else Kiboto's data folder."""
    return (
        "/mnt/user/appdata/netbird" if os.path.isdir("/mnt/user/appdata") else os.path.join(config.DATA_DIR, "netbird")
    )


def _create(key: str, url: str) -> None:
    state_dir = _state_dir()
    os.makedirs(state_dir, exist_ok=True)
    _pull()
    env = [f"NB_SETUP_KEY={key}", "NB_HOSTNAME=kiboto"] + ([f"NB_MANAGEMENT_URL={url}"] if url else [])
    body = {
        "Image": f"{IMAGE}:{TAG}",
        "Env": env,
        "HostConfig": {
            "NetworkMode": "host",
            "CapAdd": ["NET_ADMIN", "SYS_ADMIN", "SYS_RESOURCE"],
            "Binds": [f"{state_dir}:/var/lib/netbird"],
            "Devices": [{"PathOnHost": "/dev/net/tun", "PathInContainer": "/dev/net/tun", "CgroupPermissions": "rwm"}],
            "RestartPolicy": {"Name": "unless-stopped"},
        },
        "Labels": {"net.unraid.docker.managed": "dockerman", "app.name": "NetBird"},
    }
    # the host's network and the right to change it: the routes asked first (network.netbird_install)
    st, res = _docker("POST", f"/containers/create?name={CONTAINER}", body=body, headers={"X-Kiboto-Elevated": "1"})
    if st != 201:
        raise NetbirdError(
            f"The NetBird container could not be created: {(res or {}).get('message', res) if isinstance(res, dict) else res}"
        )
    st, res = _docker("POST", f"/containers/{CONTAINER}/start")
    if st not in (204, 304):
        raise NetbirdError("The NetBird container did not start.")


def connect(setup_key: str, management_url: str = "") -> dict[str, Any]:
    """Joins NetBird: creates the container when it is not here, else signs it in with the key."""
    key, url = _checked(setup_key, management_url)
    c = container()
    if not c["exists"]:
        _create(key, url)
    else:
        if not c["running"]:
            _docker("POST", f"/containers/{CONTAINER}/start")
        code, out = _exec(["up", "--setup-key", key, *(["--management-url", url] if url else [])])
        if code != 0:
            raise NetbirdError(f"NetBird did not connect: {out[:200]}")
    atomic_write_json(SETTINGS_FILE, {"management_url": url})
    logger.info("[NetBird] connected%s", f" to {url}" if url else " to NetBird Cloud")
    return status()


def disconnect() -> dict[str, Any]:
    """Leaves the NetBird network; the container and its sign-in stay for next time."""
    if container()["running"]:
        _exec(["down"])
    return status()
