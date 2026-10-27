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
from typing import Any, Optional

from backend.config import docker_sock, logger
from backend.hardware import cgroup_stats
from backend.state import Z_STATE

_CACHED_CONTAINERS: list[dict[str, Any]] = []
_LAST_DOCKER_POLL = 0.0
_DOCKER_CACHE_TTL = 3.0  # while someone watches
_DOCKER_IDLE_TTL = 30.0  # PERF-5: nobody watching, so the 2 s loop needn't ask dockerd every other tick


def _docker_ttl() -> float:
    try:
        from backend.services.broadcaster import broadcaster

        return _DOCKER_CACHE_TTL if broadcaster.get_subscriber_count() else _DOCKER_IDLE_TTL
    except Exception:
        return _DOCKER_CACHE_TTL


_CONTAINER_METRICS: dict[str, dict[str, Any]] = {}

# Container stats refresh often only while someone is looking (PERF-6): a browser on the live
# stats stream, or a request for the container list in the last DEMAND_WINDOW_SECS.
ACTIVE_POLL_SECS = 6.0
IDLE_POLL_SECS = 60.0
DEMAND_WINDOW_SECS = 60.0
_VIEWERS = 0
_LAST_DEMAND = 0.0
_DEMAND_LOCK = threading.Lock()
_DEMAND_WAKE = threading.Event()
BACKOFF_SECS = 5.0  # no Docker socket, no running containers, or an error
# container id -> (total CPU usage, system CPU usage) from the previous one-shot sample
_PREV_CPU: dict[str, tuple[int, int]] = {}


def note_container_demand() -> None:
    """Someone wants fresh container stats: poll at the active rate, starting now."""
    global _LAST_DEMAND
    _LAST_DEMAND = time.time()
    _DEMAND_WAKE.set()


def viewer_joined() -> None:
    global _VIEWERS
    with _DEMAND_LOCK:
        _VIEWERS += 1
    note_container_demand()


def viewer_left() -> None:
    global _VIEWERS
    with _DEMAND_LOCK:
        _VIEWERS = max(0, _VIEWERS - 1)


def container_poll_interval(now: float | None = None) -> float:
    now = time.time() if now is None else now
    if _VIEWERS > 0 or now - _LAST_DEMAND < DEMAND_WINDOW_SECS:
        return ACTIVE_POLL_SECS
    return IDLE_POLL_SECS


def _cpu_pct(cid: str, cpu_stats: dict, precpu_stats: dict) -> float:
    """CPU % from Docker's own previous sample when it sends one, else from ours (one-shot stats)."""
    total = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) or 0
    system = cpu_stats.get("system_cpu_usage", 0) or 0
    prev = _PREV_CPU.get(cid)
    _PREV_CPU[cid] = (total, system)
    pre_total = precpu_stats.get("cpu_usage", {}).get("total_usage", 0) or 0
    pre_system = precpu_stats.get("system_cpu_usage", 0) or 0
    if not pre_system and prev:
        pre_total, pre_system = prev
    cpu_delta, sys_delta = total - pre_total, system - pre_system
    online_cpus = cpu_stats.get("online_cpus") or len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [1]))
    if sys_delta > 0 and cpu_delta > 0 and online_cpus > 0:
        return round((cpu_delta / sys_delta) * online_cpus * 100.0, 1)
    return 0.0


_CONTAINER_INSPECT_CACHE: dict[str, dict[str, Any]] = {}
_TELEMETRY_THREAD_STARTED = False
_TELEMETRY_LOCK = threading.Lock()
_INSPECT_LOCK = threading.Lock()
# A container's inspect data changes only when it is recreated, which gives it a new id (a cache
# miss anyway); refreshed every 10 minutes for the rest (PERF-5: was 60 s)
_INSPECT_CACHE_TTL = 600.0

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


from backend.services.docker_client import UnixHTTPConnection  # noqa: E402,F401  (one client, ARCH-3)


def _parse_ports_and_webui(
    raw_ports: list,
    labels: dict,
    network_mode: str = "",
    exposed_ports: dict | None = None,
) -> tuple[list[dict[str, Any]], int | None, str | None]:
    """
    Parses container port bindings into a deduplicated, sorted list and resolves
    the primary Web UI port and URL template using universal heuristics.
    Supports bridge/NAT published ports and host-network exposed ports.
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
                    "is_host_network": p.get("is_host_network", False),
                }
            )

    is_host = network_mode == "host" or "host" in str(network_mode).lower()
    if not parsed and is_host and exposed_ports:
        for ep in (exposed_ports or {}).keys():
            port_part = ep.split("/")[0] if "/" in ep else ep
            proto_part = ep.split("/")[1] if "/" in ep else "tcp"
            if port_part.isdigit():
                port_num = int(port_part)
                parsed.append(
                    {
                        "public_port": port_num,
                        "private_port": port_num,
                        "type": proto_part.lower(),
                        "ip": "host",
                        "is_host_network": True,
                    }
                )

    # Sort so public ports appear first, ordered by port number
    parsed.sort(key=lambda x: (x["public_port"] is None, x["public_port"] or 0))

    webui_url: str | None = None
    primary_port: int | None = None

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
            webui_url = re.sub(r"\[PORT:\d+\]", str(target_pub), webui_url or "")
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


def _classify_stack(labels: dict) -> tuple[str | None, str | None, str]:
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


def _extract_hardware_badges(mounts: list, devices: list, env: list, runtime: str = "") -> list[dict[str, str]]:
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


def _extract_appdata_path(mounts: list) -> str | None:
    """
    Extracts container application config/data path on the host for File Explorer deep-linking.
    """
    for m in mounts:
        src = m.get("Source", "")
        dst = m.get("Destination", "")
        if "appdata" in src.lower() or dst in ("/config", "/data", "/app/data"):
            return src
    return None


def _fetch_container_inspect(cid_short: str, conn: UnixHTTPConnection | None = None) -> dict[str, Any]:
    """
    Fetches full container inspection JSON with thread-safe in-memory caching.
    """
    now = time.time()
    with _INSPECT_LOCK:
        cached = _CONTAINER_INSPECT_CACHE.get(cid_short)
        if cached and (now - cached.get("_ts", 0)) < _INSPECT_CACHE_TTL:
            return cached

    sock_path = docker_sock()
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
                logger.debug("backend.hardware.docker_stats._fetch_container_inspect: ignored error", exc_info=True)
    return {}


def _kernel_telemetry(cid: str) -> dict[str, Any] | None:
    """CPU, memory and network from the kernel's files (PERF-4); None when they cannot be read."""
    info = _fetch_container_inspect(cid[:12]) or {}
    pid = int((info.get("State") or {}).get("Pid") or 0)
    if pid and not cgroup_stats.owns(pid, cid):
        # restarted since we last looked: its main process has a new number
        with _INSPECT_LOCK:
            _CONTAINER_INSPECT_CACHE.pop(cid[:12], None)
        info = _fetch_container_inspect(cid[:12]) or {}
        pid = int((info.get("State") or {}).get("Pid") or 0)
    host_net = (info.get("HostConfig") or {}).get("NetworkMode") == "host"
    return cgroup_stats.telemetry(cid, pid, host_net)


def _fetch_container_telemetry(cid: str) -> dict[str, Any]:
    # the kernel's own counters first: no work for dockerd. Its stats answer the rest (a layout
    # we cannot read, and each container's first round, since a CPU % needs two samples).
    try:
        fast = _kernel_telemetry(cid)
        if fast:
            return fast
    except Exception:
        logger.debug("backend.hardware.docker_stats._fetch_container_telemetry: no kernel stats", exc_info=True)
    sock_path = docker_sock()
    if not os.path.exists(sock_path):
        return {}

    try:
        conn = UnixHTTPConnection(sock_path, timeout=2.5)
        # one-shot: Docker answers at once instead of sampling twice a second apart. The first
        # request for a container still takes Docker's two samples, so its CPU % is right at once.
        one_shot = "&one-shot=true" if cid in _PREV_CPU else ""
        conn.request("GET", f"/containers/{cid}/stats?stream=false{one_shot}")
        res = conn.getresponse()
        if res.status != 200:
            return {}

        stats = json.loads(res.read().decode("utf-8", errors="replace"))
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        mem_stats = stats.get("memory_stats", {})
        networks = stats.get("networks", {})

        cpu_pct = _cpu_pct(cid, cpu_stats, precpu_stats)

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
            sock_path = docker_sock()
            if not os.path.exists(sock_path):
                time.sleep(BACKOFF_SECS)  # one sleep, not ten slices (PERF-5)
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
                        logger.debug(
                            "backend.hardware.docker_stats._docker_telemetry_worker: ignored error", exc_info=True
                        )

            if not running:
                time.sleep(BACKOFF_SECS)  # one sleep, not ten slices (PERF-5)
                continue

            # Dynamic worker querying all running containers with adaptive concurrency
            cids = [c["Id"] for c in running if "Id" in c]
            max_parallel = min(8, max(2, len(cids) // 4)) if cids else 2
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_parallel, len(cids))) as pool:
                future_to_cid = {pool.submit(_fetch_container_telemetry, cid): cid for cid in cids}
                for fut in concurrent.futures.as_completed(future_to_cid, timeout=15.0):
                    cid = future_to_cid[fut]
                    try:
                        telemetry = fut.result()
                        if telemetry:
                            short_id = cid[:12]
                            with _TELEMETRY_LOCK:
                                _CONTAINER_METRICS[short_id] = telemetry
                    except Exception:
                        logger.debug(
                            "backend.hardware.docker_stats._docker_telemetry_worker: ignored error", exc_info=True
                        )
            for gone in set(_PREV_CPU) - set(cids):
                _PREV_CPU.pop(gone, None)
            cgroup_stats.forget(set(cids))
            _DEMAND_WAKE.clear()
            deadline = time.time() + container_poll_interval()
            while not Z_STATE.shutting_down and time.time() < deadline:
                # one wait until the next round (PERF-5: it used to wake every 0.5 s)
                if _DEMAND_WAKE.wait(max(0.0, deadline - time.time())):
                    break  # someone started looking: refresh now
        except Exception as e:
            logger.debug(f"[Docker] Telemetry worker error: {e}")
            time.sleep(BACKOFF_SECS)  # one sleep, not ten slices (PERF-5)


def start_docker_telemetry_collector():
    global _TELEMETRY_THREAD_STARTED
    if not _TELEMETRY_THREAD_STARTED:
        with _TELEMETRY_LOCK:
            if not _TELEMETRY_THREAD_STARTED:
                t = threading.Thread(target=_docker_telemetry_worker, daemon=True, name="DockerTelemetry")
                t.start()
                _TELEMETRY_THREAD_STARTED = True


_INSPECT_POOL: concurrent.futures.ThreadPoolExecutor | None = None


def _inspect_pool() -> concurrent.futures.ThreadPoolExecutor:
    """One small pool for container inspections, kept, instead of a new pool of threads each time."""
    global _INSPECT_POOL
    if _INSPECT_POOL is None:
        _INSPECT_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="DockerInspect")
    return _INSPECT_POOL


def read_docker_containers(force: bool = False) -> list[dict[str, Any]]:
    global _CACHED_CONTAINERS, _LAST_DOCKER_POLL
    now = time.time()
    if not force and _CACHED_CONTAINERS and (now - _LAST_DOCKER_POLL) < _docker_ttl():
        return _CACHED_CONTAINERS

    sock_path = docker_sock()
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

        # Batch concurrent inspection for cache misses / expired inspects
        cids_to_inspect = []
        with _INSPECT_LOCK:
            for c in raw:
                cid_short = c.get("Id", "")[:12]
                cached = _CONTAINER_INSPECT_CACHE.get(cid_short)
                if not cached or (now - cached.get("_ts", 0)) >= _INSPECT_CACHE_TTL:
                    cids_to_inspect.append(cid_short)

        if cids_to_inspect:

            def _inspect_worker(cid: str) -> None:
                _fetch_container_inspect(cid, conn=None)

            list(_inspect_pool().map(_inspect_worker, cids_to_inspect))

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

            # Stack & Origin classification
            stack, service, managed_by = _classify_stack(labels)

            # Inspect data for hardware badges, networking & exposed ports (fast cached query)
            inspect_info = _fetch_container_inspect(cid_short, conn=conn)
            devices = inspect_info.get("HostConfig", {}).get("Devices", []) or []
            env = inspect_info.get("Config", {}).get("Env", []) or []
            runtime = inspect_info.get("HostConfig", {}).get("Runtime", "")
            net_mode = c.get("HostConfig", {}).get("NetworkMode") or inspect_info.get("HostConfig", {}).get(
                "NetworkMode", ""
            )
            exposed_ports = inspect_info.get("Config", {}).get("ExposedPorts") or {}

            # Ports & Universal WebUI resolution (supports bridge NAT and host-mode exposed ports)
            ports, primary_port, webui_url = _parse_ports_and_webui(
                raw_ports, labels, network_mode=net_mode, exposed_ports=exposed_ports
            )

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
                    "zettnas_app": labels.get("com.zettnas.managed") == "1",  # installed by ZettNAS (REL-10)
                    "network_mode": net_mode,
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
                logger.debug("backend.hardware.docker_stats.read_docker_containers: ignored error", exc_info=True)


def container_action(container_id: str, action: str) -> dict[str, Any]:
    global _CACHED_CONTAINERS, _LAST_DOCKER_POLL
    # Sanitize container_id or name: alphanumeric, underscore, hyphen, dot, 1-128 chars
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        return {"success": False, "error": "Invalid container ID"}

    action = action.lower().strip()
    if action not in ("start", "stop", "restart", "pause", "unpause"):
        return {"success": False, "error": f"Unsupported action: {action}"}

    sock_path = docker_sock()
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
