"""Cloud sign-in for remotes (rclone authorize): starting a session, handing the provider's
code to rclone, and keeping the access and refresh tokens on the server."""

import time

import pytest

from backend.api import remotes as remotes_api

TOKEN = '{"access_token":"ya29.secret","refresh_token":"1//refresh","expiry":"2026-10-24T18:00:00Z"}'


class FakeProc:
    def __init__(self, lines=(), exit_code=None, out=TOKEN, err=""):
        self.lines = list(lines)
        self.exit_code = exit_code
        self.out, self.err = out, err
        self.killed = False
        self.stderr = self

    def readline(self):
        return self.lines.pop(0) if self.lines else ""

    def poll(self):
        return self.exit_code

    def communicate(self, timeout=None):
        return self.out, self.err

    def kill(self):
        self.killed = True


@pytest.fixture
def sessions(monkeypatch):
    remotes_api._ACTIVE_OAUTH_SESSIONS.clear()
    forwarded = []
    monkeypatch.setattr(remotes_api.urllib.request, "urlopen", lambda url, timeout=5: forwarded.append(url))

    async def no_wait(s):
        return None

    monkeypatch.setattr(remotes_api.asyncio, "sleep", no_wait)
    yield forwarded
    remotes_api._ACTIVE_OAUTH_SESSIONS.clear()


def _session(sid="zos_abc", state="st4te", **extra):
    data = {
        "proc": None,
        "provider_type": "drive",
        "port": 53682,
        "state": state,
        "started_at": time.time(),
        "token": None,
        "error": None,
        "completed": False,
    }
    data.update(extra)
    remotes_api._ACTIVE_OAUTH_SESSIONS[sid] = data
    return data


def test_exchange_hands_the_code_to_rclone_and_keeps_the_token(client, auth_headers, sessions):
    _session(token=TOKEN, completed=True)
    r = client.post(
        "/api/remotes/oauth/exchange",
        json={"session_id": "zos_abc", "redirect_url": "http://127.0.0.1:53682/?code=4%2Fabc&state=st4te"},
        headers=auth_headers,
    )
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert body["token"] == "********oauth_ref:zos_abc"
    assert "secret" not in r.text and "refresh" not in r.text
    assert sessions == ["http://127.0.0.1:53682/?code=4/abc&state=st4te"]


def test_the_phone_route_needs_no_sign_in_and_returns_no_token(client, sessions):
    _session(token=TOKEN, completed=True)
    r = client.post(
        "/api/remotes/oauth/mobile-exchange",
        json={"session_id": "zos_abc", "redirect_url": "http://localhost:53682/?state=st4te&code=xyz"},
    )
    assert r.status_code == 200 and r.json() == {"status": "ok", "session_id": "zos_abc"}
    assert "oauth_ref" not in r.text and "secret" not in r.text


def test_the_phone_route_refuses_a_bare_code(client, sessions):
    _session(token=TOKEN, completed=True)
    r = client.post(
        "/api/remotes/oauth/mobile-exchange", json={"session_id": "zos_abc", "redirect_url": "4/attacker-code"}
    )
    assert r.status_code == 400 and sessions == []
    r = client.post("/api/remotes/oauth/mobile-exchange", json={"session_id": "zos_abc", "redirect_url": "code=x"})
    assert r.status_code == 400 and sessions == []


def test_a_bare_code_still_works_when_signed_in(client, auth_headers, sessions):
    _session(token=TOKEN, completed=True)
    r = client.post(
        "/api/remotes/oauth/exchange", json={"session_id": "zos_abc", "redirect_url": "4/plain"}, headers=auth_headers
    )
    assert r.status_code == 200 and sessions[-1].endswith("code=4/plain&state=st4te")


@pytest.mark.parametrize(
    ("redirect", "code"),
    [
        ("http://127.0.0.1:53682/?code=x&state=wrong", 400),  # state mismatch
        ("http://127.0.0.1:53682/?state=st4te", 400),  # no code
    ],
)
def test_exchange_refusals(client, auth_headers, sessions, redirect, code):
    _session(token=TOKEN, completed=True)
    r = client.post(
        "/api/remotes/oauth/exchange", json={"session_id": "zos_abc", "redirect_url": redirect}, headers=auth_headers
    )
    assert r.status_code == code and sessions == []


def test_exchange_unknown_session_error_and_timeout(client, auth_headers, sessions):
    url = "http://127.0.0.1:53682/?code=x&state=st4te"
    r = client.post(
        "/api/remotes/oauth/exchange", json={"session_id": "zos_none", "redirect_url": url}, headers=auth_headers
    )
    assert r.status_code == 404
    _session(error="access_denied")
    r = client.post(
        "/api/remotes/oauth/exchange", json={"session_id": "zos_abc", "redirect_url": url}, headers=auth_headers
    )
    assert r.status_code == 400
    _session()
    r = client.post(
        "/api/remotes/oauth/exchange", json={"session_id": "zos_abc", "redirect_url": url}, headers=auth_headers
    )
    assert r.status_code == 504


def test_status_masks_the_token_and_saving_swaps_it_back(client, auth_headers, sessions):
    _session(token=TOKEN, completed=True)
    st = client.get("/api/remotes/oauth/status/zos_abc", headers=auth_headers).json()
    assert st["completed"] is True and st["token"] == "********oauth_ref:zos_abc" and st["has_token"] is True
    params = remotes_api._resolve_masked_oauth_parameters("drive", {"token": st["token"], "scope": "drive"})
    assert params == {"token": TOKEN, "scope": "drive"}
    # a stale reference falls back to the latest finished sign-in for the same provider
    assert remotes_api._resolve_masked_oauth_parameters("drive", {"token": "********"})["token"] == TOKEN
    assert remotes_api._resolve_masked_oauth_parameters("onedrive", {"token": "********"})["token"] == "********"
    assert remotes_api._resolve_masked_oauth_parameters("drive", {"token": "plain"})["token"] == "plain"
    assert client.get("/api/remotes/oauth/status/zos_none", headers=auth_headers).status_code == 404


def test_cancel_stops_rclone(client, auth_headers, sessions):
    proc = FakeProc()
    _session(proc=proc)
    assert client.delete("/api/remotes/oauth/zos_abc", headers=auth_headers).json() == {"status": "ok"}
    assert proc.killed and "zos_abc" not in remotes_api._ACTIVE_OAUTH_SESSIONS
    assert client.delete("/api/remotes/oauth/zos_abc", headers=auth_headers).status_code == 200


def test_old_sessions_are_cleaned_up(sessions):
    old = FakeProc()
    _session("zos_old", proc=old, started_at=time.time() - 3600)
    _session("zos_new")
    remotes_api._cleanup_old_oauth_sessions()
    assert list(remotes_api._ACTIVE_OAUTH_SESSIONS) == ["zos_new"] and old.killed
    remotes_api._cleanup_old_oauth_sessions(force_all=True)
    assert remotes_api._ACTIVE_OAUTH_SESSIONS == {}


@pytest.fixture
def fake_rclone(monkeypatch, tmp_path):
    binary = tmp_path / "rclone"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(remotes_api.shutil, "which", lambda n: str(binary))
    monkeypatch.setattr(remotes_api.subprocess, "run", lambda *a, **k: None)
    started = {}

    def popen(cmd, **kw):
        started["cmd"] = cmd
        return started["proc"]

    monkeypatch.setattr(remotes_api.subprocess, "Popen", popen)
    return started


def test_start_captures_the_login_address(client, auth_headers, sessions, fake_rclone, monkeypatch):
    fake_rclone["proc"] = FakeProc(
        lines=["NOTICE: Waiting for code...\n", "Please go to http://127.0.0.1:53682/auth?state=Ab-9_x\n"]
    )
    monkeypatch.setattr(
        remotes_api.urllib.request, "build_opener", lambda *h: type("O", (), {"open": lambda self, u: None})()
    )
    r = client.post(
        "/api/remotes/oauth/start",
        json={"provider_type": "drive", "client_id": "cid", "client_secret": "cs"},
        headers=auth_headers,
    )
    body = r.json()
    assert r.status_code == 200 and body["redirect_port"] == 53682
    assert body["auth_url"] == "http://127.0.0.1:53682/auth?state=Ab-9_x"  # no provider redirect found
    assert fake_rclone["cmd"][1:] == ["authorize", "--auth-no-open-browser", "--", "drive", "cid", "cs"]
    sid = body["session_id"]
    for _ in range(50):  # the reader thread stores the token
        if remotes_api._ACTIVE_OAUTH_SESSIONS[sid]["completed"]:
            break
        time.sleep(0.02)
    assert remotes_api._ACTIVE_OAUTH_SESSIONS[sid]["token"] == TOKEN
    assert remotes_api._ACTIVE_OAUTH_SESSIONS[sid]["state"] == "Ab-9_x"


def test_start_fails_cleanly(client, auth_headers, sessions, fake_rclone):
    fake_rclone["proc"] = FakeProc(exit_code=1, err="unknown backend")
    r = client.post("/api/remotes/oauth/start", json={"provider_type": "nope"}, headers=auth_headers)
    assert r.status_code == 500 and remotes_api._ACTIVE_OAUTH_SESSIONS == {}


def test_start_keeps_values_out_of_rclone_options(client, auth_headers, sessions, fake_rclone):
    fake_rclone["proc"] = FakeProc(exit_code=1)
    assert (
        client.post("/api/remotes/oauth/start", json={"provider_type": "--config"}, headers=auth_headers).status_code
        == 422
    )
    client.post(
        "/api/remotes/oauth/start",
        json={"provider_type": "drive", "client_id": "--log-file=/etc/x", "client_secret": "s"},
        headers=auth_headers,
    )
    cmd = fake_rclone["cmd"]
    assert cmd.index("--") < cmd.index("--log-file=/etc/x")
