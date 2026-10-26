"""Persistent QMP engine against a fake QEMU monitor on a real UNIX socket."""

import json
import os
import socket
import tempfile
import threading
import time

import pytest

from backend.services.vm_engine import QmpEngine


class FakeQemu:
    """Speaks enough QMP: greeting, qmp_capabilities, a few commands, events on demand.

    Like QEMU, it serves one client at a time.
    """

    def __init__(self, path, slow_cmds=(), pre_cap_event=False):
        self.path = path
        self.slow_cmds = set(slow_cmds)
        self.pre_cap_event = pre_cap_event
        self.connections = 0
        self.commands = []
        self.conn = None
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(1)
        self.alive = True
        threading.Thread(target=self._serve, daemon=True).start()

    def _send(self, obj):
        self.conn.sendall(json.dumps(obj).encode() + b"\n")

    def emit(self, event, data=None):
        self._send({"event": event, "data": data or {}, "timestamp": {"seconds": 0, "microseconds": 0}})

    def _serve(self):
        while self.alive:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.conn = conn
            self.connections += 1
            f = conn.makefile("rb")
            self._send({"QMP": {"version": {"qemu": {"major": 9}}, "capabilities": []}})
            try:
                for raw in f:
                    req = json.loads(raw)
                    cmd = req.get("execute")
                    self.commands.append((cmd, req.get("arguments")))
                    if cmd == "qmp_capabilities" and self.pre_cap_event:
                        self.emit("RESUME")
                    if cmd in self.slow_cmds:
                        threading.Timer(0.3, self._send, args=({"return": {"cmd": cmd}, "id": req["id"]},)).start()
                        continue
                    if cmd == "query-status":
                        self._send({"return": {"status": "running", "running": True}, "id": req["id"]})
                    elif cmd == "bogus":
                        self._send({"error": {"class": "CommandNotFound", "desc": "bogus"}, "id": req["id"]})
                    elif cmd == "hang":
                        pass
                    else:
                        self._send({"return": {}, "id": req["id"]})
            except (OSError, ValueError):
                pass
            finally:
                conn.close()

    def drop_client(self):
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def close(self):
        self.alive = False
        self.drop_client()
        self.srv.close()


@pytest.fixture
def env():
    d = tempfile.mkdtemp(prefix="qmp")
    events = []
    engine = QmpEngine(
        lambda vm_id: os.path.join(d, f"{vm_id}.sock"), on_event=lambda v, e, data: events.append((v, e, data))
    )
    servers = []

    def start(vm_id="vm1", **kw):
        srv = FakeQemu(os.path.join(d, f"{vm_id}.sock"), **kw)
        servers.append(srv)
        return srv

    yield engine, start, events
    for s in servers:
        s.close()
    for vm in list(engine._clients):
        engine.close(vm)


def _wait(cond, secs=10.0):  # returns as soon as cond holds; generous for a loaded CI box
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_missing_socket_returns_legacy_error(env):
    engine, _, _ = env
    assert "not found" in engine.execute("nope", "query-status")["error"]


def test_commands_reuse_one_connection(env):
    engine, start, _ = env
    qemu = start()
    for _ in range(5):
        assert engine.execute("vm1", "query-status")["return"]["status"] == "running"
    assert qemu.connections == 1
    assert [c for c, _ in qemu.commands].count("qmp_capabilities") == 1


def test_arguments_and_errors_pass_through(env):
    engine, start, _ = env
    qemu = start()
    assert engine.execute("vm1", "human-monitor-command", {"command-line": "savevm s1"}, timeout=5) == {"return": {}}
    assert qemu.commands[-1] == ("human-monitor-command", {"command-line": "savevm s1"})
    assert engine.execute("vm1", "bogus")["error"]["class"] == "CommandNotFound"


def test_concurrent_commands_get_their_own_replies(env):
    engine, start, _ = env
    start(slow_cmds={"slow"})
    results = {}

    def call(name):
        results[name] = engine.execute("vm1", name, timeout=3)

    threads = [threading.Thread(target=call, args=(n,)) for n in ("slow", "query-status")]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results["slow"] == {"return": {"cmd": "slow"}}
    assert results["query-status"]["return"]["status"] == "running"


def test_events_reach_callback_including_before_capabilities(env):
    engine, start, events = env
    qemu = start(pre_cap_event=True)
    engine.execute("vm1", "query-status")
    qemu.emit("GUEST_PANICKED", {"action": "pause"})
    assert _wait(lambda: any(e == "GUEST_PANICKED" for _, e, _ in events))
    assert ("vm1", "RESUME", {}) in events
    assert ("vm1", "GUEST_PANICKED", {"action": "pause"}) in events


def test_timeout_returns_error_and_connection_survives(env):
    engine, start, _ = env
    qemu = start()
    res = engine.execute("vm1", "hang", timeout=0.2)
    assert "timed out" in res["error"]
    assert engine.execute("vm1", "query-status")["return"]["running"] is True
    assert qemu.connections == 1


def test_reconnects_after_qemu_drops_connection(env):
    engine, start, _ = env
    qemu = start()
    engine.execute("vm1", "query-status")
    qemu.drop_client()
    assert _wait(lambda: not engine.is_connected("vm1"))
    assert engine.execute("vm1", "query-status")["return"]["running"] is True
    assert qemu.connections == 2


def test_watch_connects_once_socket_appears(env):
    engine, start, events = env
    engine.watch("vm2", attempts=200, interval=0.05)  # stops once connected; 10 s for a loaded CI box
    time.sleep(0.2)
    qemu = start("vm2")
    assert _wait(lambda: engine.is_connected("vm2"))
    qemu.emit("SHUTDOWN", {"guest": True, "reason": "guest-shutdown"})
    assert _wait(lambda: any(e == "SHUTDOWN" for _, e, _ in events))


def test_close_releases_the_monitor_for_others(env):
    engine, start, _ = env
    qemu = start()
    engine.execute("vm1", "query-status")
    engine.close("vm1")
    assert not engine.is_connected("vm1")
    # QEMU serves one client at a time; after close a fresh client gets in.
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    s.connect(qemu.path)
    assert b"QMP" in s.recv(4096)
    s.close()
