"""Authentication, sessions, rate limiting, password policy and docs gating."""

import hashlib

from backend import config
from backend.auth import validate_session


def assert_error(r, status, error=None):
    assert r.status_code == status, r.text
    body = r.json()
    assert {"error", "detail", "code"} <= set(body), body
    assert body["code"] == status
    assert isinstance(body["detail"], str) and body["detail"]
    if error:
        assert body["error"] == error, body


def test_health_is_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == __import__("backend").__version__
    assert {"status", "collector_heartbeat_age", "lcd_renderer_active", "fans_released"} <= set(body)


def test_health_v1_alias(client):
    assert client.get("/api/v1/health").status_code == 200


def test_api_requires_auth(client):
    assert_error(client.get("/api/stats"), 401, "unauthorized")


def test_invalid_bearer_rejected(client):
    assert_error(client.get("/api/fans", headers={"Authorization": "Bearer nope"}), 401)


def test_login_success_returns_token(client):
    r = client.post("/api/auth/login", json={"password": "admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"] and body["is_default_password"] is True
    assert validate_session(body["token"])


def test_login_wrong_password(client):
    assert_error(client.post("/api/auth/login", json={"password": "bad"}), 401, "invalid_credentials")


def test_login_missing_body_is_validation_error(client):
    r = client.post("/api/auth/login", json={})
    assert_error(r, 422, "validation_error")
    assert r.json()["errors"][0]["field"] == "password"


def test_bearer_and_query_token_both_work(client, token):
    assert client.get("/api/fans", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get(f"/api/fans?token={token}").status_code == 200


def test_internal_lcd_token_is_accepted(client):
    r = client.get("/api/fans", headers={"Authorization": f"Bearer {config.LCD_INTERNAL_TOKEN}"})
    assert r.status_code == 200


def test_logout_revokes_session(client, token):
    h = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/fans", headers=h).status_code == 401


def test_rate_limit_after_repeated_failures(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"password": "x"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": "x"})
    assert_error(r, 429, "rate_limited")
    assert int(r.headers["Retry-After"]) > 0
    # Even the right password is refused while locked out.
    assert client.post("/api/auth/login", json={"password": "admin"}).status_code == 429


def test_password_change_policy(client, auth_headers):
    short = client.post(
        "/api/security", headers=auth_headers, json={"current_password": "admin", "new_password": "abc"}
    )
    assert_error(short, 400, "weak_password")
    default = client.post(
        "/api/security", headers=auth_headers, json={"current_password": "admin", "new_password": "ADMIN"}
    )
    assert_error(default, 400, "weak_password")


def test_password_change_requires_current_password(client, auth_headers):
    r = client.post(
        "/api/security", headers=auth_headers, json={"current_password": "wrong", "new_password": "longenough1"}
    )
    assert_error(r, 403, "invalid_credentials")


def test_password_change_invalidates_sessions(client, auth_headers):
    r = client.post(
        "/api/security", headers=auth_headers, json={"current_password": "admin", "new_password": "longenough1"}
    )
    assert r.status_code == 200 and r.json()["is_default_password"] is False
    assert client.get("/api/fans", headers=auth_headers).status_code == 401
    assert client.post("/api/auth/login", json={"password": "longenough1"}).status_code == 200


def test_legacy_hash_upgraded_on_login(client):
    config.STORED_PASSWORD_HASH = hashlib.sha256(b"legacy-pass").hexdigest()
    assert client.post("/api/auth/login", json={"password": "legacy-pass"}).status_code == 200
    assert config.STORED_PASSWORD_HASH.startswith("scrypt$")


def test_security_reports_min_length(client, auth_headers):
    assert client.get("/api/security", headers=auth_headers).json()["min_password_length"] == 8


def test_docs_hidden_by_default(client, auth_headers):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert_error(client.get(path, headers=auth_headers), 404)


def test_docs_require_auth_when_enabled(client, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_API_DOCS", True)
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/openapi.json", headers=auth_headers).status_code == 200


def test_oversized_body_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setattr(config, "MAX_BODY_BYTES", 64)
    r = client.post("/api/layout", headers=auth_headers, content=b"x" * 200)
    assert_error(r, 413, "payload_too_large")
