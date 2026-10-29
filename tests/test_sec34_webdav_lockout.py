"""SEC-34: failed WebDAV portal sign-ins count against the account too, the same counter direct
WebDAV and SFTP use, so guessing one account's password locks it wherever it is tried."""

from backend.services import login_lockout


def test_portal_failures_lock_the_account(client, monkeypatch):
    from backend.api import webdav as webdav_api

    monkeypatch.setattr(
        webdav_api, "get_webdav_engine", lambda: type("E", (), {"load_config": lambda self: {"enabled": True}})()
    )
    key = "webdav:kimtest"
    login_lockout.clear(key)
    for _ in range(12):
        client.post("/webdav/auth/login", data={"username": "KimTest", "password": "wrong-password-1"})
        if login_lockout.remaining(key) > 0:
            break
    assert login_lockout.remaining(key) > 0
    r = client.post("/webdav/auth/login", data={"username": "kimtest", "password": "wrong-password-1"})
    assert r.status_code == 429
    login_lockout.clear(key)
