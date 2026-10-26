"""Bringing Tailscale up and down, and deploying its container.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import re
import time
from typing import Any

from backend.config import logger
from backend.hardware.net import common, tailscale


def execute_tailscale_up(
    auth_key: str | None = None,
    hostname: str | None = None,
    accept_routes: bool = True,
) -> dict[str, Any]:
    """Connects host to the Zero-Trust Tailscale mesh network."""
    c_info = tailscale._get_tailscale_container_info()
    if c_info.get("exists") and not c_info.get("running"):
        try:
            from backend.services.container_mutator import _docker_request

            _docker_request("POST", "/containers/tailscale/start")
            time.sleep(2.0)
        except Exception as e:
            logger.debug(f"[Tailscale] Failed to start container before tailscale up: {e}")

    cmd = ["up", "--reset"]
    if auth_key:
        cmd.extend(["--authkey", auth_key])
    if hostname:
        cmd.extend(["--hostname", hostname])
    if accept_routes:
        cmd.append("--accept-routes")
    if not auth_key:
        cmd.append("--timeout=3s")

    code, out = tailscale._run_tailscale_cmd(cmd, timeout=15.0)

    # Check for interactive authentication URL in output
    auth_url = None
    m = re.search(r"https://login\.tailscale\.com/a/[a-zA-Z0-9_-]+", out)
    if m:
        auth_url = m.group(0)
    elif "login.tailscale.com" in out:
        m2 = re.search(r"https://\S+", out)
        if m2:
            auth_url = m2.group(0)

    # If auth_url was not in stdout, query status --json fallback for AuthURL
    if not auth_url and not auth_key:
        try:
            s_code, s_out = tailscale._run_tailscale_cmd(["status", "--json"], timeout=4.0)
            if s_code == 0 and s_out.strip().startswith("{"):
                import json

                s_doc = json.loads(s_out.strip())
                if s_doc.get("AuthURL"):
                    auth_url = s_doc["AuthURL"]
        except Exception as e:
            logger.debug(f"[Network] Fallback status json check: {e}")

    if auth_url:
        return {
            "status": "needs_login",
            "code": 0,
            "auth_url": auth_url,
            "output": out,
            "message": "Authentication required. Visit the authorization URL to link this device.",
        }

    if code == 0:
        return {
            "status": "success",
            "code": 0,
            "output": out or "Tailscale connected successfully",
        }

    if code == 127:
        return {"status": "error", "code": 127, "output": "tailscale CLI or container not found on host"}

    return {"status": "error", "code": code, "output": out or "Tailscale connection failed"}


def execute_tailscale_down() -> dict[str, Any]:
    """Disconnects host from the Zero-Trust Tailscale mesh network."""
    c_info = tailscale._get_tailscale_container_info()
    if c_info.get("exists"):
        try:
            from backend.services.container_mutator import _docker_request

            if c_info.get("running"):
                tailscale._run_tailscale_cmd(["down"], timeout=5.0)
                _docker_request("POST", "/containers/tailscale/stop?t=5")
            return {
                "status": "success",
                "code": 0,
                "output": "Tailscale container stopped and disconnected",
            }
        except Exception as e:
            return {"status": "error", "code": 1, "output": str(e)}

    code, out = tailscale._run_tailscale_cmd(["down"], timeout=10.0)
    if code == 0:
        return {
            "status": "success",
            "code": 0,
            "output": out or "Tailscale disconnected successfully",
        }
    if code == 127:
        return {"status": "error", "code": 127, "output": "tailscale CLI or container not found on host"}
    return {"status": "error", "code": code, "output": out or "Tailscale disconnection failed"}


def deploy_tailscale_container(
    auth_key: str | None = None,
    hostname: str | None = None,
    accept_routes: bool = True,
    state_dir: str | None = None,
) -> dict[str, Any]:
    """
    1-Click turnkey provisioning of the official Tailscale Docker container
    with host network mode, NET_ADMIN caps, and persistent state storage.
    """
    from backend.hardware.docker_stats import UnixHTTPConnection
    from backend.services.container_mutator import _docker_request

    sock_path = common.docker_sock()
    if not os.path.exists(sock_path):
        return {
            "status": "error",
            "message": "Docker socket /var/run/docker.sock not available. Docker is required for 1-click deployment.",
        }

    # 1. Check if 'tailscale' container already exists
    st_exist, c_info = _docker_request("GET", "/containers/tailscale/json")
    if st_exist == 200 and isinstance(c_info, dict):
        cid = str(c_info.get("Id", ""))[:12]
        is_running = bool(c_info.get("State", {}).get("Running", False))
        if not is_running:
            _docker_request("POST", "/containers/tailscale/start")
            time.sleep(2)

        if auth_key:
            up_res = execute_tailscale_up(auth_key=auth_key, hostname=hostname, accept_routes=accept_routes)
            return {
                "status": "success",
                "container_id": cid,
                "message": "Tailscale container started and connected with auth key.",
                "details": up_res,
            }
        else:
            up_res = execute_tailscale_up(hostname=hostname, accept_routes=accept_routes)
            auth_url = up_res.get("auth_url")
            return {
                "status": "success",
                "container_id": cid,
                "auth_url": auth_url,
                "backend_state": "NeedsLogin" if auth_url else "Running",
                "message": (
                    "Tailscale container running. Please authenticate in your browser to complete setup."
                    if auth_url
                    else "Tailscale container running."
                ),
            }

    # 2. Pull official image if not cached locally
    image_name = "tailscale/tailscale:stable"
    st_img, _ = _docker_request("GET", f"/images/{image_name}/json")
    if st_img != 200:
        logger.info(f"[Network] Pulling image {image_name} for 1-click Tailscale deployment...")
        pull_conn = None
        try:
            pull_conn = UnixHTTPConnection(sock_path, timeout=180.0)
            pull_conn.request("POST", "/images/create?fromImage=tailscale/tailscale&tag=stable")
            res_p = pull_conn.getresponse()
            while True:
                chunk = res_p.read(4096)
                if not chunk:
                    break
        except Exception as e:
            logger.warning(f"[Network] Image pull notice: {e}")
        finally:
            if pull_conn:
                try:
                    pull_conn.close()
                except Exception:
                    logger.debug("backend.hardware.network.deploy_tailscale_container: ignored error", exc_info=True)

    # 3. Resolve persistent host storage directory
    if not state_dir:
        if os.path.isdir("/mnt/user/appdata"):
            state_dir = "/mnt/user/appdata/tailscale"
        else:
            from backend.config import DATA_DIR

            state_dir = os.path.join(DATA_DIR, "tailscale")
    try:
        os.makedirs(state_dir, exist_ok=True)
    except Exception as e:
        logger.warning(f"[Network] Could not create state_dir {state_dir}: {e}")

    # 4. Configure environment variables
    env_vars = [
        "TS_STATE_DIR=/var/lib/tailscale",
        "TS_USERSPACE=false",
    ]
    if hostname:
        env_vars.append(f"TS_HOSTNAME={hostname.strip()}")
    if auth_key:
        env_vars.append(f"TS_AUTHKEY={auth_key.strip()}")
    if accept_routes:
        env_vars.append("TS_EXTRA_ARGS=--reset --accept-routes")
    else:
        env_vars.append("TS_EXTRA_ARGS=--reset")

    # 5. Device and capabilities handling
    devices = []
    if os.path.exists("/dev/net/tun") or os.path.exists("/host/dev/net/tun"):
        devices.append(
            {
                "PathOnHost": "/dev/net/tun",
                "PathInContainer": "/dev/net/tun",
                "CgroupPermissions": "rwm",
            }
        )
    else:
        # Fallback to userspace networking if /dev/net/tun is unavailable
        env_vars = [e for e in env_vars if not e.startswith("TS_USERSPACE=")]
        env_vars.append("TS_USERSPACE=true")

    create_body = {
        "Image": image_name,
        "Env": env_vars,
        "HostConfig": {
            "NetworkMode": "host",
            "CapAdd": ["NET_ADMIN", "NET_RAW"],
            "Binds": [f"{state_dir}:/var/lib/tailscale"],
            "Devices": devices,
            "RestartPolicy": {"Name": "unless-stopped"},
        },
        "Labels": {
            "com.docker.compose.project": "tailscale",
            "com.docker.compose.service": "tailscale",
            "net.unraid.docker.managed": "dockerman",
            "net.unraid.docker.icon": "https://raw.githubusercontent.com/tailscale/tailscale/main/cmd/tailscale/logo.png",
            "app.name": "Tailscale Zero-Trust Mesh",
        },
    }

    # 6. Create container
    st_create, res_create = _docker_request("POST", "/containers/create?name=tailscale", body=create_body)
    if st_create != 201:
        err_msg = res_create.get("message") if isinstance(res_create, dict) else str(res_create)
        return {"status": "error", "message": f"Failed to create Tailscale container: {err_msg}"}

    cid = str(res_create.get("Id", ""))

    # 7. Start container
    st_start, res_start = _docker_request("POST", f"/containers/{cid}/start")
    if st_start not in (204, 304):
        err_msg = res_start.get("message") if isinstance(res_start, dict) else str(res_start)
        return {"status": "error", "message": f"Failed to start Tailscale container: {err_msg}"}

    time.sleep(2.5)

    # 8. Check auth requirement or trigger login
    auth_url = None
    if not auth_key:
        up_res = execute_tailscale_up(hostname=hostname, accept_routes=accept_routes)
        auth_url = up_res.get("auth_url")
    else:
        execute_tailscale_up(auth_key=auth_key, hostname=hostname, accept_routes=accept_routes)

    return {
        "status": "success",
        "container_id": cid[:12],
        "state_dir": state_dir,
        "auth_url": auth_url,
        "backend_state": "NeedsLogin" if auth_url else "Running",
        "message": (
            "Tailscale container deployed. Please authenticate in your browser to complete setup."
            if auth_url
            else "Tailscale container deployed and connected to Tailnet."
        ),
    }
