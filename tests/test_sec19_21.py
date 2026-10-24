"""SEC-19 / SEC-20 / SEC-21."""

from types import SimpleNamespace

from backend import config
from backend.api import auth as auth_api
from backend.auth import client_ip


def test_login_user_list_is_opt_in(client, monkeypatch):
    monkeypatch.setattr(config, "LOGIN_USER_CHOOSER", False)
    assert client.get("/api/auth/users-list").json() == []
    monkeypatch.setattr(config, "LOGIN_USER_CHOOSER", True)
    tiles = client.get("/api/auth/users-list").json()
    assert tiles and set(tiles[0]) == {"username", "display_name", "avatar_url"}


def test_client_ip_ignores_spoofed_forwarded_for(monkeypatch):
    trusted = {"10.0.0.2"}
    monkeypatch.setattr("backend.auth.is_ip_in_trusted_proxies", lambda ip, trusted_list=None: ip in trusted)

    def req(peer, xff):
        return SimpleNamespace(client=SimpleNamespace(host=peer), headers={"x-forwarded-for": xff})

    assert client_ip(req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"  # untrusted peer: header ignored
    assert client_ip(req("10.0.0.2", "1.2.3.4, 198.51.100.7")) == "198.51.100.7"  # rightmost untrusted hop


def test_failed_logins_lock_per_user_and_ip_and_survive_restart(client, monkeypatch):
    for _ in range(auth_api._FREE_ATTEMPTS_USER + 1):
        client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    locked = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert locked.status_code == 429
    key = next(k for k in auth_api._failures if k.startswith("user:admin@"))
    # persisted: a fresh process sees the same lock
    saved = dict(auth_api._failures)
    auth_api._failures.clear()
    auth_api._load_failures()
    assert key in auth_api._failures
    # another address is not locked out of the admin account
    monkeypatch.setattr(auth_api, "_client_ip", lambda request: "198.51.100.77")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 200
    for k in saved:
        auth_api._clear_failures(k)


def test_share_links_work_without_a_session_and_ask_for_the_password(client, auth_headers, tmp_path, monkeypatch):
    from unittest.mock import patch

    root = tmp_path / "user"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    with patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)]):
        res = client.post(
            "/api/fs/share-links", json={"path": str(root / "a.txt"), "password": "Secret12345"}, headers=auth_headers
        )
        assert res.status_code == 200, res.text
        token = res.json()["token"]
        client.cookies.clear()
        page = client.get(f"/api/fs/shared/{token}", headers={"Accept": "text/html"})
        assert page.status_code == 401 and "<form" in page.text
        assert client.get(f"/api/fs/shared/{token}?pwd=Secret12345").status_code == 401  # never from the URL
        ok = client.post(f"/api/fs/shared/{token}", data={"password": "Secret12345"})
        assert ok.status_code == 200 and ok.content == b"hello"
