"""
ZettNAS Toolkit - Docker Stacks Manager & Setup Editor Subsystem
Provides stack discovery, inspection, live multi-service compose synthesis,
in-place compose.yaml and .env modification, and stack orchestration actions.
Hardware & OS agnostic.
"""

import io
import json
import os
import re
import tarfile
import time
from typing import Any, Dict, List, Optional, Tuple

import yaml

from backend.config import logger
from backend.hardware.docker_stats import (
    UnixHTTPConnection,
    _classify_stack,
    _parse_ports_and_webui,
)
from backend.services.compose_synthesizer import (
    execute_in_container,
    fetch_container_raw_inspect,
    synthesize_compose_spec,
)

DOCKER_SOCK = "/var/run/docker.sock"


def _docker_request(method: str, path: str, body: Optional[bytes] = None, timeout: float = 6.0) -> Tuple[int, bytes]:
    """Helper to query Docker Unix socket."""
    if not os.path.exists(DOCKER_SOCK):
        return 503, b'{"error": "Docker socket unavailable"}'
    conn = None
    try:
        conn = UnixHTTPConnection(DOCKER_SOCK, timeout=timeout)
        headers = {}
        if body:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse()
        data = res.read()
        return res.status, data
    except Exception as e:
        logger.debug(f"[DockerStacks] Request {method} {path} error: {e}")
        return 500, str(e).encode()
    finally:
        if conn:
            conn.close()


def _read_file_from_container(cid: str, container_path: str) -> Optional[str]:
    """Reads a file from inside a container via the Docker socket archive API."""
    try:
        status, tar_bytes = _docker_request("GET", f"/containers/{cid}/archive?path={container_path}", timeout=6.0)
        if status != 200:
            return None
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
            for member in tar.getmembers():
                if member.isfile():
                    f = tar.extractfile(member)
                    if f:
                        return f.read().decode("utf-8", errors="replace")
        return None
    except Exception as e:
        logger.debug(f"[DockerStacks] Could not read {container_path} from {cid}: {e}")
        return None


def _write_file_to_container(cid: str, dir_path: str, filename: str, content: str) -> bool:
    """Writes a file inside a container via the Docker socket archive API."""
    try:
        tar_stream = io.BytesIO()
        raw_bytes = content.encode("utf-8")
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            tarinfo = tarfile.TarInfo(name=filename)
            tarinfo.size = len(raw_bytes)
            tarinfo.mtime = int(time.time())
            tarinfo.mode = 0o644
            tar.addfile(tarinfo, io.BytesIO(raw_bytes))
        tar_bytes = tar_stream.getvalue()

        conn = UnixHTTPConnection(DOCKER_SOCK, timeout=10.0)
        conn.request(
            "PUT",
            f"/containers/{cid}/archive?path={dir_path}",
            body=tar_bytes,
            headers={"Content-Type": "application/x-tar"},
        )
        res = conn.getresponse()
        status = res.status
        conn.close()
        return status in (200, 201)
    except Exception as e:
        logger.warning(f"[DockerStacks] Could not write {filename} to {cid}:{dir_path}: {e}")
        return False


def list_all_stacks() -> List[Dict[str, Any]]:
    """
    Discovers and groups all containers by their Compose / Orchestrator stack.
    """
    status, data = _docker_request("GET", "/containers/json?all=1")
    if status != 200:
        return []

    try:
        containers = json.loads(data.decode("utf-8"))
    except Exception:
        return []

    stacks_map: Dict[str, Dict[str, Any]] = {}

    for c in containers:
        labels = c.get("Labels", {})
        stack, service, managed_by = _classify_stack(labels)

        if not stack:
            # Standalone container without stack
            continue

        cid = c.get("Id", "")[:12]
        cname = (c.get("Names") or [""])[0].lstrip("/")
        state = c.get("State", "").lower()
        image = c.get("Image", "")
        ports_list = c.get("Ports", [])
        parsed_ports, _, webui_url = _parse_ports_and_webui(ports_list, labels)

        working_dir = labels.get("com.docker.compose.project.working_dir", "")
        config_files = labels.get("com.docker.compose.project.config_files", "")
        environment_file = labels.get("com.docker.compose.project.environment_file", "")

        if stack not in stacks_map:
            stacks_map[stack] = {
                "name": stack,
                "origin": managed_by,
                "working_dir": working_dir,
                "config_files": config_files,
                "environment_file": environment_file,
                "services": [],
                "containers": [],
                "total_count": 0,
                "running_count": 0,
            }

        # Keep the most specific config file/dir if found
        if not stacks_map[stack]["working_dir"] and working_dir:
            stacks_map[stack]["working_dir"] = working_dir
        if not stacks_map[stack]["config_files"] and config_files:
            stacks_map[stack]["config_files"] = config_files
        if not stacks_map[stack]["environment_file"] and environment_file:
            stacks_map[stack]["environment_file"] = environment_file

        stacks_map[stack]["total_count"] += 1
        if state == "running":
            stacks_map[stack]["running_count"] += 1

        service_entry = service or cname
        if service_entry not in stacks_map[stack]["services"]:
            stacks_map[stack]["services"].append(service_entry)

        stacks_map[stack]["containers"].append(
            {
                "id": cid,
                "name": cname,
                "service": service_entry,
                "state": state,
                "status": c.get("Status", ""),
                "image": image,
                "ports": parsed_ports,
                "webui_url": webui_url,
            }
        )

    # Finalize status string
    results = []
    for s in stacks_map.values():
        if s["running_count"] == s["total_count"] and s["total_count"] > 0:
            s["status"] = "running"
        elif s["running_count"] == 0:
            s["status"] = "stopped"
        else:
            s["status"] = "partial"
        results.append(s)

    results.sort(key=lambda x: x["name"].lower())
    return results


def get_stack_details(stack_name: str) -> Dict[str, Any]:
    """
    Returns full details for a stack:
    - Containers list with inspect data
    - Real or synthesized compose.yaml content
    - Real or extracted .env content
    - Working directory & config paths
    """
    stacks = list_all_stacks()
    target_stack = next((s for s in stacks if s["name"] == stack_name), None)

    containers_in_stack = target_stack["containers"] if target_stack else []
    working_dir = target_stack.get("working_dir", "") if target_stack else ""
    config_file = target_stack.get("config_files", "") if target_stack else ""
    env_file = target_stack.get("environment_file", "") if target_stack else ""
    origin = target_stack.get("origin", "compose") if target_stack else "compose"

    compose_yaml = None
    env_content = None
    has_real_file = False
    resolved_location_type = "synthesized"  # "host_fs", "dockhand", "synthesized"

    # 1. Attempt reading from host filesystem (e.g. /mnt/user/... or local path)
    if config_file and os.path.isfile(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                compose_yaml = f.read()
            has_real_file = True
            resolved_location_type = "host_fs"
        except Exception as e:
            logger.debug(f"[DockerStacks] Cannot read host config_file {config_file}: {e}")

    if not compose_yaml and working_dir and os.path.isdir(working_dir):
        for candidate in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
            cand_path = os.path.join(working_dir, candidate)
            if os.path.isfile(cand_path):
                try:
                    with open(cand_path, "r", encoding="utf-8") as f:
                        compose_yaml = f.read()
                    config_file = cand_path
                    has_real_file = True
                    resolved_location_type = "host_fs"
                    break
                except Exception:
                    pass

    # Read .env on host filesystem if found
    if resolved_location_type == "host_fs":
        cand_env = env_file if (env_file and os.path.isfile(env_file)) else os.path.join(working_dir, ".env")
        if os.path.isfile(cand_env):
            try:
                with open(cand_env, "r", encoding="utf-8") as f:
                    env_content = f.read()
            except Exception:
                pass

    # 2. Attempt reading from dockhand container volume if dockhand is running
    if not compose_yaml and config_file.startswith("/app/data/"):
        compose_yaml = _read_file_from_container("dockhand", config_file)
        if compose_yaml:
            has_real_file = True
            resolved_location_type = "dockhand"
            if env_file:
                env_content = _read_file_from_container("dockhand", env_file)
            elif working_dir:
                env_content = _read_file_from_container("dockhand", f"{working_dir.rstrip('/')}/.env")

    # 3. Fallback: synthesize multi-service Compose YAML from live containers
    if not compose_yaml:
        synthesized_services = {}
        accumulated_env = {}

        for c_summary in containers_in_stack:
            inspect_data = fetch_container_raw_inspect(c_summary["id"])
            if not inspect_data:
                continue

            svc_name, svc_spec = synthesize_compose_spec(inspect_data, mask_secrets=False)
            # Normalize service key
            service_label = c_summary.get("service") or svc_name
            clean_svc = re.sub(r"[^a-zA-Z0-9_\-]", "_", service_label)
            synthesized_services[clean_svc] = svc_spec

            # Collect env variables
            env_list = inspect_data.get("Config", {}).get("Env", [])
            for item in env_list:
                if "=" in item:
                    k, v = item.split("=", 1)
                    if not k.startswith("PATH") and not k.startswith("HOSTNAME"):
                        accumulated_env[k] = v

        full_compose_dict = {
            "version": "3.8",
            "services": synthesized_services,
        }
        try:
            compose_yaml = yaml.dump(full_compose_dict, sort_keys=False, default_flow_style=False)
        except Exception:
            compose_yaml = json.dumps(full_compose_dict, indent=2)

        if not env_content and accumulated_env:
            env_content = "\n".join(f"{k}={v}" for k, v in accumulated_env.items())

    return {
        "name": stack_name,
        "origin": origin,
        "working_dir": working_dir,
        "config_file": config_file,
        "has_real_file": has_real_file,
        "location_type": resolved_location_type,
        "compose_yaml": compose_yaml or "",
        "env_content": env_content or "",
        "containers": containers_in_stack,
        "total_count": len(containers_in_stack),
        "running_count": sum(1 for c in containers_in_stack if c.get("state") == "running"),
        "status": target_stack.get("status", "unknown") if target_stack else "unknown",
    }


def save_stack_config(stack_name: str, compose_yaml: str, env_content: Optional[str] = None) -> Dict[str, Any]:
    """
    Validates and saves updated compose.yaml and .env for a stack.
    """
    if not compose_yaml or not compose_yaml.strip():
        return {"success": False, "error": "Compose YAML cannot be empty"}

    # 1. Validate YAML syntax
    try:
        yaml.safe_load(compose_yaml)
    except Exception as e:
        return {"success": False, "error": f"Invalid YAML syntax: {e}"}

    details = get_stack_details(stack_name)
    location_type = details.get("location_type")
    config_file = details.get("config_file")
    working_dir = details.get("working_dir")

    # A. Host filesystem
    if location_type == "host_fs" and config_file:
        try:
            # Backup
            bak_path = f"{config_file}.bak.{int(time.time())}"
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as orig:
                    with open(bak_path, "w", encoding="utf-8") as bak:
                        bak.write(orig.read())

            with open(config_file, "w", encoding="utf-8") as f:
                f.write(compose_yaml)

            if env_content is not None and working_dir:
                env_path = os.path.join(working_dir, ".env")
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(env_content)

            return {"success": True, "message": "Stack configuration saved to host filesystem"}
        except Exception as e:
            return {"success": False, "error": f"Failed writing to host filesystem: {e}"}

    # B. Dockhand volume
    if location_type == "dockhand" and config_file and working_dir:
        filename = os.path.basename(config_file)
        ok = _write_file_to_container("dockhand", working_dir, filename, compose_yaml)
        if not ok:
            return {"success": False, "error": "Failed writing compose file into Dockhand volume"}

        if env_content is not None:
            _write_file_to_container("dockhand", working_dir, ".env", env_content)

        return {"success": True, "message": "Stack configuration saved into Dockhand volume"}

    # C. Synthesized / new stack on host
    default_dir = f"/mnt/user/appdata/{stack_name}"
    try:
        os.makedirs(default_dir, exist_ok=True)
        target_file = os.path.join(default_dir, "docker-compose.yml")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(compose_yaml)
        if env_content is not None:
            with open(os.path.join(default_dir, ".env"), "w", encoding="utf-8") as f:
                f.write(env_content)
        return {"success": True, "message": f"Stack configuration saved to {target_file}"}
    except Exception as e:
        return {"success": False, "error": f"Failed creating stack directory: {e}"}


def execute_stack_action(stack_name: str, action: str) -> Dict[str, Any]:
    """
    Executes an action across an entire stack:
    - restart: Restarts all containers in the stack
    - stop: Stops all containers in the stack
    - start: Starts all containers in the stack
    - redeploy: Runs docker compose up -d (via dockhand or host)
    """
    details = get_stack_details(stack_name)
    containers = details.get("containers", [])
    location_type = details.get("location_type")
    working_dir = details.get("working_dir")

    if not containers and action != "redeploy":
        return {"success": False, "error": f"No containers found for stack '{stack_name}'"}

    if action == "redeploy":
        if location_type == "dockhand" and working_dir:
            cmd = f"cd {working_dir} && docker compose up -d"
            res = execute_in_container("dockhand", cmd)
            return {
                "success": res.get("success", False),
                "action": "redeploy",
                "output": res.get("output", res.get("error", "")),
            }
        else:
            # Fallback: sequential restart of all containers
            restarted = []
            for c in containers:
                cid = c["id"]
                st, _ = _docker_request("POST", f"/containers/{cid}/restart?t=10")
                if st in (204, 200):
                    restarted.append(c["name"])
            return {
                "success": len(restarted) > 0,
                "action": "redeploy",
                "output": f"Re-started {len(restarted)} services: {', '.join(restarted)}",
            }

    results = []
    for c in containers:
        cid = c["id"]
        if action == "restart":
            st, _ = _docker_request("POST", f"/containers/{cid}/restart?t=10")
        elif action == "stop":
            st, _ = _docker_request("POST", f"/containers/{cid}/stop?t=10")
        elif action == "start":
            st, _ = _docker_request("POST", f"/containers/{cid}/start")
        else:
            return {"success": False, "error": f"Unsupported stack action '{action}'"}

        results.append(
            {
                "id": cid,
                "name": c["name"],
                "success": st in (204, 200, 304),
            }
        )

    all_ok = all(r["success"] for r in results)
    return {
        "success": all_ok,
        "action": action,
        "details": results,
    }
