"""SEC-16 / SEC-17 / FE-05: session transport."""

from types import SimpleNamespace

from backend import config
from backend.auth import query_credential_allowed, request_is_https


def _login(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert res.status_code == 200, res.text
    assert "zettnas_session" in res.cookies
    return res.json()["token"]


def test_session_tokens_are_not_accepted_in_urls(client):
    token = _login(client)
    client.cookies.clear()
    assert client.get(f"/api/auth/me?token={token}").status_code == 401
    assert client.get(f"/api/auth/me?ticket={token}").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert query_credential_allowed(token) == ""
    assert query_credential_allowed(config.LCD_INTERNAL_TOKEN) == config.LCD_INTERNAL_TOKEN
    assert query_credential_allowed("zst_abc") == "zst_abc"


def test_cookie_writes_need_a_same_origin_header(client):
    _login(client)  # the test client now holds the session cookie
    host = "testserver"
    blocked = client.post("/api/auth/logout")
    assert blocked.status_code == 403 and blocked.json()["error"] == "csrf_blocked"
    evil = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    ok = client.post("/api/auth/logout", headers={"Origin": f"http://{host}"})
    assert ok.status_code == 200
    # reads are not affected
    _login(client)
    assert client.get("/api/auth/me").status_code == 200


def test_bearer_clients_are_not_csrf_checked(client):
    token = _login(client)
    client.cookies.clear()
    res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200


def test_forwarded_proto_only_from_trusted_proxies(monkeypatch):
    req = SimpleNamespace(
        url=SimpleNamespace(scheme="http"),
        client=SimpleNamespace(host="192.168.1.50"),
        headers={"x-forwarded-proto": "https"},
    )
    monkeypatch.setattr(config, "TRUSTED_PROXIES", [], raising=False)
    monkeypatch.setattr("backend.auth.is_ip_in_trusted_proxies", lambda ip, trusted_list=None: False)
    assert request_is_https(req) is False
    monkeypatch.setattr("backend.auth.is_ip_in_trusted_proxies", lambda ip, trusted_list=None: True)
    assert request_is_https(req) is True
