"""A NUT server for the family's PCs (FEAT-11).

The UPS ZettNAS reads (USB, apcupsd or another NUT server) is offered over the Network UPS
Tools protocol, so a Windows, Mac or Linux PC with NUT's upsmon (or WinNUT, or any NUT client)
watches it as a secondary: MONITOR ups@NAS-ADDRESS:3493 1 <user> <password> secondary. The PCs shut
down when the battery runs low, and when ZettNAS starts its own low-battery shutdown it raises
the forced-shutdown flag (FSD) and gives the PCs up to 15 seconds to go first.

Only the read side of upsd is offered (LIST, GET, LOGIN, LOGOUT); instant commands, setting
variables and becoming the primary are refused. Clients must be on the home network, and
LOGIN takes the monitor user and password set here.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

SETTINGS_FILE = os.path.join(DATA_DIR, "nut_server.json")
UPS_NAME = "ups"
DEFAULT_PORT = 3493
HOME_NETWORKS = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "100.64.0.0/10",
    "fc00::/7",
    "fe80::/10",
    "::1/128",
)
FSD_WAIT_SECS = 15.0
VERSION = "Network UPS Tools upsd 2.8.1 - ZettNAS"

_FSD = threading.Event()
_LOGINS: set[int] = set()
_LOGINS_LOCK = threading.Lock()


def settings() -> dict[str, Any]:
    saved = read_json(SETTINGS_FILE, {}) or {}
    return {
        "enabled": bool(saved.get("enabled", False)),
        "port": int(saved.get("port") or DEFAULT_PORT),
        "user": str(saved.get("user") or "monuser"),
        "password": str(saved.get("password") or ""),
        "networks": list(saved.get("networks") or HOME_NETWORKS),
    }


def _password(cfg: dict[str, Any]) -> str:
    from backend import secret_box

    return secret_box.unseal(cfg["password"]) if cfg.get("password") else ""


def save_settings(
    enabled: bool | None = None, port: int | None = None, user: str | None = None, new_password: bool = False
) -> dict[str, Any]:
    from backend import secret_box

    cfg = settings()
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if port is not None:
        if not 1 <= int(port) <= 65535:
            raise ValueError("The port is a number from 1 to 65535.")
        cfg["port"] = int(port)
    if user is not None:
        if not user or not user.replace("_", "").replace("-", "").isalnum() or len(user) > 32:
            raise ValueError("Use letters, digits, dashes and underscores for the user name.")
        cfg["user"] = user
    if new_password or not cfg["password"]:
        cfg["password"] = secret_box.seal(secrets.token_urlsafe(18))
    atomic_write_json(SETTINGS_FILE, cfg)
    return public(cfg)


def public(cfg: dict[str, Any] | None = None, show_password: bool = False) -> dict[str, Any]:
    cfg = cfg or settings()
    out = {k: v for k, v in cfg.items() if k != "password"}
    out["has_password"] = bool(cfg.get("password"))
    out["running"] = SERVER.running()
    out["logins"] = logins()
    out["fsd"] = _FSD.is_set()
    if show_password and cfg.get("password"):
        out["password"] = _password(cfg)
        out["upsmon"] = f"MONITOR {UPS_NAME}@NAS-ADDRESS:{cfg['port']} 1 {cfg['user']} {out['password']} secondary"
    return out


def logins() -> int:
    with _LOGINS_LOCK:
        return len(_LOGINS)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> str | None:
    f = _float(value)
    if f is None:
        return None
    return str(int(f)) if f == int(f) else f"{f:.1f}"


def ups_vars(status: dict[str, Any], fsd: bool = False) -> dict[str, str]:
    """NUT variables from ZettNAS's UPS reading (hardware/ups.read_ups_status)."""
    if not status.get("available"):
        return {}
    flags = ["OB" if status.get("on_battery") else "OL"]
    charge, left = _float(status.get("battery_charge_pct")), _float(status.get("time_left_min"))
    low_charge = charge is not None and charge <= (_float(status.get("policy_threshold_batt")) or 20)
    low_time = left is not None and left <= (_float(status.get("policy_threshold_runtime")) or 5)
    if status.get("on_battery") and (low_charge or low_time):
        flags.append("LB")
    if "CHARG" in str(status.get("status") or "").upper() and not status.get("on_battery"):
        flags.append("CHRG")
    if fsd:
        flags.insert(0, "FSD")
    out = {
        "ups.status": " ".join(flags),
        "device.type": "ups",
        "device.model": str(status.get("model") or "UPS"),
        "ups.model": str(status.get("model") or "UPS"),
        "driver.name": "zettnas",
        "battery.charge": _num(charge),
        "battery.runtime": _num(left * 60) if left is not None else None,
        "battery.voltage": _num(status.get("battery_volts")),
        "ups.load": _num(status.get("load_pct")),
        "ups.realpower": _num(status.get("power_watts")),
        "input.voltage": _num(status.get("line_volts")),
        "input.frequency": _num(status.get("line_freq_hz")),
        "output.voltage": _num(status.get("output_volts")),
    }
    return {k: v for k, v in out.items() if v is not None}


def _default_status() -> dict[str, Any]:
    from backend.hardware.ups import read_ups_status

    return read_ups_status()


def allowed(ip: str, networks: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0].removeprefix("::ffff:"))
    except ValueError:
        return False
    for net in networks:
        try:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


class Session:
    """One client connection: the commands of upsd's read side."""

    def __init__(self, cfg: dict[str, Any], status: Callable[[], dict[str, Any]]):
        self.cfg = cfg
        self.status = status
        self.user: str | None = None
        self.password: str | None = None
        self.logged_in = False

    def _vars(self) -> dict[str, str]:
        return ups_vars(self.status(), _FSD.is_set())

    def handle(self, line: str) -> tuple[list[str], bool]:
        """The reply lines for one command, and whether to close the connection."""
        parts = line.strip().split()
        if not parts:
            return [], False
        cmd = [p.upper() for p in parts[:2]]
        args = parts[1:]
        if cmd[0] == "VER":
            return [VERSION], False
        if cmd[0] == "NETVER":
            return ["1.3"], False
        if cmd[0] == "HELP":
            return ["Commands: HELP VER NETVER GET LIST USERNAME PASSWORD LOGIN LOGOUT"], False
        if cmd[0] == "STARTTLS":
            return ["ERR FEATURE-NOT-CONFIGURED"], False
        if cmd[0] == "USERNAME":
            if not args:
                return ["ERR INVALID-ARGUMENT"], False
            self.user = args[0]
            return ["OK"], False
        if cmd[0] == "PASSWORD":
            if not args:
                return ["ERR INVALID-ARGUMENT"], False
            self.password = " ".join(args)
            return ["OK"], False
        if cmd[0] == "LOGIN":
            return self._login(args), False
        if cmd[0] == "LOGOUT":
            return ["OK Goodbye"], True
        if cmd[0] in ("FSD", "PRIMARY", "MASTER", "INSTCMD", "SET"):
            return ["ERR ACCESS-DENIED"], False
        if cmd == ["LIST", "UPS"]:
            return ["BEGIN LIST UPS", f'UPS {UPS_NAME} "ZettNAS UPS"', "END LIST UPS"], False
        if cmd[0] == "LIST" and len(args) >= 2 and cmd[1] == "VAR":
            if args[1] != UPS_NAME:
                return ["ERR UNKNOWN-UPS"], False
            values = self._vars()
            if not values:
                return ["ERR DATA-STALE"], False
            body = [f'VAR {UPS_NAME} {k} "{v}"' for k, v in sorted(values.items())]
            return [f"BEGIN LIST VAR {UPS_NAME}", *body, f"END LIST VAR {UPS_NAME}"], False
        if cmd[0] == "GET" and len(args) >= 2:
            return self._get(cmd[1], args[1:]), False
        return ["ERR UNKNOWN-COMMAND"], False

    def _login(self, args: list[str]) -> list[str]:
        if not args or args[0] != UPS_NAME:
            return ["ERR UNKNOWN-UPS"]
        if self.logged_in:
            return ["ERR ALREADY-LOGGED-IN"]
        expected = _password(self.cfg)
        if not (self.user and self.password and expected):
            return ["ERR USERNAME-REQUIRED" if not self.user else "ERR PASSWORD-REQUIRED"]
        ok = hmac.compare_digest(self.user, self.cfg["user"]) & hmac.compare_digest(self.password, expected)
        if not ok:
            return ["ERR ACCESS-DENIED"]
        self.logged_in = True
        with _LOGINS_LOCK:
            _LOGINS.add(id(self))
        return ["OK"]

    def _get(self, what: str, rest: list[str]) -> list[str]:
        if rest[0] != UPS_NAME:
            return ["ERR UNKNOWN-UPS"]
        if what == "NUMLOGINS":
            return [f"NUMLOGINS {UPS_NAME} {logins()}"]
        if what == "UPSDESC":
            return [f'UPSDESC {UPS_NAME} "ZettNAS UPS"']
        if what == "VAR" and len(rest) >= 2:
            values = self._vars()
            if not values:
                return ["ERR DATA-STALE"]
            if rest[1] not in values:
                return ["ERR VAR-NOT-SUPPORTED"]
            return [f'VAR {UPS_NAME} {rest[1]} "{values[rest[1]]}"']
        return ["ERR INVALID-ARGUMENT"]

    def close(self) -> None:
        with _LOGINS_LOCK:
            _LOGINS.discard(id(self))


class NutServer:
    """The TCP listener, on its own event loop in a thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self.port = 0

    def running(self) -> bool:
        return self._server is not None

    async def _client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, cfg: dict[str, Any], status: Callable
    ) -> None:
        peer = (writer.get_extra_info("peername") or ("", 0))[0]
        if not allowed(str(peer), cfg["networks"]):
            writer.close()
            return
        session = Session(cfg, status)
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=600)
                if not line:
                    break
                replies, close = await asyncio.to_thread(session.handle, line.decode("utf-8", errors="replace")[:512])
                for r in replies:
                    writer.write((r + "\n").encode("utf-8"))
                await writer.drain()
                if close:
                    break
        except (TimeoutError, ConnectionError, OSError):
            pass
        finally:
            session.close()
            writer.close()

    def start(
        self,
        cfg: dict[str, Any] | None = None,
        status: Callable[[], dict[str, Any]] = _default_status,
        host: str = "0.0.0.0",
    ) -> int:
        """Starts listening; returns the port. OSError when the port is taken."""
        self.stop()
        cfg = cfg or settings()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, int(cfg["port"])))
        except OSError:
            sock.close()
            raise
        sock.listen(16)
        self.port = sock.getsockname()[1]
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        async def serve() -> None:
            self._server = await asyncio.start_server(lambda r, w: self._client(r, w, cfg, status), sock=sock)
            ready.set()

        def run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(serve())
            loop.run_forever()

        self._loop = loop
        self._thread = threading.Thread(target=run, daemon=True, name="NutServer")
        self._thread.start()
        ready.wait(5)
        logger.info("[NUT] serving the UPS on port %s", self.port)
        return self.port

    def stop(self) -> None:
        loop, server = self._loop, self._server
        if not loop:
            return
        if server is not None:
            loop.call_soon_threadsafe(server.close)
        loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(5)
        self._loop = self._server = self._thread = None


SERVER = NutServer()


def apply() -> dict[str, Any]:
    """Starts or stops the server to match the settings."""
    cfg = settings()
    if not cfg["enabled"]:
        SERVER.stop()
        return public(cfg)
    if not cfg["password"]:
        save_settings()  # a first start makes the monitor password
        cfg = settings()
    try:
        SERVER.start(cfg)
    except OSError as e:
        raise ValueError(f"Port {cfg['port']} is in use (is a NUT server already running on the host?): {e}") from None
    return public(cfg)


def start_if_enabled() -> None:
    """At startup: serve the UPS when it is turned on; a taken port is logged, not fatal."""
    try:
        apply()
    except ValueError as e:
        logger.warning("[NUT] not started: %s", e)


def forced_shutdown(
    wait: float = FSD_WAIT_SECS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Raises FSD so the PCs watching this UPS shut down, and waits until they have logged out
    (or the time is up). Returns how many were still connected at the end."""
    _FSD.set()
    if not SERVER.running():
        return 0
    end = clock() + wait
    while logins() and clock() < end:
        sleep(0.5)
    left = logins()
    logger.warning("[NUT] forced shutdown sent; %d PC(s) still connected", left)
    return left


def clear_fsd() -> None:
    _FSD.clear()
