"""Tailscale, natively or in its container: status, Taildrop, ping, routes, exit node, SSH, Serve and Funnel, re-authentication.

Part of backend/hardware/network.py, split out by ARC-5."""

import os
import re
import shutil
import subprocess
from datetime import UTC
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.net import common
from backend.ignored_errors import ignored

SETTINGS_FILE = os.path.join(DATA_DIR, "remote_access.json")
# a Headscale (or other control) server: https, a host and maybe a port, nothing after it
LOGIN_SERVER = re.compile(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?/?$")


def settings() -> dict[str, Any]:
    """Remote access settings (COMP-01): the login server and the port Kiboto is served from."""
    data = read_json(SETTINGS_FILE, {})
    return data if isinstance(data, dict) else {}


def update_settings(**fields: Any) -> dict[str, Any]:
    data = {**settings(), **fields}
    atomic_write_json(SETTINGS_FILE, data)
    return data


def login_server() -> str:
    """The control server this node signs in to; "" is Tailscale's own."""
    return str(settings().get("login_server") or "")


def set_login_server(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url and not LOGIN_SERVER.match(url):
        raise ValueError("A Headscale address is https://<your server>, with a port if it needs one and no path.")
    update_settings(login_server=url)
    return url


def login_args() -> list[str]:
    """Every `tailscale up` repeats the login server: with --reset, leaving it out would move
    the node back to Tailscale's servers."""
    server = login_server()
    return [f"--login-server={server}"] if server else []


def auth_url_in(text: str) -> str:
    """The sign-in link `tailscale up` printed, from Tailscale or from the login server."""
    m = re.search(r"https://login\.tailscale\.com/a/[A-Za-z0-9_-]+", text or "")
    if m:
        return m.group(0)
    server = login_server()
    if server:
        m = re.search(re.escape(server) + r"/\S+", text or "")
        if m:
            return m.group(0)
    return ""


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


def container_info() -> dict[str, Any]:
    return _get_tailscale_container_info()


def installed() -> bool:
    """A tailscale container (running or not) or the tailscale program on the host."""
    return bool(_get_tailscale_container_info().get("exists") or _find_tailscale_bin())


def run_cli(args: list[str], timeout: float = 10.0) -> tuple[int, str]:
    return _run_tailscale_cmd(args, timeout=timeout)


def _as_text(value: str | bytes | None) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


EXEC_WAIT_CAP = 8  # seconds a waiting serve/funnel command gets inside the container


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
                # below the Docker exec connection's own 10 s, so what it printed (an approval link)
                # comes back instead of a read timeout and a misleading "container is stopped"
                cmd_list = ["timeout", str(max(1, min(int(timeout), EXEC_WAIT_CAP))), "tailscale"] + args
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


def detect_local_subnets(fallback: bool = True) -> list[str]:
    """Detects local physical IPv4 network subnets (e.g. ['192.168.1.0/24']). With fallback, a guess
    when none is found (a suggestion for the subnet router field); without, an empty list."""
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
    if not subnets and fallback:
        subnets = ["192.168.1.0/24"]
    return subnets


def lan_route_conflicts(doc: dict[str, Any]) -> list[dict[str, str]]:
    """Subnet routes other nodes offer that cover a network this NAS is on. Accepting one sends the
    NAS's own home traffic into the tailnet: it drops off its network until the route goes."""
    import ipaddress

    lans = []
    for s in detect_local_subnets(fallback=False):
        try:
            lans.append(ipaddress.ip_network(s, strict=False))
        except ValueError:
            continue
    out = []
    for peer in (doc.get("Peer") or {}).values():
        for route in peer.get("PrimaryRoutes") or []:
            try:
                net = ipaddress.ip_network(route, strict=False)
            except ValueError:
                continue
            if net.prefixlen == 0:
                continue  # an exit node's default route is chosen on purpose, not accepted with routes
            for lan in lans:
                if net.version == lan.version and net.overlaps(lan):
                    name = str(peer.get("HostName") or peer.get("DNSName") or "another node").rstrip(".")
                    out.append({"peer": name, "route": str(net), "lan": str(lan)})
    return out


def guard_lan_routes(doc: dict[str, Any] | None = None, route_all: bool | None = None) -> list[dict[str, str]]:
    """With Accept Routes on, turns it off when another node offers a route over the NAS's own
    network, and says so in Events. Returns those routes (empty when there are none)."""
    import json

    if doc is None:
        code, out = _run_tailscale_cmd(["status", "--json"], timeout=4.0)
        try:
            doc = json.loads(out) if code == 0 else {}
        except ValueError:
            doc = {}
    conflicts = lan_route_conflicts(doc or {})
    if not conflicts:
        return []
    if route_all is None:
        code, out = _run_tailscale_cmd(["debug", "prefs"], timeout=2.0)
        try:
            route_all = bool(json.loads(out).get("RouteAll")) if code == 0 else False
        except ValueError:
            route_all = False
    if route_all:
        code, out = _run_tailscale_cmd(["set", "--accept-routes=false"], timeout=8.0)
        what = ", ".join(f"{c['peer']} offers {c['route']}" for c in conflicts)
        logger.warning(
            "[Tailscale] Accept Routes turned off: %s, the network this NAS is on (%s)", what, out.strip()[:120]
        )
        try:
            from backend.state import add_event

            add_event(
                "warning",
                "Tailscale routes not accepted",
                f"{what}: the network this NAS is on. Accepting it would cut the NAS off from your home network, "
                "so Accept Routes is off.",
            )
        except (ImportError, OSError, ValueError, RuntimeError) as e:
            logger.debug("[Tailscale] the routes event was not recorded: %s", e)
    return conflicts


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


def execute_tailscale_reauth() -> dict[str, Any]:
    """Forces Tailscale node re-authentication, returning interactive login URL."""
    import re

    code, out = _run_tailscale_cmd(["up", "--force-reauth", "--reset", *login_args()], timeout=8.0)
    auth_url = auth_url_in(out)
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


run_tailscale_cmd = _run_tailscale_cmd  # shared with public share links (NFEAT-2)
