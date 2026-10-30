"""NSEC-15: failed SFTP sign-ins count against the address they came from."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from backend.services import ip_block
from backend.services import sftp_front as sf

PROXY = Path(__file__).resolve().parents[1] / "backend" / "services" / "rclone_auth_proxy.py"


def test_a_failure_goes_to_the_one_address_signing_in():
    s = sf.SignIns()
    a = s.opened("203.0.113.9", now=100)
    assert s.who(105) == "203.0.113.9"
    assert s.who(100 + sf.AUTH_WINDOW_S + 5) == ""  # long past its sign-in
    s.closed(a, now=106)
    assert s.who(110) == ""  # it had gone
    s.opened("203.0.113.9", now=200)
    s.opened("198.51.100.4", now=201)
    assert s.who(202) == ""  # two at once: nobody is counted
    s.prune(now=10_000)
    assert s.conns == []


def test_failures_are_read_once_and_counted(tmp_path):
    log = tmp_path / "auth-failures.log"
    log.write_text(json.dumps({"ts": 105.0}) + "\n" + "junk\n" + json.dumps({"ts": 106.0}) + "\n")
    s = sf.SignIns()
    s.opened("203.0.113.9", now=100)
    counted = []
    assert sf.count_failures(str(log), s, lambda ip, svc: counted.append((ip, svc))) == 2
    assert counted == [("203.0.113.9", "SFTP")] * 2
    assert not log.exists() and not (tmp_path / "auth-failures.log.reading").exists()
    assert sf.take_failures(str(log)) == []


def test_enough_failures_block_the_address(tmp_path, monkeypatch):
    monkeypatch.setattr(ip_block, "_trusted", lambda ip: False)
    monkeypatch.setattr(ip_block, "_relay", lambda ip: False)
    blocked = []
    monkeypatch.setattr(ip_block, "block", lambda ip, why: blocked.append((ip, why)) or True)
    ip_block._reset_for_tests()
    log = tmp_path / "f.log"
    s = sf.SignIns()
    s.opened("203.0.113.9", now=__import__("time").time())
    for _ in range(ip_block.FAIL_LIMIT):
        log.write_text(json.dumps({"ts": __import__("time").time()}) + "\n")
        sf.count_failures(str(log), s, ip_block.record_auth_failure)
    assert blocked and blocked[0][0] == "203.0.113.9" and "SFTP" in blocked[0][1]


def test_the_proxy_writes_failures_only_for_sftp(tmp_path, monkeypatch):
    from backend import config
    from backend.users_db import init_users_db

    init_users_db()
    log = tmp_path / "f.log"
    env = {
        "PATH": "/usr/bin:/bin",
        "TESTING": "1",
        "DATA_DIR": str(tmp_path),
        "USERS_DB_PATH": config.USERS_DB_PATH,
        "ZETTNAS_AUTH_FAIL_LOG": str(log),
    }
    req = json.dumps({"user": "nobody", "pass": "wrong"})
    r = subprocess.run([sys.executable, str(PROXY)], input=req, capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 1
    assert json.loads(log.read_text().splitlines()[0])["ts"] > 0
    env.pop("ZETTNAS_AUTH_FAIL_LOG")
    log.unlink()
    subprocess.run([sys.executable, str(PROXY)], input=req, capture_output=True, text=True, env=env, timeout=60)
    assert not log.exists()  # WebDAV's rclone has no log: its own front counts by address


def test_the_front_tracks_each_connection():
    async def go():
        async def upstream(reader, writer):
            writer.write(b"hi")
            await writer.drain()
            writer.close()

        up = await asyncio.start_server(upstream, "127.0.0.1", 0)
        internal = up.sockets[0].getsockname()[1]
        s = sf.SignIns()
        front = await sf.serve(0, internal, lambda ip: False, host="127.0.0.1", sign_ins=s)
        port = front.sockets[0].getsockname()[1]
        r, w = await asyncio.open_connection("127.0.0.1", port)
        assert await r.read(2) == b"hi"
        w.close()
        await asyncio.sleep(0.2)
        front.close()
        up.close()
        return s

    s = asyncio.run(go())
    assert len(s.conns) == 1 and s.conns[0][0] == "127.0.0.1" and s.conns[0][2] is not None


def test_main_gives_rclone_the_log(monkeypatch, tmp_path):
    seen = {}

    class Proc:
        def poll(self):
            return 0

    monkeypatch.setattr(sf.subprocess, "Popen", lambda cmd, env=None: seen.update(env=env) or Proc())
    monkeypatch.setattr(sf, "rclone_command", lambda internal, cache: ["rclone"])
    monkeypatch.setattr(sf, "internal_port", lambda p: 1)
    monkeypatch.setattr(sf.asyncio, "run", lambda coro: coro.close() or 0)
    assert sf.main(["2222", str(tmp_path)]) == 0
    assert seen["env"][sf.FAIL_LOG_ENV] == str(tmp_path / "auth-failures.log")


def _run_proxy(monkeypatch, user, password):
    import io

    import pytest

    from backend.services import rclone_auth_proxy as rap

    monkeypatch.setattr(rap.sys, "stdin", io.StringIO(json.dumps({"user": user, "pass": password})))
    with pytest.raises(SystemExit) as out:
        rap.main()
    return out.value.code


def test_proxy_notes_wrong_passwords_and_locked_accounts(tmp_path, monkeypatch):
    from backend.services import login_lockout
    from backend.users_db import init_users_db

    init_users_db()
    log = tmp_path / "f.log"
    monkeypatch.setenv("ZETTNAS_AUTH_FAIL_LOG", str(log))
    assert _run_proxy(monkeypatch, "nobody", "wrong") == 1
    monkeypatch.setattr(login_lockout, "remaining", lambda key: 30)
    assert _run_proxy(monkeypatch, "nobody", "wrong") == 1
    assert len(log.read_text().splitlines()) == 2


def test_proxy_note_never_fails_a_sign_in(tmp_path, monkeypatch):
    from backend.services import rclone_auth_proxy as rap

    monkeypatch.setenv("ZETTNAS_AUTH_FAIL_LOG", str(tmp_path / "missing" / "f.log"))
    rap._note_failure()  # an unwritable log is ignored
    monkeypatch.delenv("ZETTNAS_AUTH_FAIL_LOG")
    rap._note_failure()
