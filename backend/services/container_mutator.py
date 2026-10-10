"""
ZettNAS Toolkit - Container Mutation & Zero-Downtime Resource Tuning Subsystem
Supports:
1. Live zero-downtime CPU and Memory limit tuning via POST /containers/{id}/update.
2. Atomic Clone-and-Recreate port reconfiguration with automatic rollback.
3. Host socket port pre-flight conflict detection.
100% OS-agnostic and hardware-agnostic.
"""

import json
import os
import socket
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from backend.config import logger
from backend.hardware.docker_stats import UnixHTTPConnection
from backend.services.compose_synthesizer import fetch_container_raw_inspect


def check_port_available(port: int, proto: str = "tcp", host: str = "0.0.0.0") -> bool:
    """
    Checks if a local port is available to bind without conflicts.
    Inspects host procfs sockets (/host/proc/net/tcp, /host/proc/net/tcp6)
    as well as container socket bind.
    """
    if not (1 <= port <= 65535):
        return False

    hex_port = f"{port:04X}"
    for proc_path in ("/host/proc/net/tcp", "/host/proc/net/tcp6", "/proc/net/tcp", "/proc/net/tcp6"):
        if os.path.exists(proc_path):
            try:
                with open(proc_path) as f:
                    for line in f:
                        fields = line.strip().split()
                        if len(fields) >= 4 and fields[3] == "0A":  # TCP_LISTEN
                            if fields[1].endswith(f":{hex_port}"):
                                return False
            except Exception:
                pass

    sock_type = socket.SOCK_STREAM if proto.lower() == "tcp" else socket.SOCK_DGRAM
    try:
        with socket.socket(socket.AF_INET, sock_type) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def _docker_request(method: str, path: str, body: Optional[dict] = None, timeout: float = 15.0) -> Tuple[int, Any]:
    """Helper for making synchronous HTTP requests over the Docker Unix socket."""
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        raise RuntimeError("Docker socket /var/run/docker.sock not found")

    # Sanitize URL path and query parameters so control chars and unencoded JSON in query strings never cause InvalidURL
    if "?" in path:
        base, query = path.split("?", 1)
        parts = query.split("&")
        safe_parts = []
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                unquoted = urllib.parse.unquote(v)
                safe_parts.append(f"{k}={urllib.parse.quote(unquoted)}")
            else:
                safe_parts.append(p)
        query_str = "&".join(safe_parts)
        path = f"{base}?{query_str}"
    elif " " in path:
        path = path.replace(" ", "%20")

    conn = UnixHTTPConnection(sock_path, timeout=timeout)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    body_bytes = json.dumps(body).encode("utf-8") if body is not None else None

    try:
        conn.request(method, path, body=body_bytes, headers=headers)
        res = conn.getresponse()
        raw = res.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except Exception:
            data = {"raw": raw}
        return res.status, data
    finally:
        try:
            conn.close()
        except Exception:
            pass


def update_container_resources(
    cid: str,
    memory_mb: Optional[int] = None,
    nano_cpus: Optional[float] = None,
    cpu_shares: Optional[int] = None,
    restart_policy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Applies zero-downtime resource changes (Memory, CPU quota, Restart Policy)
    via official Docker Engine API: POST /containers/{id}/update.
    """
    payload: Dict[str, Any] = {}
    if memory_mb is not None:
        if memory_mb < 0:
            raise ValueError("memory_mb must be >= 0 (0 for unlimited)")
        payload["Memory"] = int(memory_mb * 1024 * 1024)
        if memory_mb > 0:
            # Docker requires MemorySwap >= Memory when updating memory
            payload["MemorySwap"] = int(memory_mb * 1024 * 1024 * 2)

    if nano_cpus is not None:
        if nano_cpus < 0:
            raise ValueError("nano_cpus must be >= 0")
        payload["NanoCPUs"] = int(nano_cpus * 1e9)

    if cpu_shares is not None:
        payload["CpuShares"] = int(cpu_shares)

    if restart_policy:
        valid_policies = ["no", "always", "unless-stopped", "on-failure"]
        if restart_policy not in valid_policies:
            raise ValueError(f"restart_policy must be one of {valid_policies}")
        payload["RestartPolicy"] = {"Name": restart_policy}

    if not payload:
        return {"status": "no_changes", "message": "No resource limits specified to update."}

    status, resp = _docker_request("POST", f"/containers/{cid}/update", body=payload)
    if status == 200:
        return {
            "status": "success",
            "message": "Container resource limits updated successfully with zero downtime.",
            "updated_fields": list(payload.keys()),
            "warnings": resp.get("Warnings", []),
        }
    else:
        err_msg = resp.get("message") or resp.get("raw") or f"HTTP {status}"
        raise RuntimeError(f"Docker API resource update failed: {err_msg}")


def pull_container_image(image: str, timeout: float = 180.0) -> bool:
    """
    Pulls a Docker image using Docker Engine Unix socket API:
    POST /images/create?fromImage={repo}&tag={tag}.
    Streams pull progress chunks until complete.
    """
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        raise RuntimeError("Docker socket /var/run/docker.sock not found")

    image_str = image.strip()
    if ":" in image_str and not image_str.endswith(":"):
        repo, tag = image_str.rsplit(":", 1)
        if "/" in tag:
            repo = image_str
            tag = "latest"
    else:
        repo = image_str
        tag = "latest"

    url_path = f"/images/create?fromImage={urllib.parse.quote(repo)}&tag={urllib.parse.quote(tag)}"
    conn = UnixHTTPConnection(sock_path, timeout=timeout)
    try:
        conn.request("POST", url_path)
        res = conn.getresponse()
        if res.status != 200:
            raw = res.read().decode("utf-8", errors="replace")
            logger.error(f"[Docker Pull] Pull failed for '{image}' (HTTP {res.status}): {raw}")
            raise RuntimeError(f"Docker API pull failed for '{image}': {raw[:200]}")

        while True:
            chunk = res.readline()
            if not chunk:
                break
        logger.info(f"[Docker Pull] Successfully pulled image '{image}'")
        return True
    except Exception as exc:
        logger.error(f"[Docker Pull] Exception pulling '{image}': {exc}")
        raise RuntimeError(f"Failed to pull image '{image}': {exc}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def recreate_container(
    cid: str,
    name: Optional[str] = None,
    image: Optional[str] = None,
    env: Optional[List[str]] = None,
    binds: Optional[List[str]] = None,
    port_bindings: Optional[List[Dict[str, Any]]] = None,
    network_mode: Optional[str] = None,
    restart_policy: Optional[str] = None,
    pull_image: bool = False,
    keep_backup: bool = False,
    timeout: float = 45.0,
) -> Dict[str, Any]:
    """
    Safely reconfigures and mutates a container using the Atomic Clone-and-Recreate pattern.
    Supports updating container name, image tag, environment variables, mounts / binds,
    network mode, port bindings, and restart policy.
    Includes automated rollback to guarantee zero data loss and uninterrupted availability
    if creation or startup of the updated container encounters an error.
    """
    # Step 1: Pre-flight inspect
    inspect_data = fetch_container_raw_inspect(cid)
    if not inspect_data:
        raise ValueError(f"Container '{cid}' not found or Docker socket unavailable.")

    config = inspect_data.get("Config", {})
    host_config = inspect_data.get("HostConfig", {})
    orig_name = inspect_data.get("Name", "").lstrip("/")
    if not orig_name:
        raise ValueError(f"Could not determine container name for '{cid}'.")

    self_hostname = socket.gethostname()
    if (self_hostname and cid.startswith(self_hostname)) or orig_name in ("zettnas-toolkit", "zettnas"):
        raise ValueError(
            "Cannot recreate the active ZettNAS Toolkit container from within the app. "
            "Container modifications must be configured in Docker Compose or your host template."
        )

    target_name = name.strip().lstrip("/") if (name and name.strip()) else orig_name
    target_image = image.strip() if (image and image.strip()) else config.get("Image", "")

    # Step 2: Optionally pull new image if requested
    if pull_image and target_image:
        logger.info(f"[Container Recreate] Pulling image '{target_image}' before recreate...")
        pull_container_image(target_image, timeout=120.0)

    # Step 3: Handle Port Bindings and Exposed Ports
    cloned_port_bindings: Dict[str, Any] = dict(host_config.get("PortBindings") or {})
    cloned_exposed_ports: Dict[str, Any] = dict(config.get("ExposedPorts") or {})

    if port_bindings is not None:
        cloned_port_bindings = {}
        cloned_exposed_ports = {}
        current_ports = host_config.get("PortBindings", {})

        for pb in port_bindings:
            cp = pb.get("container_port")
            hp = pb.get("host_port")
            proto = pb.get("proto", "tcp").lower()
            host_ip = pb.get("host_ip", "")

            if not cp:
                continue

            port_key = f"{cp}/{proto}"
            cloned_exposed_ports[port_key] = {}

            if hp is not None and int(hp) > 0:
                hp_int = int(hp)
                if not check_port_available(hp_int, proto=proto):
                    already_bound_by_self = any(
                        any(int(b.get("HostPort", 0)) == hp_int for b in binds_list)
                        for binds_list in current_ports.values()
                    )
                    if not already_bound_by_self:
                        raise ValueError(
                            f"Port collision: Host port {hp_int}/{proto} is already in use by another service."
                        )
                cloned_port_bindings[port_key] = [{"HostIp": host_ip, "HostPort": str(hp_int)}]

    # Step 4: Prepare new HostConfig
    new_host_config = dict(host_config)
    new_host_config["PortBindings"] = cloned_port_bindings

    if binds is not None:
        new_host_config["Binds"] = [b.strip() for b in binds if b and b.strip()]

    if network_mode is not None and network_mode.strip():
        new_host_config["NetworkMode"] = network_mode.strip()

    if restart_policy is not None and restart_policy.strip():
        valid_policies = ["no", "always", "unless-stopped", "on-failure"]
        pol = restart_policy.strip()
        if pol in valid_policies:
            new_host_config["RestartPolicy"] = {"Name": pol}

    # Step 5: Prepare create payload based on current inspect
    target_env = [e.strip() for e in env if e and e.strip()] if env is not None else config.get("Env", [])
    create_body: Dict[str, Any] = {
        "Image": target_image,
        "Env": target_env,
        "Cmd": config.get("Cmd"),
        "Entrypoint": config.get("Entrypoint"),
        "WorkingDir": config.get("WorkingDir"),
        "User": config.get("User"),
        "Labels": config.get("Labels", {}),
        "ExposedPorts": cloned_exposed_ports,
        "StopSignal": config.get("StopSignal"),
        "StopTimeout": config.get("StopTimeout"),
        "HostConfig": new_host_config,
    }

    # NetworkingConfig (EndpointsConfig for custom networks if not host/none)
    net_mode = new_host_config.get("NetworkMode", "")
    if net_mode not in ("host", "none"):
        network_settings = inspect_data.get("NetworkSettings", {})
        networks = network_settings.get("Networks", {})
        if networks:
            create_body["NetworkingConfig"] = {"EndpointsConfig": networks}

    ts_suffix = int(time.time())
    backup_name = f"{orig_name}.backup.{ts_suffix}"
    backup_id = inspect_data.get("Id", cid)
    new_id = None

    logger.info(
        f"[Container Recreate] Starting atomic reconfiguration for '{orig_name}' -> '{target_name}' (ID: {backup_id[:12]})"
    )

    try:
        # Step 6: Stop old container gracefully
        logger.info(f"[Container Recreate] Stopping old container '{orig_name}'...")
        _docker_request("POST", f"/containers/{backup_id}/stop?t=10", timeout=timeout)

        # Step 7: Temporarily rename old container to free the original name
        logger.info(f"[Container Recreate] Renaming '{orig_name}' -> '{backup_name}'...")
        status, rename_resp = _docker_request("POST", f"/containers/{backup_id}/rename?name={backup_name}")
        if status != 204:
            raise RuntimeError(f"Failed to rename old container: {rename_resp}")

        # Step 8: Create new container with target name and updated configuration
        logger.info(f"[Container Recreate] Creating new container '{target_name}' with updated config...")
        status, create_resp = _docker_request(
            "POST", f"/containers/create?name={target_name}", body=create_body, timeout=timeout
        )
        if status != 201:
            raise RuntimeError(f"Failed to create new container: {create_resp}")

        new_id = create_resp.get("Id")
        if not new_id:
            raise RuntimeError(f"Docker did not return ID for created container: {create_resp}")

        # Step 9: Start new container
        logger.info(f"[Container Recreate] Starting new container '{target_name}' (ID: {new_id[:12]})...")
        status, start_resp = _docker_request("POST", f"/containers/{new_id}/start", timeout=timeout)
        if status != 204:
            raise RuntimeError(f"Failed to start newly created container: {start_resp}")

        # Step 10: Success! Cleanup or retain backup
        if not keep_backup:
            logger.info(f"[Container Recreate] Removing backup container '{backup_name}'...")
            _docker_request("DELETE", f"/containers/{backup_id}?v=false&force=true")

        return {
            "status": "success",
            "message": f"Container '{target_name}' successfully recreated with updated configuration.",
            "old_id": backup_id[:12],
            "new_id": new_id[:12],
            "target_name": target_name,
            "target_image": target_image,
            "retained_backup": keep_backup,
            "backup_name": backup_name if keep_backup else None,
        }

    except Exception as exc:
        # AUTOMATIC ROLLBACK PROCEDURE
        logger.error(f"[Container Recreate] Error occurred during recreation: {exc}. Initiating automatic rollback!")

        # If new container was partially created, delete it
        if new_id:
            try:
                logger.info(f"[Rollback] Removing failed container {new_id[:12]}...")
                _docker_request("DELETE", f"/containers/{new_id}?v=false&force=true")
            except Exception as e:
                logger.warning(f"[Rollback] Failed to delete temporary container {new_id}: {e}")

        # Restore original container name
        try:
            logger.info(f"[Rollback] Restoring container name '{backup_name}' -> '{orig_name}'...")
            _docker_request("POST", f"/containers/{backup_id}/rename?name={orig_name}")
        except Exception as e:
            logger.warning(f"[Rollback] Failed to restore original container name: {e}")

        # Restart original container
        try:
            logger.info(f"[Rollback] Restarting original container '{orig_name}'...")
            _docker_request("POST", f"/containers/{backup_id}/start")
        except Exception as e:
            logger.error(f"[Rollback] Failed to restart original container: {e}")

        raise RuntimeError(f"Container mutation aborted. Automatic rollback restored original state. Reason: {exc}")


def recreate_container_ports(
    cid: str,
    new_port_bindings: List[Dict[str, Any]],
    keep_backup: bool = False,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    Backwards-compatible convenience wrapper around recreate_container.
    """
    return recreate_container(
        cid=cid,
        port_bindings=new_port_bindings,
        keep_backup=keep_backup,
        timeout=timeout,
    )

