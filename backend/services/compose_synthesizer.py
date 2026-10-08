"""
ZettNAS Toolkit - Docker Compose Synthesizer & Container Inspector Subsystem
Reverse-engineers live container configurations into standard OCI Compose Specification (v3.8+).
Decodes multiplexed Docker log frames and extracts rich container telemetry.
Hardware & OS agnostic.
"""

import json
import os
import re
import struct
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.config import logger
from backend.hardware.docker_stats import (
    UnixHTTPConnection,
    _extract_hardware_badges,
    _parse_ports_and_webui,
    _classify_stack,
)

SECRET_KEY_PATTERNS = ["PASS", "SECRET", "TOKEN", "KEY", "AUTH", "CREDENTIAL", "PRIVATE"]


def is_secret_key(key: str) -> bool:
    """Checks whether an environment variable key name indicates sensitive data."""
    upper = (key or "").upper()
    return any(p in upper for p in SECRET_KEY_PATTERNS)


def mask_secret_value(val: str) -> str:
    """Masks secret values with asterisks."""
    if not val:
        return ""
    if len(val) <= 4:
        return "••••••••"
    return "••••••••"


def fetch_container_raw_inspect(cid_or_name: str) -> Dict[str, Any]:
    """Fetches full inspect JSON from local Docker socket."""
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return {}

    try:
        conn = UnixHTTPConnection(sock_path, timeout=4.0)
        conn.request("GET", f"/containers/{cid_or_name}/json")
        res = conn.getresponse()
        if res.status != 200:
            return {}
        data = json.loads(res.read().decode("utf-8", errors="replace"))
        conn.close()
        return data
    except Exception as e:
        logger.debug(f"[Docker] Inspect error for {cid_or_name}: {e}")
        return {}


def synthesize_compose_spec(inspect_data: Dict[str, Any], mask_secrets: bool = False) -> Tuple[str, Dict[str, Any]]:
    """
    Reconstructs standard OCI Compose Spec v3.8+ dictionary from container inspect data.
    """
    if not inspect_data:
        return "unnamed", {}

    raw_name = inspect_data.get("Name", "").lstrip("/") or "service"
    service_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw_name)

    config = inspect_data.get("Config", {})
    host_config = inspect_data.get("HostConfig", {})

    image = config.get("Image", "")
    restart_policy = host_config.get("RestartPolicy", {}).get("Name", "")
    restart = restart_policy if restart_policy in ("always", "unless-stopped", "on-failure") else "unless-stopped"

    # Ports
    ports = []
    port_bindings = host_config.get("PortBindings") or {}
    for cont_port, bindings in port_bindings.items():
        if bindings:
            for b in bindings:
                hp = b.get("HostPort")
                hip = b.get("HostIp")
                if hp:
                    if hip and hip not in ("0.0.0.0", "::", ""):
                        ports.append(f"{hip}:{hp}:{cont_port}")
                    else:
                        ports.append(f"{hp}:{cont_port}")
        else:
            ports.append(cont_port)

    # Volumes & Mounts
    volumes = []
    mounts = inspect_data.get("Mounts", []) or []
    for m in mounts:
        m_type = m.get("Type", "bind")
        src = m.get("Source", "")
        dst = m.get("Destination", "")
        mode = m.get("Mode", "")
        rw = m.get("RW", True)
        if src and dst:
            if not mode:
                mode = "rw" if rw else "ro"
            # Avoid internal container mounts and host devices in volumes
            if (
                src.startswith("/dev/")
                or dst in ("/etc/resolv.conf", "/etc/hostname", "/etc/hosts", "/dev/shm")
                or "/docker/containers/" in src
            ):
                continue
            volumes.append(f"{src}:{dst}:{mode}")

    # Host Devices
    devices = []
    for d in host_config.get("Devices") or []:
        p_host = d.get("PathOnHost")
        p_cont = d.get("PathInContainer")
        if p_host:
            devices.append(f"{p_host}:{p_cont or p_host}")
    # Also check if /dev/dri was mounted as volume
    for m in mounts:
        src = m.get("Source", "")
        if src.startswith("/dev/"):
            dst = m.get("Destination", src)
            dev_entry = f"{src}:{dst}"
            if dev_entry not in devices:
                devices.append(dev_entry)

    # Environment
    env_list = []
    for env_str in config.get("Env", []) or []:
        if "=" in env_str:
            k, v = env_str.split("=", 1)
        else:
            k, v = env_str, ""
        # Filter standard internal container envs
        if k in ("PATH", "HOSTNAME", "HOME"):
            continue
        if mask_secrets and is_secret_key(k):
            env_list.append(f"{k}={mask_secret_value(v)}")
        else:
            env_list.append(f"{k}={v}")

    # Network Mode
    net_mode = host_config.get("NetworkMode", "bridge")
    network_setting = None
    if net_mode and net_mode not in ("bridge", "default"):
        if net_mode == "host":
            network_setting = "host"

    # Assemble service spec
    spec: Dict[str, Any] = {
        "image": image,
        "container_name": raw_name,
        "restart": restart,
    }
    if network_setting:
        spec["network_mode"] = network_setting
    if ports and network_setting != "host":
        spec["ports"] = sorted(ports)
    if env_list:
        spec["environment"] = env_list
    if volumes:
        spec["volumes"] = sorted(volumes)
    if devices:
        spec["devices"] = sorted(devices)

    cap_add = host_config.get("CapAdd")
    if cap_add:
        spec["cap_add"] = cap_add

    privileged = host_config.get("Privileged", False)
    if privileged:
        spec["privileged"] = True

    return service_name, spec


def format_compose_yaml(service_name: str, spec: Dict[str, Any]) -> str:
    """
    Renders clean, indented YAML string adhering to Compose Spec v3.8.
    """
    lines = [
        "# Generated by ZettNAS Toolkit Compose Synthesizer",
        f"# Container: {service_name}",
        "# OCI Compose Specification v3.8+",
        'version: "3.8"',
        "",
        "services:",
        f"  {service_name}:",
    ]

    for key, val in spec.items():
        if isinstance(val, str):
            lines.append(f'    {key}: "{val}"' if any(c in val for c in ":#") else f"    {key}: {val}")
        elif isinstance(val, bool):
            lines.append(f"    {key}: {'true' if val else 'false'}")
        elif isinstance(val, list):
            lines.append(f"    {key}:")
            for item in val:
                # Wrap item in quotes if it contains colons or special chars
                clean_item = str(item)
                if any(c in clean_item for c in ":= #"):
                    clean_item = f'"{clean_item}"'
                lines.append(f"      - {clean_item}")
        elif isinstance(val, dict):
            lines.append(f"    {key}:")
            for dk, dv in val.items():
                lines.append(f"      {dk}: {dv}")

    lines.append("")
    return "\n".join(lines)


def get_container_compose_data(cid_or_name: str) -> Dict[str, Any]:
    """
    Returns Compose definition for a container, including both unmasked and masked YAML.
    """
    inspect_data = fetch_container_raw_inspect(cid_or_name)
    if not inspect_data:
        return {"error": "Container not found or Docker socket unavailable"}

    raw_name = inspect_data.get("Name", "").lstrip("/") or cid_or_name
    labels = inspect_data.get("Config", {}).get("Labels", {}) or {}

    # Check for original compose file on disk
    compose_path = labels.get("com.docker.compose.project.config_files")
    disk_content = None
    source = "synthesized"

    if compose_path and os.path.exists(compose_path) and os.path.isfile(compose_path):
        try:
            with open(compose_path, "r", encoding="utf-8") as f:
                disk_content = f.read()
            source = "disk"
        except Exception:
            disk_content = None

    # Synthesize specs
    srv_name, raw_spec = synthesize_compose_spec(inspect_data, mask_secrets=False)
    _, masked_spec = synthesize_compose_spec(inspect_data, mask_secrets=True)

    raw_yaml = disk_content if (source == "disk" and disk_content) else format_compose_yaml(srv_name, raw_spec)
    masked_yaml = format_compose_yaml(srv_name, masked_spec)

    return {
        "container_id": inspect_data.get("Id", "")[:12],
        "name": raw_name,
        "source": source,
        "compose_file_path": compose_path if source == "disk" else None,
        "compose_yaml": raw_yaml,
        "masked_yaml": masked_yaml,
        "service_spec": raw_spec,
    }


def get_container_full_details(cid_or_name: str) -> Dict[str, Any]:
    """
    Returns rich, structured inspector data for all tabs in the Container Inspector Modal.
    """
    inspect_data = fetch_container_raw_inspect(cid_or_name)
    if not inspect_data:
        return {"error": "Container not found"}

    cfg = inspect_data.get("Config", {})
    hc = inspect_data.get("HostConfig", {})
    st = inspect_data.get("State", {})
    net = inspect_data.get("NetworkSettings", {})
    labels = cfg.get("Labels", {}) or {}
    mounts = inspect_data.get("Mounts", []) or []

    raw_name = inspect_data.get("Name", "").lstrip("/")
    cid_short = inspect_data.get("Id", "")[:12]

    # Environment variables parsed & classified
    envs = []
    for item in cfg.get("Env", []) or []:
        if "=" in item:
            k, v = item.split("=", 1)
        else:
            k, v = item, ""
        is_sec = is_secret_key(k)
        envs.append(
            {
                "key": k,
                "value": v,
                "masked_value": mask_secret_value(v) if is_sec else v,
                "is_secret": is_sec,
            }
        )
    envs.sort(key=lambda x: x["key"].lower())

    # Mounts parsed
    parsed_mounts = []
    for m in mounts:
        src = m.get("Source", "")
        dst = m.get("Destination", "")
        mode = m.get("Mode", "")
        rw = m.get("RW", True)
        is_appdata = "appdata" in src.lower() or dst in ("/config", "/data", "/app/data")
        parsed_mounts.append(
            {
                "source": src,
                "destination": dst,
                "mode": mode or ("rw" if rw else "ro"),
                "rw": rw,
                "type": m.get("Type", "bind"),
                "is_appdata": is_appdata,
            }
        )

    # Ports
    raw_ports = []
    for cont_p, bindings in (hc.get("PortBindings") or {}).items():
        if bindings:
            for b in bindings:
                raw_ports.append(
                    {
                        "PrivatePort": int(cont_p.split("/")[0]) if cont_p.split("/")[0].isdigit() else 0,
                        "PublicPort": int(b.get("HostPort", 0)) if str(b.get("HostPort")).isdigit() else 0,
                        "Type": cont_p.split("/")[1] if "/" in cont_p else "tcp",
                        "IP": b.get("HostIp", "0.0.0.0"),
                    }
                )
        else:
            raw_ports.append(
                {
                    "PrivatePort": int(cont_p.split("/")[0]) if cont_p.split("/")[0].isdigit() else 0,
                    "PublicPort": None,
                    "Type": cont_p.split("/")[1] if "/" in cont_p else "tcp",
                    "IP": "0.0.0.0",
                }
            )
    ports, primary_port, webui_url = _parse_ports_and_webui(raw_ports, labels)

    # Stack origin
    stack, service, managed_by = _classify_stack(labels)

    # Hardware badges
    devices = hc.get("Devices", []) or []
    env_keys = cfg.get("Env", []) or []
    runtime = hc.get("Runtime", "")
    badges = _extract_hardware_badges(mounts, devices, env_keys, runtime=runtime)

    # Network IP
    ip_addr = net.get("IPAddress", "")
    gateway = net.get("Gateway", "")
    mac_addr = net.get("MacAddress", "")
    networks_map = net.get("Networks", {})
    if not ip_addr and networks_map:
        first_net = next(iter(networks_map.values()), {})
        ip_addr = first_net.get("IPAddress", "")
        gateway = first_net.get("Gateway", "")
        mac_addr = first_net.get("MacAddress", "")

    return {
        "overview": {
            "name": raw_name,
            "id": cid_short,
            "full_id": inspect_data.get("Id", ""),
            "image": cfg.get("Image", ""),
            "state": st.get("Status", "unknown"),
            "running": st.get("Running", False),
            "paused": st.get("Paused", False),
            "restarting": st.get("Restarting", False),
            "pid": st.get("Pid", 0),
            "started_at": st.get("StartedAt", ""),
            "finished_at": st.get("FinishedAt", ""),
            "platform": inspect_data.get("Platform", "linux"),
            "restart_policy": hc.get("RestartPolicy", {}).get("Name", "no"),
            "ip_address": ip_addr or "Host Network",
            "gateway": gateway,
            "mac_address": mac_addr,
            "network_mode": hc.get("NetworkMode", "bridge"),
            "command": " ".join(cfg.get("Entrypoint") or []) + " " + " ".join(cfg.get("Cmd") or []),
        },
        "resources": {
            "nano_cpus": hc.get("NanoCPUs", 0),
            "cpu_shares": hc.get("CpuShares", 0),
            "memory_limit": hc.get("Memory", 0),
            "memory_reservation": hc.get("MemoryReservation", 0),
        },
        "stack": stack,
        "service": service,
        "managed_by": managed_by,
        "ports": ports,
        "primary_port": primary_port,
        "webui_url": webui_url,
        "hardware_badges": badges,
        "mounts": parsed_mounts,
        "env": envs,
    }


def get_container_logs_chunk(cid_or_name: str, tail: int = 200) -> Dict[str, Any]:
    """
    Reads multiplexed Docker stdout/stderr logs from the Unix socket,
    decoding the 8-byte framing into clean timestamps and messages.
    """
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return {"lines": [], "error": "Docker socket not available"}

    tail_param = max(10, min(2000, int(tail)))

    conn = None
    try:
        conn = UnixHTTPConnection(sock_path, timeout=5.0)
        conn.request("GET", f"/containers/{cid_or_name}/logs?stdout=1&stderr=1&tail={tail_param}&timestamps=1")
        res = conn.getresponse()
        raw = res.read()

        lines = []
        idx = 0
        raw_len = len(raw)

        # Docker 8-byte multiplex protocol: [1 byte stream][3 bytes pad][4 bytes payload length]
        while idx + 8 <= raw_len:
            stream_type = raw[idx]
            if stream_type not in (1, 2, 0):
                # Non-standard or non-multiplexed frame detected; break to raw line fallback
                break
            payload_len = struct.unpack(">I", raw[idx + 4 : idx + 8])[0]
            if idx + 8 + payload_len > raw_len:
                break
            payload = raw[idx + 8 : idx + 8 + payload_len].decode("utf-8", errors="replace")
            idx += 8 + payload_len

            st_label = "stdout" if stream_type == 1 else ("stderr" if stream_type == 2 else "stdin")
            clean_line = payload.strip("\r\n")
            if not clean_line:
                continue

            # Parse RFC3339 timestamp prefix if present (e.g. 2026-10-08T17:26:21.376179397Z)
            ts = ""
            msg = clean_line
            if len(clean_line) > 30 and clean_line[4] == "-" and clean_line[10] == "T" and " " in clean_line[:35]:
                parts = clean_line.split(" ", 1)
                ts = parts[0]
                msg = parts[1] if len(parts) > 1 else ""

            lines.append(
                {
                    "stream": st_label,
                    "ts": ts,
                    "msg": msg,
                }
            )

        # Fallback for containers with Tty: true (no 8-byte multiplex header)
        if not lines and raw:
            text = raw.decode("utf-8", errors="replace")
            for raw_line in text.splitlines():
                clean_line = raw_line.strip("\r\n")
                if not clean_line:
                    continue
                ts = ""
                msg = clean_line
                if len(clean_line) > 30 and clean_line[4] == "-" and clean_line[10] == "T" and " " in clean_line[:35]:
                    parts = clean_line.split(" ", 1)
                    ts = parts[0]
                    msg = parts[1] if len(parts) > 1 else ""
                lines.append(
                    {
                        "stream": "stdout",
                        "ts": ts,
                        "msg": msg,
                    }
                )

        return {
            "container": cid_or_name,
            "lines": lines,
            "count": len(lines),
            "tail": tail_param,
        }
    except Exception as e:
        logger.error(f"[Docker] Failed to read logs for {cid_or_name}: {e}")
        return {"lines": [], "error": str(e)}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def execute_in_container(cid_or_name: str, cmd: Any) -> Dict[str, Any]:
    """
    Executes a command inside the target container via Docker Engine socket.
    Returns exit code and stdout/stderr output.
    """
    sock_path = "/var/run/docker.sock"
    if not os.path.exists(sock_path):
        return {"success": False, "error": "Docker socket not available"}

    if isinstance(cmd, str):
        cmd_list = ["/bin/sh", "-c", cmd]
    elif isinstance(cmd, list):
        cmd_list = cmd
    else:
        cmd_list = ["/bin/sh", "-c", "echo ready"]

    conn = None
    try:
        conn = UnixHTTPConnection(sock_path, timeout=10.0)
        # 1. Create exec instance
        create_payload = json.dumps(
            {
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": False,
                "Cmd": cmd_list,
            }
        )
        conn.request(
            "POST",
            f"/containers/{cid_or_name}/exec",
            body=create_payload,
            headers={"Content-Type": "application/json"},
        )
        create_res = conn.getresponse()
        if create_res.status not in (200, 201):
            return {"success": False, "error": f"Failed to create exec instance: status {create_res.status}"}

        exec_info = json.loads(create_res.read().decode("utf-8"))
        exec_id = exec_info.get("Id")
        if not exec_id:
            return {"success": False, "error": "No Exec ID returned by Docker daemon"}

        # 2. Start exec instance
        start_payload = json.dumps({"Detach": False, "Tty": False})
        conn.request(
            "POST",
            f"/exec/{exec_id}/start",
            body=start_payload,
            headers={"Content-Type": "application/json"},
        )
        start_res = conn.getresponse()
        raw_output = start_res.read()

        # Parse Docker multiplexed output or raw string
        clean_lines = []
        idx = 0
        raw_len = len(raw_output)
        while idx + 8 <= raw_len:
            stream_type = raw_output[idx]
            if stream_type not in (1, 2, 0):
                break
            payload_len = struct.unpack(">I", raw_output[idx + 4 : idx + 8])[0]
            if idx + 8 + payload_len > raw_len:
                break
            payload = raw_output[idx + 8 : idx + 8 + payload_len].decode("utf-8", errors="replace")
            idx += 8 + payload_len
            clean_lines.append(payload)

        output_str = "".join(clean_lines) if clean_lines else raw_output.decode("utf-8", errors="replace")

        return {
            "success": True,
            "exec_id": exec_id,
            "output": output_str.strip(),
            "cmd": cmd_list,
        }
    except Exception as e:
        logger.error(f"[Docker] Failed to execute in {cid_or_name}: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

