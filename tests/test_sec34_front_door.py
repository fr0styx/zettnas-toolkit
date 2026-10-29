"""SEC-34: WebDAV and SFTP reach rclone through ZettNAS, so IP blocks, failed sign-ins and the
ransomware guard apply on the WebDAV and SFTP ports as on the web app."""

import asyncio
import base64
import json
import os
import socket
import subprocess
import sys

import httpx
import pytest
from starlette.testclient import TestClient

from backend.services import ip_block, sftp_engine, sftp_front, webdav_engine, webdav_front

CLIENT = ("203.0.113.9", 50000)
BASIC = {"authorization": "Basic " + base64.b64encode(b"anna:wrong").decode()}


@pytest.fixture
def blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(ip_block, "STORE", str(tmp_path / "ip_blocks.json"))
    monkeypatch.setattr(ip_block, "_sync_samba", lambda: None)
    ip_block._reset_for_tests()
    yield
    ip_block._reset_for_tests()


@pytest.fixture
def rclone(monkeypatch):
    """rclone's side: records what reached it and answers like it."""
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("authorization", "").endswith(base64.b64encode(b"anna:wrong").decode()):
            return httpx.Response(401, headers={"www-authenticate": 'Basic realm="rclone"'})
        return httpx.Response(207, content=b"<multistatus/>", headers={"content-type": "application/xml"})

    monkeypatch.setattr(webdav_front, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    return seen


def test_rclone_listens_behind_the_public_ports():
    assert webdav_front.internal_port(8084) == 18084
    assert webdav_front.internal_port(60000) == 50000
    assert sftp_front.internal_port(2222) == 12222
    cmd = sftp_front.rclone_command(12222, "/tmp/cache")
    assert cmd[cmd.index("--addr") + 1] == "127.0.0.1:12222"
    # run by Python: the script has no execute bit in the image
    assert cmd[cmd.index("--auth-proxy") + 1] == f"{sys.executable} {sftp_front.SCRIPT_DIR}/rclone_auth_proxy.py"


def test_the_webdav_port_refuses_blocked_addresses(blocks, rclone):
    ip_block.block(CLIENT[0], "test")
    client = TestClient(webdav_front.front_app(18084, webdav_engine.gate()), client=CLIENT)
    r = client.request("PROPFIND", "/photos/", headers={"depth": "1"})
    assert r.status_code == 403 and not rclone


def test_the_webdav_port_forwards_as_sent_and_counts_failed_sign_ins(blocks, rclone, monkeypatch):
    failures = []
    monkeypatch.setattr(ip_block, "record_auth_failure", lambda ip, service="web": failures.append((ip, service)))
    client = TestClient(webdav_front.front_app(18084, webdav_engine.gate()), client=CLIENT)
    r = client.request("PROPFIND", "/photos/", headers={"depth": "1", "host": "nas.local:8084"})
    assert r.status_code == 207 and r.content == b"<multistatus/>"
    sent = rclone[-1]
    # rclone compares a MOVE's Destination with the Host, so both reach it as the client sent them
    assert str(sent.url) == "http://127.0.0.1:18084/photos/" and sent.headers["host"] == "nas.local:8084"
    assert not failures
    assert client.request("PROPFIND", "/", headers=BASIC).status_code == 401
    assert failures == [(CLIENT[0], "WebDAV")]


def test_twenty_failed_webdav_sign_ins_block_the_address(blocks, rclone):
    client = TestClient(webdav_front.front_app(18084, webdav_engine.gate()), client=CLIENT)
    for _ in range(ip_block.FAIL_LIMIT):
        client.request("PROPFIND", "/", headers=BASIC)
    assert ip_block.is_blocked(CLIENT[0])
    assert client.request("PROPFIND", "/", headers={"depth": "0"}).status_code == 403


def test_writes_on_the_webdav_port_reach_the_ransomware_guard(blocks, rclone, monkeypatch):
    seen = []

    class Guard:
        def observe(self, kind, path, user="", ip="", new_path=""):
            seen.append((kind, path, user, ip, new_path))

    monkeypatch.setattr("backend.services.ransomware_guard.get_guard", lambda: Guard())
    client = TestClient(webdav_front.front_app(18084, webdav_engine.gate()), client=CLIENT)
    auth = {"authorization": "Basic " + base64.b64encode(b"anna:right").decode()}
    client.request("MOVE", "/docs/a.txt", headers={**auth, "destination": "http://nas.local:8084/docs/b%20c.txt"})
    assert seen == [("rename", "docs/a.txt", "anna", CLIENT[0], "docs/b c.txt")]
    assert rclone[-1].headers["destination"] == "http://nas.local:8084/docs/b%20c.txt"


def test_the_web_apps_webdav_path_moves_paths_to_the_root(blocks, rclone):
    from starlette.applications import Starlette
    from starlette.routing import Route

    async def endpoint(request):
        return await webdav_front.forward(
            request, request.path_params["path"], 18084, webdav_engine.gate(), prefix="/webdav"
        )

    app = Starlette(routes=[Route("/webdav/{path:path}", endpoint, methods=webdav_front.METHODS)])
    client = TestClient(app, client=CLIENT)
    client.request("COPY", "/webdav/a.txt", headers={"destination": "http://nas.local:8082/webdav/b.txt"})
    sent = rclone[-1]
    assert str(sent.url) == "http://127.0.0.1:18084/a.txt"
    assert sent.headers["destination"] == "http://127.0.0.1:18084/b.txt"
    assert sent.headers["host"] == "127.0.0.1:18084"


def test_a_stopped_rclone_is_a_502(blocks, monkeypatch):
    def down(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(webdav_front, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(down)))
    client = TestClient(webdav_front.front_app(18084, webdav_engine.gate()), client=CLIENT)
    assert client.request("PROPFIND", "/").status_code == 502


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_front_answers_on_the_port_and_stops(blocks, rclone):
    front = webdav_front.Front()
    port = _free_port()
    front.start(port, 18084, webdav_engine.gate(), host="127.0.0.1")
    try:
        assert front.running()
        r = httpx.request("PROPFIND", f"http://127.0.0.1:{port}/x/", timeout=5)
        assert r.status_code == 207
    finally:
        front.stop()
    assert not front.running()


def test_a_port_in_use_is_an_error_at_start():
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        with pytest.raises(OSError):
            webdav_front.Front().start(taken.getsockname()[1], 18084, webdav_engine.gate(), host="127.0.0.1")


def test_the_engine_starts_rclone_on_loopback_and_the_front_on_the_port(tmp_path, monkeypatch):
    from backend import config

    cfg = tmp_path / "webdav.json"
    cfg.write_text(json.dumps({"enabled": True, "port": 8084, "root_path": str(tmp_path)}))
    monkeypatch.setattr(config, "WEBDAV_CONFIG_FILE", str(cfg))
    monkeypatch.setattr(webdav_engine.WebdavEngine, "safe_root", staticmethod(lambda root: str(tmp_path)))
    monkeypatch.setattr(webdav_engine.shutil, "which", lambda name: "/usr/bin/rclone")
    monkeypatch.setattr(webdav_engine.time, "sleep", lambda s: None)
    launched = []

    class Proc:
        pid = 4242
        returncode = None

        def __init__(self, cmd, **kw):
            launched.append(cmd)

        def poll(self):
            return None

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(webdav_engine.subprocess, "Popen", Proc)
    engine = webdav_engine.WebdavEngine()
    fronts = []
    monkeypatch.setattr(engine._front, "start", lambda public, internal, gate: fronts.append((public, internal)))
    monkeypatch.setattr(engine._front, "stop", lambda: fronts.append("stopped"))
    engine.start()
    cmd = launched[0]
    assert cmd[cmd.index("--addr") + 1] == "127.0.0.1:18084"
    assert cmd[cmd.index("--auth-proxy") + 1].startswith(f"{sys.executable} ")
    assert fronts == [(8084, 18084)] and engine.internal_port() == 18084
    engine.stop()
    assert fronts[-1] == "stopped"


def test_the_engine_gives_up_rclone_when_the_port_is_taken(tmp_path, monkeypatch):
    from backend import config

    cfg = tmp_path / "webdav.json"
    cfg.write_text(json.dumps({"enabled": True, "port": 8084, "root_path": str(tmp_path)}))
    monkeypatch.setattr(config, "WEBDAV_CONFIG_FILE", str(cfg))
    monkeypatch.setattr(webdav_engine.WebdavEngine, "safe_root", staticmethod(lambda root: str(tmp_path)))
    monkeypatch.setattr(webdav_engine.shutil, "which", lambda name: "/usr/bin/rclone")
    monkeypatch.setattr(webdav_engine.time, "sleep", lambda s: None)
    stopped = []

    class Proc:
        pid = 1

        def __init__(self, cmd, **kw):
            pass

        def poll(self):
            return None

        def terminate(self):
            stopped.append(True)

    monkeypatch.setattr(webdav_engine.subprocess, "Popen", Proc)
    engine = webdav_engine.WebdavEngine()

    def taken(public, internal, gate):
        raise OSError("Address already in use")

    monkeypatch.setattr(engine._front, "start", taken)
    status = engine.start()
    assert stopped == [True] and not status["running"] and "8084" in status["last_error"]


async def _echo_server():
    async def echo(reader, writer):
        while data := await reader.read(1024):
            writer.write(data)
            await writer.drain()
        writer.close()

    return await asyncio.start_server(echo, "127.0.0.1", 0)


def test_the_sftp_port_passes_bytes_on_and_closes_blocked_addresses():
    async def run():
        upstream = await _echo_server()
        internal = upstream.sockets[0].getsockname()[1]
        refused = {"on": False}
        front = await sftp_front.serve(0, internal, lambda ip: refused["on"] and ip == "127.0.0.1", host="127.0.0.1")
        port = front.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"SSH-2.0-test\r\n")
        await writer.drain()
        assert await reader.readexactly(14) == b"SSH-2.0-test\r\n"
        writer.close()
        refused["on"] = True
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        assert await asyncio.wait_for(reader.read(10), 5) == b""
        writer.close()
        front.close()
        upstream.close()

    asyncio.run(run())


def test_a_connection_is_closed_when_rclone_is_not_there():
    async def run():
        front = await sftp_front.serve(0, _free_port(), lambda ip: False, host="127.0.0.1")
        port = front.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        assert await asyncio.wait_for(reader.read(10), 5) == b""
        writer.close()
        front.close()

    asyncio.run(run())


def test_the_sftp_front_stops_rclone_when_it_is_stopped(tmp_path, monkeypatch):
    """The whole script, with a stand-in for rclone that just waits."""
    port = _free_port()
    fake = tmp_path / "rclone"
    fake.write_text("#!/bin/sh\nexec sleep 60\n")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "DATA_DIR": str(tmp_path / "data")}
    proc = subprocess.Popen([sys.executable, sftp_front.__file__, str(port), str(tmp_path / "cache")], env=env)
    try:
        for _ in range(100):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            asyncio.run(asyncio.sleep(0.05))
        proc.terminate()
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_the_sftp_front_explains_its_arguments(capsys):
    assert sftp_front.main([]) == 2
    assert "sftp_front.py <port>" in capsys.readouterr().err


def test_an_old_sidecar_is_recreated_with_the_front(monkeypatch):
    calls = []

    def docker(method, path, body=None, **kw):
        calls.append((method, path, body))
        if path == "/containers/zettnas-sftp/json":
            return 200, {"State": {"Running": True}, "Config": {"Cmd": ["rclone", "serve", "sftp", "--addr", ":2222"]}}
        if path == "/containers/zettnas-toolkit/json":
            return 200, {"Config": {"Image": "zettnas:test"}, "HostConfig": {"Binds": []}}
        if path.endswith("/start"):
            return 204, {}
        return 201, {}

    monkeypatch.setattr("backend.services.container_mutator._docker_request", docker)
    monkeypatch.setattr(sftp_engine, "docker_sock", lambda: __file__)
    assert sftp_engine.get_sftp_engine()._start_sidecar(2222)
    assert ("DELETE", "/containers/zettnas-sftp?force=true", None) in calls
    created = next(body for method, path, body in calls if path.startswith("/containers/create"))
    assert created["Cmd"] == ["python3", "/app/backend/services/sftp_front.py", "2222", "/app/data/sftp/cache"]


def test_a_current_sidecar_is_kept(monkeypatch):
    calls = []

    def docker(method, path, body=None, **kw):
        calls.append((method, path))
        return 200, {"State": {"Running": True}, "Config": {"Cmd": sftp_engine._front_cmd(2222)}}

    monkeypatch.setattr("backend.services.container_mutator._docker_request", docker)
    monkeypatch.setattr(sftp_engine, "docker_sock", lambda: __file__)
    assert sftp_engine.get_sftp_engine()._start_sidecar(2222)
    assert calls == [("GET", "/containers/zettnas-sftp/json")]


def test_the_fallback_process_runs_the_front(monkeypatch):
    launched = []
    monkeypatch.setattr(
        sftp_engine.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd) or type("P", (), {"pid": 7})()
    )
    assert sftp_engine.get_sftp_engine()._start_subprocess(2222)
    assert launched[0][1:3] == [sftp_engine.FRONT_SCRIPT, "2222"]


def test_blocks_written_by_another_process_are_seen(blocks):
    assert not ip_block.is_blocked(CLIENT[0])
    with open(ip_block.STORE, "w") as f:
        json.dump({CLIENT[0]: {"reason": "web sign-ins", "since": 0, "until": None}}, f)
    os.utime(ip_block.STORE, ns=(1, 1))  # a different time than the last read, whatever the clock
    assert ip_block.is_blocked(CLIENT[0])


def test_the_sftp_front_ends_with_rclone(blocks):
    class Rclone:
        returncode = 3
        polls = 0

        def poll(self):
            self.polls += 1
            return None if self.polls < 2 else 3

    assert asyncio.run(sftp_front._run(_free_port(), _free_port(), Rclone())) == 3


def test_the_sftp_front_stops_a_killed_rclone_as_a_failure(blocks, tmp_path, monkeypatch):
    class Rclone:
        returncode = -9

        def poll(self):
            return -9

    monkeypatch.setattr(sftp_front.subprocess, "Popen", lambda cmd: Rclone())
    assert sftp_front.main([str(_free_port()), str(tmp_path / "cache")]) == 1
