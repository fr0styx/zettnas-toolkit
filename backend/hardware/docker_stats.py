"""
ZettNAS Toolkit - Docker Introspection Subsystem
Queries local Docker daemon Unix socket (/var/run/docker.sock) for container
health, status, image tags, and uptime.
"""

import concurrent.futures
import http.client
import json
import os
import re
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.config import logger
from backend.state import Z_STATE

_CACHED_CONTAINERS: List[Dict[str, Any]] = []
_LAST_DOCKER_POLL = 0.0
_DOCKER_CACHE_TTL = 3.0
_CONTAINER_METRICS: Dict[str, Dict[str, Any]] = {}
_CONTAINER_INSPECT_CACHE: Dict[str, Dict[str, Any]] = {}
_TELEMETRY_THREAD_STARTED = False
_TELEMETRY_LOCK = threading.Lock()
_INSPECT_LOCK = threading.Lock()
_INSPECT_CACHE_TTL = 60.0

# Universal well-known HTTP web service ports (prioritized by common NAS services)
WELL_KNOWN_WEB_PORTS = [
    80,
    443,
    8080,
    8096,
    32400,
    2283,
    3000,
    5055,
    7878,
    8989,
    9696,
    8686,
    9000,
    8082,
    8081,
    8888,
    8191,
    6868,
    5000,
    8000,
    8443,
    9443,
    5001,
]


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str = "/var/run/docker.sock", timeout: float = 3.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def _parse_ports_and_webui(raw_ports: list, labels: dict) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
    """
    Parses container port bindings into a deduplicated, sorted list and resolves
    the primary Web UI port and URL template using universal heuristics.
    """
    parsed = []
    seen = set()
    for p in raw_ports or []:
        pub = p.get("PublicPort")
        priv = p.get("PrivatePort")
        proto = p.get("Type", "tcp").lower()
        key = (pub, priv, proto)
        if key not in seen:
            seen.add(key)
            parsed.append(
                {
                    "public_port": pub,
                    "private_port": priv,
                    "type": proto,
                    "ip": p.get("IP", "0.0.0.0"),
                }
            )

    # Sort so public ports appear first, ordered by port number
    parsed.sort(key=lambda x: (x["public_port"] is None, x["public_port"] or 0))

    webui_url: Optional[str] = None
    primary_port: Optional[int] = None

    # Heuristic 1: Unraid WebUI label (if present, replace [IP] with [HOST])
    unraid_webui = labels.get("net.unraid.docker.webui")
    if unraid_webui:
        match = re.search(r"\[PORT:(\d+)\]", unraid_webui)
        target_priv = int(match.group(1)) if match else None
        target_pub = target_priv
        if target_priv:
            for p in parsed:
                if p["private_port"] == target_priv and p["public_port"]:
                    target_pub = p["public_port"]
                    break
        webui_url = unraid_webui.replace("[IP]", "[HOST]")
        if target_pub:
            webui_url = re.sub(r"\[PORT:\d+\]", str(target_pub), webui_url)
            primary_port = target_pub

    # Heuristic 2: Traefik / Ingress labels (e.g. Host(`example.com`))
    if not webui_url:
        for k, v in labels.items():
            if k.startswith("traefik.http.routers.") and k.endswith(".rule") and "Host(" in v:
                m = re.search(r"Host\(`([^`]+)`\)", v)
                if m:
                    webui_url = f"http://{m.group(1)}/"
                    break

    # Heuristic 3: Well-known HTTP web service ports matching public bindings
    if not webui_url:
        pub_ports = [p["public_port"] for p in parsed if p["public_port"]]
        for wk in WELL_KNOWN_WEB_PORTS:
            if wk in pub_ports:
                primary_port = wk
                break
        if not primary_port and pub_ports:
            # Fallback to the first available public port
            primary_port = pub_ports[0]

        if primary_port:
            proto = "https" if primary_port in (443, 8443, 9443) else "http"
            webui_url = f"{proto}://[HOST]:{primary_port}/"

    return parsed, primary_port, webui_url


def _classify_stack(labels: dict) -> Tuple[Optional[str], Optional[str], str]:
    """
    Classifies container orchestrator stack origin (Compose, Dockhand, Unraid, Standalone).
    """
    stack = labels.get("com.docker.compose.project") or labels.get("io.portainer.stack.name") or None
    service = labels.get("com.docker.compose.service") or labels.get("org.opencontainers.image.title") or None
    managed = labels.get("net.unraid.docker.managed")

    if stack:
        managed_by = "compose"
    elif managed == "dockerman":
        managed_by = "unraid"
    else:
        managed_by = "standalone"

    return stack, service, managed_by


def _extract_hardware_badges(mounts: list, devices: list, env: list, runtime: str = "") -> List[Dict[str, str]]:
    """
    Hardware Abstraction Layer (HAL) badge detector.
    OS-agnostic: discovers DRM/DRI GPUs, AMD ROCm, NVIDIA CUDA, Coral TPUs, and USB serial adapters.
    """
    badges = []

    # 1. GPU / DRI (Intel / AMD / VirtIO / Panfrost render nodes)
    has_dri = any("dri" in (m.get("Source") or "") for m in mounts) or any(
        "dri" in (d.get("PathOnHost") or "") for d in devices
    )
    if has_dri:
        badges.append({"id": "gpu", "label": "GPU", "icon": "zap", "color": "var(--accent-cyan,#00f0ff)"})

    # 2. NVIDIA CUDA Acceleration
    has_nvidia = (
        runtime == "nvidia"
        or any("nvidia" in (d.get("PathOnHost") or "").lower() for d in devices)
        or any(e.startswith("NVIDIA_") or "CUDA_" in e for e in env)
    )
    if has_nvidia:
        badges.append({"id": "nvidia", "label": "NVIDIA", "icon": "cpu", "color": "#22c55e"})

    # 3. AMD ROCm / KFD
    has_rocm = any("kfd" in (m.get("Source") or "") for m in mounts) or any(
        "kfd" in (d.get("PathOnHost") or "") for d in devices
    )
    if has_rocm:
        badges.append({"id": "rocm", "label": "ROCm", "icon": "cpu", "color": "#ef4444"})

    # 4. Google Coral Edge TPU
    has_tpu = any("apex" in (d.get("PathOnHost") or "") for d in devices) or any(
        "coral" in (d.get("PathOnHost") or "").lower() for d in devices
    )
    if has_tpu:
        badges.append({"id": "tpu", "label": "TPU", "icon": "cpu", "color": "#10b981"})

    # 5. Serial / Zigbee / Z-Wave Coordinator Dongles
    has_serial = any(
        ("ttyUSB" in (d.get("PathOnHost") or "") or "ttyACM" in (d.get("PathOnHost") or "")) for d in devices
    )
    if has_serial:
        badges.append({"id": "serial", "label": "Serial", "icon": "radio", "color": "#f59e0b"})

    return badges


def _extract_appdata_path(mounts: list) -> Optional[str]:
    """
    Extracts container application config/data path on the host for File Explorer deep-linking.
    """
    for m in mounts:
        src = m.get("Source", "")
        dst = m.get("Destination", "")
        if "appdata" in src.lower() or dst in ("/config", "/data", "/app/data"):
            return src
    return None


def _fetch_container_inspect(cid_short: str, conn: Optional[UnixHTTPConnection] = None) -> Dict[str, Any]:
    """
    Fetches full container inspection JSON with thread-safe in-memory caching.
    """
    now = time.time()
    with _INSPECT_LOCK:
        cached = _CONTAINER_INSPECT_CACHE.get(cid_short)
        if cached and (now - cached.get("_ts", 0)) < _INSPECT_CACHE_TTL:
            return cached

    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return {}

    should_close = False
    if conn is None:
        try:
            conn = UnixHTTPConnection(sock_path, timeout=2.0)
            should_close = True
        except Exception:
            return {}

    try:
        conn.request("GET", f"/containers/{cid_short}/json")
        res = conn.getresponse()
        if res.status == 200:
            info = json.loads(res.read().decode("utf-8", errors="replace"))
            info["_ts"] = now
            with _INSPECT_LOCK:
                _CONTAINER_INSPECT_CACHE[cid_short] = info
            return info
    except Exception as e:
        logger.debug(f"[Docker] Inspect error for {cid_short}: {e}")
    finally:
        if should_close:
            try:
                conn.close()
            except Exception:
                pass
    return {}


def _fetch_container_telemetry(cid: str) -> Dict[str, Any]:
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return {}

    try:
        conn = UnixHTTPConnection(sock_path, timeout=2.5)
        conn.request("GET", f"/containers/{cid}/stats?stream=false")
        res = conn.getresponse()
        if res.status != 200:
            return {}

        stats = json.loads(res.read().decode("utf-8", errors="replace"))
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        mem_stats = stats.get("memory_stats", {})
        networks = stats.get("networks", {})

        # Calculate CPU %
        cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get("cpu_usage", {}).get(
            "total_usage", 0
        )
        sys_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)
        online_cpus = cpu_stats.get("online_cpus") or len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [1]))

        cpu_pct = 0.0
        if sys_delta > 0 and cpu_delta > 0 and online_cpus > 0:
            cpu_pct = round((cpu_delta / sys_delta) * online_cpus * 100.0, 1)

        # Calculate Memory (excluding kernel buffer/cache)
        mem_usage = mem_stats.get("usage", 0)
        stats_sub = mem_stats.get("stats", {})
        mem_cache = stats_sub.get("cache", 0) or stats_sub.get("inactive_file", 0)
        real_mem = max(0, mem_usage - mem_cache)
        mem_limit = mem_stats.get("limit", 1)
        mem_pct = round((real_mem / mem_limit) * 100.0, 1) if mem_limit > 0 else 0.0

        # Calculate Network I/O
        net_rx = sum(v.get("rx_bytes", 0) for v in networks.values()) if networks else 0
        net_tx = sum(v.get("tx_bytes", 0) for v in networks.values()) if networks else 0

        return {
            "cpu_pct": max(0.0, min(1000.0, cpu_pct)),
            "mem_used": real_mem,
            "mem_limit": mem_limit,
            "mem_pct": max(0.0, min(100.0, mem_pct)),
            "net_rx": net_rx,
            "net_tx": net_tx,
            "updated_at": time.time(),
        }
    except Exception as e:
        logger.debug(f"[Docker] Failed to fetch telemetry for {cid}: {e}")
        return {}


def _docker_telemetry_worker():
    while not Z_STATE.shutting_down:
        try:
            sock_path = "/var/run/docker.sock"
            if not os.path.exists(sock_path):
                for _ in range(10):
                    if Z_STATE.shutting_down:
                        break
                    time.sleep(0.5)
                continue

            conn = None
            running = []
            try:
                conn = UnixHTTPConnection(sock_path, timeout=3.0)
                conn.request("GET", "/containers/json?filters=%7B%22status%22%3A%5B%22running%22%5D%7D")
                res = conn.getresponse()
                if res.status == 200:
                    running = json.loads(res.read().decode("utf-8", errors="replace"))
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

            if not running:
                for _ in range(10):
                    if Z_STATE.shutting_down:
                        break
                    time.sleep(0.5)
                continue

            # Limit parallel queries to avoid burdening Docker daemon
            cids = [c["Id"] for c in running if "Id" in c][:16]
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(cids))) as pool:
                future_to_cid = {pool.submit(_fetch_container_telemetry, cid): cid for cid in cids}
                for fut in concurrent.futures.as_completed(future_to_cid, timeout=12.0):
                    cid = future_to_cid[fut]
                    try:
                        telemetry = fut.result()
                        if telemetry:
                            short_id = cid[:12]
                            with _TELEMETRY_LOCK:
                                _CONTAINER_METRICS[short_id] = telemetry
                    except Exception:
                        pass
            for _ in range(12):
                if Z_STATE.shutting_down:
                    break
                time.sleep(0.5)
        except Exception as e:
            logger.debug(f"[Docker] Telemetry worker error: {e}")
            for _ in range(10):
                if Z_STATE.shutting_down:
                    break
                time.sleep(0.5)


def start_docker_telemetry_collector():
    global _TELEMETRY_THREAD_STARTED
    if not _TELEMETRY_THREAD_STARTED:
        with _TELEMETRY_LOCK:
            if not _TELEMETRY_THREAD_STARTED:
                t = threading.Thread(target=_docker_telemetry_worker, daemon=True, name="DockerTelemetry")
                t.start()
                _TELEMETRY_THREAD_STARTED = True


def read_docker_containers(force: bool = False) -> List[Dict[str, Any]]:
    global _CACHED_CONTAINERS, _LAST_DOCKER_POLL
    now = time.time()
    if not force and _CACHED_CONTAINERS and (now - _LAST_DOCKER_POLL) < _DOCKER_CACHE_TTL:
        return _CACHED_CONTAINERS

    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return []

    start_docker_telemetry_collector()

    conn = None
    try:
        conn = UnixHTTPConnection(sock_path, timeout=3.0)
        conn.request("GET", "/containers/json?all=1")
        res = conn.getresponse()
        if res.status != 200:
            return _CACHED_CONTAINERS

        raw = json.loads(res.read().decode("utf-8", errors="replace"))
        out = []
        for c in raw:
            cid_full = c.get("Id", "")
            cid_short = cid_full[:12]
            names = c.get("Names", [])
            name = names[0].lstrip("/") if names else "unnamed"
            metrics = _CONTAINER_METRICS.get(cid_short, {})
            raw_ports = c.get("Ports", [])
            labels = c.get("Labels", {}) or {}
            raw_mounts = c.get("Mounts", []) or []

            # Ports & Universal WebUI resolution
            ports, primary_port, webui_url = _parse_ports_and_webui(raw_ports, labels)

            # Stack & Origin classification
            stack, service, managed_by = _classify_stack(labels)

            # Inspect data for hardware badges (fast cached query)
            inspect_info = _fetch_container_inspect(cid_short, conn=conn)
            devices = inspect_info.get("HostConfig", {}).get("Devices", []) or []
            env = inspect_info.get("Config", {}).get("Env", []) or []
            runtime = inspect_info.get("HostConfig", {}).get("Runtime", "")

            # HAL hardware badges (GPU, ROCm, NVIDIA, Coral, Serial)
            badges = _extract_hardware_badges(raw_mounts, devices, env, runtime=runtime)

            # Appdata path for File Explorer deep-linking
            appdata_path = _extract_appdata_path(raw_mounts)

            out.append(
                {
                    "id": cid_short,
                    "full_id": cid_full,
                    "name": name,
                    "image": c.get("Image", ""),
                    "state": c.get("State", "unknown"),
                    "status": c.get("Status", ""),
                    "created": c.get("Created", 0),
                    "cpu_pct": metrics.get("cpu_pct", 0.0),
                    "mem_used": metrics.get("mem_used", 0),
                    "mem_limit": metrics.get("mem_limit", 0),
                    "mem_pct": metrics.get("mem_pct", 0.0),
                    "net_rx": metrics.get("net_rx", 0),
                    "net_tx": metrics.get("net_tx", 0),
                    "stack": stack,
                    "service": service,
                    "managed_by": managed_by,
                    "ports": ports,
                    "primary_port": primary_port,
                    "webui_url": webui_url,
                    "hardware_badges": badges,
                    "mounts_count": len(raw_mounts),
                    "appdata_path": appdata_path,
                }
            )
        out.sort(key=lambda x: (x["state"] != "running", x["name"]))
        _CACHED_CONTAINERS = out
        _LAST_DOCKER_POLL = now
        return out
    except Exception as e:
        logger.debug(f"[Docker] Failed to introspect containers: {e}")
        return _CACHED_CONTAINERS
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def container_action(container_id: str, action: str) -> Dict[str, Any]:
    global _CACHED_CONTAINERS, _LAST_DOCKER_POLL
    # Sanitize container_id: alphanumeric only, 1-64 chars
    if not container_id or not container_id.isalnum() or len(container_id) > 64:
        return {"success": False, "error": "Invalid container ID"}

    action = action.lower().strip()
    if action not in ("start", "stop", "restart", "pause", "unpause"):
        return {"success": False, "error": f"Unsupported action: {action}"}

    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return {"success": False, "error": "Docker socket not available"}

    endpoint = f"/containers/{container_id}/{action}"
    if action in ("stop", "restart"):
        endpoint += "?t=10"

    try:
        conn = UnixHTTPConnection(sock_path, timeout=15.0)
        conn.request("POST", endpoint)
        res = conn.getresponse()
        resp_data = res.read().decode("utf-8", errors="replace")

        # 204 No Content, 200 OK, or 304 Not Modified
        if res.status in (200, 204, 304):
            _CACHED_CONTAINERS = []
            _LAST_DOCKER_POLL = 0.0
            with _INSPECT_LOCK:
                _CONTAINER_INSPECT_CACHE.clear()
            return {"success": True, "action": action, "id": container_id}

        err_msg = f"HTTP {res.status}"
        try:
            parsed = json.loads(resp_data)
            if "message" in parsed:
                err_msg = parsed["message"]
        except Exception:
            if resp_data:
                err_msg = resp_data
        return {"success": False, "error": err_msg}
    except Exception as e:
        logger.error(f"[Docker] Failed to perform {action} on {container_id}: {e}")
        return {"success": False, "error": str(e)}
