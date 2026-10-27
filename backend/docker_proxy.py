"""
Docker API proxy with an allow-list (SEC-09).

The web process no longer talks to /var/run/docker.sock directly. It talks to this
proxy, which runs as its own process and forwards only the Docker API calls the app
uses. Everything else (swarm, plugins, secrets, image build/load/import, commit,
export, …) is refused with 403.

Creating a container (or an exec) that could take over the host needs the request
header `X-ZettNAS-Elevated: 1`. Only flows the user confirms send it (installing an
app after its security review, recreating an existing container, the self-updater).
Every elevated request is written to data/docker-proxy-audit.log.

Elevated means any of: privileged, host PID/IPC/user namespace, dangerous
capabilities, seccomp/AppArmor disabled, raw block devices, or bind mounts of the
Docker socket, "/", /etc, /boot, /root, /proc, /sys, /dev, /var/lib/docker, /usr.

Run with `python -m backend.docker_proxy`. backend.main starts it under the
supervisor and points the app at it via ZETTNAS_DOCKER_SOCK.
"""

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
from typing import Any

logger = logging.getLogger("ZettNAS.docker_proxy")
UPSTREAM = os.environ.get("ZETTNAS_DOCKER_UPSTREAM", "/var/run/docker.sock")
LISTEN = os.environ.get("ZETTNAS_DOCKER_PROXY_SOCK", "/run/zettnas/docker.sock")
ELEVATED_HEADER = "x-zettnas-elevated"
MAX_HEAD = 64 * 1024
MAX_POLICY_BODY = 4 * 1024 * 1024

_ID = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
_IMG = r"[A-Za-z0-9][A-Za-z0-9_./:@-]*"
ALLOW: dict[str, list[str]] = {
    "GET": [
        r"/_ping",
        r"/version",
        r"/info",
        r"/events",
        r"/system/df",
        r"/containers/json",
        rf"/containers/{_ID}/(json|logs|stats|top|changes|archive)",
        r"/images/json",
        rf"/images/{_IMG}/(json|history)",
        rf"/distribution/{_IMG}/json",
        r"/networks",
        rf"/networks/{_ID}",
        r"/volumes",
        rf"/volumes/{_ID}",
        rf"/exec/{_ID}/json",
    ],
    "HEAD": [r"/_ping", rf"/containers/{_ID}/archive"],
    "POST": [
        r"/containers/create",
        r"/containers/prune",
        rf"/containers/{_ID}/(start|stop|restart|kill|pause|unpause|update|rename|wait|resize|exec|attach)",
        rf"/exec/{_ID}/(start|resize)",
        r"/images/create",
        r"/images/prune",
        rf"/images/{_IMG}/tag",
        r"/networks/create",
        r"/networks/prune",
        rf"/networks/{_ID}/(connect|disconnect)",
        r"/volumes/create",
        r"/volumes/prune",
        r"/build/prune",
    ],
    # Writing files into a container (compose stack files)
    "PUT": [rf"/containers/{_ID}/archive"],
    "DELETE": [rf"/containers/{_ID}", rf"/images/{_IMG}", rf"/networks/{_ID}", rf"/volumes/{_ID}"],
}
_ALLOW_RE = {m: re.compile("^(?:" + "|".join(p) + ")$") for m, p in ALLOW.items()}
_VERSION_PREFIX = re.compile(r"^/v\d+\.\d+(?=/)")

DANGEROUS_CAPS = {
    "ALL",
    "SYS_ADMIN",
    "SYS_MODULE",
    "SYS_PTRACE",
    "SYS_RAWIO",
    "SYS_BOOT",
    "DAC_READ_SEARCH",
    "BPF",
    "PERFMON",
    "MAC_ADMIN",
}
HOST_PATHS = (
    "/etc",
    "/boot",
    "/root",
    "/proc",
    "/sys",
    "/dev",
    "/var",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/var/run",
    "/run",
)
SAFE_HOST_PATHS = (
    "/etc/localtime",
    "/etc/timezone",
    "/dev/dri",
    "/dev/net/tun",
    "/dev/snd",
    "/dev/bus/usb",
    "/dev/serial",
    "/dev/fuse",
)
SAFE_DEVICE_RE = re.compile(
    r"^/dev/(dri(/.*)?|net/tun|snd(/.*)?|bus/usb(/.*)?|serial/.*|ttyUSB\d+|ttyACM\d+|video\d+|fuse|hidraw\d+|apex_\d+|kfd)$"
)


def normalize_path(target: str) -> tuple[str, str] | None:
    """Splits a request target into (path, query); None if it's unsafe to route."""
    parts = urllib.parse.urlsplit(target)
    path = parts.path
    if not path.startswith("/") or "%" in path or "//" in path or "\\" in path:
        return None
    if any(seg in (".", "..") for seg in path.split("/")):
        return None
    return _VERSION_PREFIX.sub("", path), parts.query


def endpoint_allowed(method: str, path: str) -> bool:
    rx = _ALLOW_RE.get(method.upper())
    return bool(rx and rx.match(path))


def _bind_source(bind: str) -> str:
    return bind.split(":", 1)[0] if ":" in bind else bind


def _app_folders() -> list[str]:
    """ZettNAS's own data and install folders (users.db, secret.key): never mounted into apps."""
    try:
        from backend.fsutil import protected_dirs

        return protected_dirs()
    except Exception:
        logger.debug("docker_proxy: app folders unknown", exc_info=True)
        return []


def _risky_host_path(src: str) -> str | None:
    src = os.path.normpath(src) if src.startswith("/") else src
    if not src.startswith("/"):
        return None  # a named volume
    if src == "/":
        return "/"
    if src.endswith(("docker.sock", "containerd.sock", "podman.sock")):
        return src
    if any(src == d or src.startswith(d.rstrip("/") + "/") for d in _app_folders()):
        return src
    if any(src == s or src.startswith(s + "/") for s in SAFE_HOST_PATHS):
        return None
    for p in HOST_PATHS:
        if src == p or src.startswith(p + "/"):
            return src
    return None


def volume_reasons(body: dict[str, Any]) -> list[str]:
    """A local volume with o=bind is a bind mount in disguise: check its device path too."""
    opts = body.get("DriverOpts") or {}
    if not isinstance(opts, dict):
        return []
    if "bind" not in str(opts.get("o") or "") and not opts.get("device"):
        return []
    device = str(opts.get("device") or "")
    hit = _risky_host_path(device) if device else None
    return [f"volume bind {hit}"] if hit else []


def elevated_reasons(path: str, body: dict[str, Any]) -> list[str]:
    """Why a create/exec request could take over the host (empty list = it can't)."""
    reasons: list[str] = []
    if path.endswith("/exec"):
        if body.get("Privileged"):
            reasons.append("privileged exec")
        return reasons
    if path != "/containers/create":
        return reasons
    hc = body.get("HostConfig") or {}
    if hc.get("Privileged"):
        reasons.append("privileged")
    for key in ("PidMode", "IpcMode", "UsernsMode", "UTSMode", "NetworkMode"):
        mode = str(hc.get(key) or "").lower()
        if mode == "host":
            reasons.append(f"{key}=host")
        elif mode.startswith("container:"):
            # SEC-25: joining another container's namespaces reaches whatever that one can
            reasons.append(f"{key}={mode}")
    if str(hc.get("CgroupnsMode") or "").lower() == "host":
        reasons.append("CgroupnsMode=host")
    if hc.get("VolumesFrom"):
        # SEC-25: every mount of another container, e.g. ZettNAS's own docker.sock and data folder
        reasons.append("volumes-from " + ", ".join(str(v) for v in hc.get("VolumesFrom") or []))
    caps = {str(c).upper().removeprefix("CAP_") for c in hc.get("CapAdd") or []}
    for c in sorted(caps & DANGEROUS_CAPS):
        reasons.append(f"cap {c}")
    for opt in hc.get("SecurityOpt") or []:
        o = str(opt).replace(":", "=").lower()
        if o in ("seccomp=unconfined", "apparmor=unconfined", "label=disable", "systempaths=unconfined"):
            reasons.append(f"security-opt {opt}")
        elif o.startswith("seccomp=") and o not in ("seccomp=default", "seccomp=builtin"):
            reasons.append("security-opt custom seccomp profile")  # SEC-25: can allow any syscall
    for b in hc.get("Binds") or []:
        hit = _risky_host_path(_bind_source(str(b)))
        if hit:
            reasons.append(f"bind {hit}")
    for m in hc.get("Mounts") or []:
        if isinstance(m, dict) and m.get("Type", "bind") == "bind":
            hit = _risky_host_path(str(m.get("Source") or ""))
            if hit:
                reasons.append(f"mount {hit}")
        elif isinstance(m, dict) and m.get("Type") == "volume":
            # SEC-25: an inline local volume with o=bind is a bind mount of any host path
            opts = ((m.get("VolumeOptions") or {}).get("DriverConfig") or {}).get("Options") or {}
            reasons += [r.replace("volume bind", "mount volume bind") for r in volume_reasons({"DriverOpts": opts})]
    for d in hc.get("Devices") or []:
        host = str(d.get("PathOnHost") if isinstance(d, dict) else d).split(":", 1)[0]
        if not SAFE_DEVICE_RE.match(host):
            reasons.append(f"device {host}")
    if hc.get("DeviceCgroupRules"):
        reasons.append("device cgroup rules")
    return reasons


def check_request(method: str, target: str, headers: dict[str, str], body: bytes | None) -> tuple[bool, str, list[str]]:
    """Returns (allowed, refusal message, elevated reasons)."""
    norm = normalize_path(target)
    if norm is None:
        return False, "path not allowed", []
    path, _ = norm
    if not endpoint_allowed(method, path):
        return False, f"{method} {path} is not allowed by the ZettNAS Docker proxy", []
    if method.upper() == "POST" and (path == "/containers/create" or path.endswith("/exec")):
        try:
            parsed = json.loads(body or b"{}")
        except ValueError:
            return False, "request body is not JSON", []
        if not isinstance(parsed, dict):
            return False, "request body is not a JSON object", []
        reasons = elevated_reasons(path, parsed)
        if reasons and headers.get(ELEVATED_HEADER) != "1":
            return False, "elevated container settings need confirmation: " + ", ".join(reasons), reasons
        return True, "", reasons
    if method.upper() == "PUT" and path.startswith("/containers/") and path.endswith("/archive"):
        # SEC-25: writing files into a container (ZettNAS's own included) is never needed by the app
        if headers.get(ELEVATED_HEADER) != "1":
            return False, "writing files into a container needs confirmation", ["archive write"]
        return True, "", ["archive write"]
    if method.upper() == "POST" and path == "/volumes/create":
        try:
            parsed = json.loads(body or b"{}")
        except ValueError:
            return False, "request body is not JSON", []
        reasons = volume_reasons(parsed if isinstance(parsed, dict) else {})
        if reasons and headers.get(ELEVATED_HEADER) != "1":
            return False, "elevated volume settings need confirmation: " + ", ".join(reasons), reasons
        return True, "", reasons
    return True, "", []


def _audit(method: str, target: str, reasons: list[str], body: bytes | None) -> None:
    data_dir = os.environ.get("DATA_DIR", "/app/data")
    try:
        parsed = json.loads(body or b"{}")
    except ValueError:
        parsed = {}
    entry = {"ts": time.time(), "method": method, "target": target, "image": parsed.get("Image"), "reasons": reasons}
    try:
        with open(os.path.join(data_dir, "docker-proxy-audit.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        logger.debug("docker_proxy: connection closed early", exc_info=True)


def _refusal(status: int, message: str) -> bytes:
    body = json.dumps({"message": message}).encode()
    reason = {
        400: "Bad Request",
        403: "Forbidden",
        411: "Length Required",
        413: "Payload Too Large",
        502: "Bad Gateway",
    }.get(status, "Error")
    return (
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode() + body


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, OSError):
        logger.debug("docker_proxy: connection closed early", exc_info=True)
    finally:
        try:
            if writer.can_write_eof():
                writer.write_eof()
        except (OSError, RuntimeError):
            logger.debug("docker_proxy: connection closed early", exc_info=True)


_HIJACK_RE = re.compile(rf"^/(containers/{_ID}/attach|exec/{_ID}/start)$")


def _policy_body_path(path: str) -> bool:
    return path == "/containers/create" or path.endswith("/exec")


async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter, upstream: str = UPSTREAM) -> None:
    up_w = None
    try:
        try:
            head = await client_r.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, _version = lines[0].split(" ", 2)
        except ValueError:
            client_w.write(_refusal(400, "bad request line"))
            return
        method = method.upper()
        headers: dict[str, str] = {}
        out_lines = [lines[0]]
        for line in lines[1:]:
            if not line:
                continue
            k, _, v = line.partition(":")
            key = k.strip().lower()
            headers[key] = v.strip()
            if key not in ("connection", "keep-alive", "proxy-connection", ELEVATED_HEADER):
                out_lines.append(line)
        norm = normalize_path(target)
        if norm is None:
            client_w.write(_refusal(403, "path not allowed"))
            return
        path, query = norm
        body = b""
        needs_body = method == "POST" and _policy_body_path(path)
        if needs_body:
            if "chunked" in headers.get("transfer-encoding", "").lower():
                client_w.write(_refusal(411, "send a Content-Length body"))
                return
            n = int(headers.get("content-length") or 0)
            if n > MAX_POLICY_BODY:
                client_w.write(_refusal(413, "body too large"))
                return
            body = await client_r.readexactly(n) if n else b""
        ok, msg, reasons = check_request(method, target, headers, body if needs_body else None)
        if ok and path == "/images/create" and "fromSrc" in urllib.parse.parse_qs(query):
            ok, msg = False, "importing images from a request body is not allowed"
        if not ok:
            client_w.write(_refusal(403, msg))
            return
        if reasons:
            _audit(method, target, reasons, body)
        # One request per connection, so every request passes the check above. Only
        # attach and exec start may switch the connection to a raw stream.
        upgrade = "upgrade" in headers.get("connection", "").lower() and bool(_HIJACK_RE.match(path))
        out_lines.append("Connection: Upgrade" if upgrade else "Connection: close")
        try:
            up_r, up_w = await asyncio.open_unix_connection(upstream)
        except OSError as e:
            client_w.write(_refusal(502, f"docker daemon unreachable: {e}"))
            return
        up_w.write(("\r\n".join(out_lines) + "\r\n\r\n").encode("latin-1") + body)
        await up_w.drain()
        to_upstream = asyncio.ensure_future(_pipe(client_r, up_w))
        await _pipe(up_r, client_w)
        to_upstream.cancel()
    except (ConnectionError, OSError, asyncio.IncompleteReadError, ValueError):
        logger.debug("docker_proxy: connection closed early", exc_info=True)
    finally:
        for w in (up_w, client_w):
            if w is None:
                continue
            try:
                w.close()
            except (ConnectionError, OSError, RuntimeError):
                logger.debug("docker_proxy: connection closed early", exc_info=True)


async def serve(listen: str = LISTEN, upstream: str = UPSTREAM) -> asyncio.AbstractServer:
    os.makedirs(os.path.dirname(listen), exist_ok=True)
    if os.path.exists(listen):
        os.unlink(listen)
    server = await asyncio.start_unix_server(lambda r, w: handle(r, w, upstream), path=listen, limit=MAX_HEAD)
    os.chmod(listen, 0o660)
    return server


async def _main() -> None:
    server = await serve()
    print(f"[DockerProxy] {LISTEN} -> {UPSTREAM}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
