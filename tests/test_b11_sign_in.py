"""B11 (SEC-29, D11): sign-in that is unsafe is warned about for one release, then refused.
Single sign-on is bound to the browser that started it; the Security Advisor names http://
providers, plaintext directory sign-in and a proxy that can reach any account."""

import pytest

from backend.services import ldap_auth, oidc, safe_defaults_advisor
from backend.users_db import create_user, get_user_by_username


@pytest.fixture
def sso(monkeypatch):
    monkeypatch.setattr(oidc, "start_login", lambda base: "https://idp.example/auth?state=abc123&nonce=n")
    user = get_user_by_username("sso_ann") or create_user("sso_ann", "Ann", "GoodPass123!", role_id="share_user")
    monkeypatch.setattr(oidc, "finish_login", lambda code, state: {"sub": "ann", "state": state})
    monkeypatch.setattr(oidc, "user_for_claims", lambda claims: user)
    return user


def test_starting_sign_in_binds_it_to_this_browser(client, sso):
    res = client.get("/api/auth/oidc/login", follow_redirects=False)
    assert res.status_code == 303
    cookie = res.headers["set-cookie"]
    assert "zn_sso_state=abc123" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()


def test_a_sign_in_started_in_another_browser_is_refused(client, sso):
    client.cookies.set("zn_sso_state", "someone-elses", path="/api")
    res = client.get("/api/auth/oidc/callback?code=c&state=abc123", follow_redirects=False)
    assert res.status_code == 303 and "sso_error=" in res.headers["location"]
    assert "another%20browser" in res.headers["location"]


def test_the_same_browser_signs_in_and_the_cookie_is_cleared(client, sso):
    client.cookies.set("zn_sso_state", "abc123", path="/api")
    res = client.get("/api/auth/oidc/callback?code=c&state=abc123", follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/"
    assert any("zn_sso_state=" in c and "Max-Age=0" in c for c in res.headers.get_list("set-cookie"))


def test_without_the_cookie_it_still_works_this_release_but_is_logged(client, sso, caplog):
    client.cookies.clear()
    res = client.get("/api/auth/oidc/callback?code=c&state=abc123", follow_redirects=False)
    assert res.headers["location"] == "/"
    assert "without the browser cookie" in caplog.text


def _ids():
    return {f["id"] for f in safe_defaults_advisor.findings()}


def test_the_advisor_names_an_http_provider(monkeypatch):
    monkeypatch.setattr(oidc, "load_config", lambda: {"enabled": True, "issuer": "http://idp.lan"})
    found = [f for f in safe_defaults_advisor.findings() if f["id"] == "sso_http_issuer"]
    assert found and "next release" in found[0]["details"] and "fix" not in found[0]
    monkeypatch.setattr(oidc, "load_config", lambda: {"enabled": True, "issuer": "https://idp.lan"})
    assert "sso_http_issuer" not in _ids()


def test_the_advisor_names_plaintext_and_unchecked_directory_sign_in(monkeypatch):
    cfg = {"enabled": True, "server_url": "ldap://dc.lan", "start_tls": False, "verify_tls": False}
    monkeypatch.setattr(ldap_auth, "load_config", lambda: cfg)
    assert {"ldap_plaintext", "ldap_unverified"} <= _ids()
    cfg.update(start_tls=True, verify_tls=True)
    assert not {"ldap_plaintext", "ldap_unverified"} & _ids()
    cfg.update(server_url="ldaps://dc.lan", start_tls=False)
    assert "ldap_plaintext" not in _ids()


def test_the_advisor_names_a_proxy_that_reaches_local_accounts(monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "ENABLE_PROXY_SSO", True)
    assert "proxy_sso_local_accounts" in _ids()  # the admin account is local
    monkeypatch.setattr(config, "ENABLE_PROXY_SSO", False)
    assert "proxy_sso_local_accounts" not in _ids()


def test_the_posture_shows_a_warning_without_a_fix_button(client, auth_headers, monkeypatch):
    monkeypatch.setattr(oidc, "load_config", lambda: {"enabled": True, "issuer": "http://idp.lan"})
    checks = client.get("/api/system/security-posture", headers=auth_headers).json()["checks"]
    check = next(c for c in checks if c["id"] == "sso_http_issuer")
    assert check["passed"] is False and "fix" not in check


def test_a_proxy_sign_in_to_a_local_account_is_logged_once_a_day(monkeypatch):
    from backend import auth

    events = []
    monkeypatch.setattr("backend.users_db.log_security_event", lambda *a, **k: events.append((a, k)))
    auth._PROXY_WARNED.clear()
    auth._warn_proxy_local_account({"username": "admin", "idp_type": "local"})
    auth._warn_proxy_local_account({"username": "admin", "idp_type": "local"})
    assert len(events) == 1 and events[0][0][0] == "auth.proxy_sso_local_account"
