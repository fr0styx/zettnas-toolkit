"""Tailscale, natively or in its container: status, Taildrop, ping, routes, exit node, SSH, Serve and Funnel, re-authentication.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import shutil
import subprocess
from datetime import UTC
from typing import Any

from backend.config import logger
from backend.hardware.net import common
from backend.ignored_errors import ignored


def _find_tailscale_bin() -> str | None:
    """Finds tailscale CLI executable across standard PATH and NAS host plugin paths."""
    ts_bin = shutil.which("tailscale")
    if ts_bin:
        return ts_bin
    for cand in (
        "/usr/local/sbin/tailscale",
        "/usr/sbin/tailscale",
        "/usr/bin/tailscale",
        "/usr/local/bin/tailscale",
        "/usr/local/emhttp/plugins/tailscale/bin/tailscale",
    ):
        if os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _get_tailscale_container_info() -> dict[str, Any]:
    """Checks if a Docker container named 'tailscale' exists and returns its state."""
    try:
        from backend.services.container_mutator import _docker_request

        status, data = _docker_request("GET", "/containers/tailscale/json")
        if status == 200 and isinstance(data, dict):
            state = data.get("State", {})
            return {
                "exists": True,
                "running": bool(state.get("Running", False)),
                "id": str(data.get("Id", ""))[:12],
                "status": state.get("Status", "unknown"),
            }
    except Exception:
        ignored("backend.hardware.network._get_tailscale_container_info")
    return {"exists": False, "running": False, "id": "", "status": "not_found"}


def _as_text(value: str | bytes | None) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def _run_tailscale_cmd(args: list[str], timeout: float = 10.0) -> tuple[int, str]:
    """
    Executes a Tailscale command using Docker exec if 'tailscale' container is running,
    or falls back to native host binary if present and daemon is accessible.
    Returns (returncode, output_text).
    """
    c_info = _get_tailscale_container_info()
    use_container = bool(c_info.get("exists") and c_info.get("running"))

    if use_container:
        try:
            from backend.services.compose_synthesizer import execute_in_container

            # If command can block for approval (like serve or funnel activation),
            # wrap with timeout so Docker exec returns output cleanly before timing out
            cmd_list = ["tailscale"] + args
            if args and args[0] in ("serve", "funnel") and len(args) > 1 and args[1] not in ("status", "reset"):
                cmd_list = ["timeout", str(max(1, int(timeout))), "tailscale"] + args
            res = execute_in_container("tailscale", cmd_list)
            if res.get("success"):
                exit_code = res.get("exit_code", 0)
                out = (res.get("output") or "").strip()
                return exit_code, out
        except Exception as e:
            logger.debug(f"[Tailscale] Container execution error: {e}")

    # Fallback to native host binary
    ts_bin = _find_tailscale_bin()
    bin_cmd = ts_bin or "tailscale"
    try:
        r = subprocess.run([bin_cmd] + args, capture_output=True, text=True, timeout=timeout)
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return r.returncode, out
    except subprocess.TimeoutExpired as te:
        # what it printed before the timeout comes as bytes, even with text=True
        out = (_as_text(te.stdout) + "\n" + _as_text(te.stderr)).strip()
        return 1, out or "Command timed out"
    except FileNotFoundError:
        pass
    except Exception as e:
        return 1, str(e)

    if c_info.get("exists"):
        return 1, "Tailscale container is stopped"

    return 127, "tailscale CLI or running container not found"


def detect_local_subnets() -> list[str]:
    """Detects local physical IPv4 network subnets (e.g. ['192.168.1.0/24'])."""
    subnets = []
    try:
        routes = common._parse_routes()
        for r in routes:
            iface = r.get("iface", "")
            if r.get("is_default") or iface.startswith(
                ("lo", "docker", "shim-", "br-", "tunl", "wg", "tailscale", "veth")
            ):
                continue
            dest = r.get("destination", "")
            cidr = r.get("cidr", 24)
            if dest and dest != "0.0.0.0" and not dest.startswith(("127.", "169.254.")):
                s = f"{dest}/{cidr}"
                if s not in subnets:
                    subnets.append(s)
    except Exception as e:
        logger.debug(f"[Network] Error detecting subnets: {e}")
    if not subnets:
        subnets = ["192.168.1.0/24"]
    return subnets


def get_taildrop_dir() -> str:
    """Finds or creates persistent Taildrop directory on host."""
    from backend.config import DATA_DIR

    candidates = [
        "/mnt/user/downloads/taildrop",
        "/mnt/user/appdata/tailscale/taildrop",
        os.path.join(DATA_DIR, "tailscale", "taildrop"),
    ]
    for c in candidates:
        try:
            parent = os.path.dirname(c)
            if os.path.isdir(parent):
                os.makedirs(c, exist_ok=True)
                return c
        except Exception:
            continue
    fallback = os.path.join(DATA_DIR, "taildrop")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def get_taildrop_inbox_files() -> list[dict[str, Any]]:
    """Lists files received via Taildrop."""
    from datetime import datetime

    target_dir = get_taildrop_dir()
    files = []
    if not os.path.isdir(target_dir):
        return files
    try:
        for entry in os.scandir(target_dir):
            if entry.is_file():
                try:
                    st = entry.stat()
                    size_b = st.st_size
                    if size_b < 1024:
                        size_fmt = f"{size_b} B"
                    elif size_b < 1024 * 1024:
                        size_fmt = f"{size_b / 1024:.1f} KB"
                    elif size_b < 1024 * 1024 * 1024:
                        size_fmt = f"{size_b / (1024 * 1024):.1f} MB"
                    else:
                        size_fmt = f"{size_b / (1024 * 1024 * 1024):.2f} GB"
                    mtime_iso = datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%d %H:%M")
                    files.append(
                        {
                            "name": entry.name,
                            "size_bytes": size_b,
                            "size_formatted": size_fmt,
                            "modified_at": mtime_iso,
                            "path": entry.path,
                        }
                    )
                except Exception:
                    ignored("backend.hardware.network.get_taildrop_inbox_files")
    except Exception as e:
        logger.debug(f"[Tailscale] Failed to read taildrop inbox: {e}")
    files.sort(key=lambda x: x["name"].lower())
    return files


def execute_tailscale_taildrop_receive() -> dict[str, Any]:
    """Ingests any pending files from Taildrop queue into the inbox."""
    target_dir = get_taildrop_dir()
    c_info = _get_tailscale_container_info()
    if c_info.get("exists") and c_info.get("running"):
        cmd = ["file", "get", "--conflict=rename", "/var/lib/tailscale/taildrop"]
    else:
        cmd = ["file", "get", "--conflict=rename", target_dir]
    code, out = _run_tailscale_cmd(cmd, timeout=12.0)
    files = get_taildrop_inbox_files()
    return {
        "status": "ok" if code == 0 else "error",
        "code": code,
        "output": out,
        "directory": target_dir,
        "files": files,
        "count": len(files),
        "received_count": len(files),
    }


def execute_tailscale_ping(peer: str) -> dict[str, Any]:
    """Pings a Tailscale peer and parses round-trip latency and route path."""
    import re

    clean_peer = peer.strip()
    if not clean_peer:
        return {"status": "error", "message": "Peer IP or hostname is required"}
    code, out = _run_tailscale_cmd(["ping", "--c=1", "--timeout=2s", clean_peer], timeout=4.0)
    out_clean = out.strip()
    if "pong from" in out_clean.lower():
        route = ""
        latency_str = ""
        latency_ms = None
        m_route = re.search(r"via\s+([^\s]+)", out_clean)
        if m_route:
            route = m_route.group(1)
        m_time = re.search(r"in\s+([0-9.]+)\s*(ms|s)", out_clean)
        if m_time:
            val = float(m_time.group(1))
            unit = m_time.group(2)
            latency_ms = val if unit == "ms" else val * 1000.0
            latency_str = f"{latency_ms:.1f} ms"
        is_direct = bool(route and not route.lower().startswith("derp"))
        return {
            "status": "success",
            "peer": clean_peer,
            "route": route,
            "latency": latency_str,
            "latency_ms": latency_ms,
            "is_direct": is_direct,
            "output": out_clean,
        }
    return {
        "status": "error",
        "peer": clean_peer,
        "output": out_clean or "Ping timed out or peer is unreachable",
    }


def execute_tailscale_set_routes(routes: str, enabled: bool = True) -> dict[str, Any]:
    """Advertises or withdraws subnet routes to the Tailnet."""
    clean_routes = routes.strip() if enabled else ""
    if clean_routes:
        parts = [p.strip() for p in clean_routes.split(",") if p.strip() and p.strip() not in ("0.0.0.0/0", "::/0")]
        clean_routes = ",".join(parts)
    cmd = ["set", f"--advertise-routes={clean_routes}"]
    code, out = _run_tailscale_cmd(cmd, timeout=8.0)
    return {
        "status": "ok" if code == 0 else "error",
        "code": code,
        "enabled": enabled and bool(clean_routes),
        "advertised_routes": clean_routes,
        "output": out,
    }


def execute_tailscale_set_exit_node(enabled: bool) -> dict[str, Any]:
    """Advertises this node as a Tailscale Exit Node."""
    val = "true" if enabled else "false"
    cmd = ["set", f"--advertise-exit-node={val}"]
    code, out = _run_tailscale_cmd(cmd, timeout=8.0)
    return {
        "status": "ok" if code == 0 else "error",
        "code": code,
        "enabled": enabled,
        "output": out,
    }


def execute_tailscale_set_ssh(enabled: bool) -> dict[str, Any]:
    """Enables or disables Tailscale SSH."""
    val = "true" if enabled else "false"
    cmd = ["set", f"--ssh={val}"]
    code, out = _run_tailscale_cmd(cmd, timeout=8.0)
    return {
        "status": "ok" if code == 0 else "error",
        "code": code,
        "enabled": enabled,
        "output": out,
    }


def execute_tailscale_set_serve(serve: bool, funnel: bool = False, port: int = 8082) -> dict[str, Any]:
    """Configures Tailscale Serve and Funnel proxy for ZettNAS Web Desktop."""
    import json
    import re

    approval_url = ""
    error_msg = ""
    feature = "serve"
    _code_s = 0
    _code_f = 0

    # 1. Handle Serve
    if serve:
        _code_s, out_s = _run_tailscale_cmd(["serve", "--bg", "--yes", str(port)], timeout=3.0)
        m_s = re.search(r"https://login\.tailscale\.com/f/serve[^\s]+", out_s)
        if m_s:
            approval_url = m_s.group(0)
            feature = "serve"
        elif _code_s != 0 and "No serve config" not in out_s and "login.tailscale.com" not in out_s:
            error_msg = out_s.strip()
    else:
        _run_tailscale_cmd(["serve", "reset"], timeout=4.0)

    # 2. Handle Funnel
    if funnel and serve and not approval_url:
        _code_f, out_f = _run_tailscale_cmd(["funnel", "--bg", "--yes", str(port)], timeout=3.0)
        m_f = re.search(r"https://login\.tailscale\.com/f/funnel[^\s]+", out_f)
        if m_f:
            approval_url = m_f.group(0)
            feature = "funnel"
        elif _code_f != 0 and "No serve config" not in out_f and "login.tailscale.com" not in out_f:
            if not error_msg:
                error_msg = out_f.strip()
    elif not funnel:
        _run_tailscale_cmd(["funnel", "reset"], timeout=4.0)

    # Check actual status from tailscale daemon
    sv_code, sv_out = _run_tailscale_cmd(["serve", "status", "--json"], timeout=3.0)
    actual_serve = (sv_code == 0 and sv_out.strip().startswith("{") and len(sv_out.strip()) > 2) or (
        _code_s == 0 and not approval_url and serve
    )

    actual_funnel = False
    if actual_serve:
        fn_code, fn_out = _run_tailscale_cmd(["funnel", "status", "--json"], timeout=3.0)
        actual_funnel = (fn_code == 0 and "AllowFunnel" in fn_out) or (_code_f == 0 and funnel and serve)

    # The address to open on a phone or laptop in the tailnet (M2)
    serve_url = ""
    if actual_serve:
        st_code, st_out = _run_tailscale_cmd(["status", "--json"], timeout=3.0)
        if st_code == 0 and st_out.strip().startswith("{"):
            try:
                dns = (json.loads(st_out).get("Self") or {}).get("DNSName", "").rstrip(".")
                serve_url = f"https://{dns}" if dns else ""
            except ValueError:
                logger.debug("network.execute_tailscale_set_serve: status not JSON", exc_info=True)

    return {
        "status": "needs_approval"
        if approval_url
        else ("ok" if (actual_serve or not serve) else ("error" if error_msg else "pending")),
        "serve_url": serve_url,
        "serve_enabled": actual_serve,
        "funnel_enabled": actual_funnel,
        "approval_url": approval_url,
        "feature": feature,
        "error": error_msg,
        "port": port,
    }


def execute_tailscale_reauth() -> dict[str, Any]:
    """Forces Tailscale node re-authentication, returning interactive login URL."""
    import re

    code, out = _run_tailscale_cmd(["up", "--force-reauth", "--reset"], timeout=8.0)
    m = re.search(r"https://login\.tailscale\.com/a/[a-zA-Z0-9_-]+", out)
    auth_url = m.group(0) if m else ""
    if not auth_url:
        s_code, s_out = _run_tailscale_cmd(["status", "--json"], timeout=4.0)
        if s_code == 0 and s_out.strip().startswith("{"):
            try:
                import json

                s_doc = json.loads(s_out.strip())
                auth_url = s_doc.get("AuthURL", "")
            except Exception:
                ignored("backend.hardware.network.execute_tailscale_reauth")
    return {
        "status": "needs_login" if auth_url else ("ok" if code == 0 else "error"),
        "auth_url": auth_url,
        "output": out,
    }
