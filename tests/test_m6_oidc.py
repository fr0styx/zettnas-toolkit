"""M6: OpenID Connect sign-in against a fake provider (Authentik/Keycloak-style)."""

import base64
import json
import time
import urllib.parse

import httpx
import pytest

from backend.services import oidc

ISSUER = "https://auth.example.test/application/o/zettnas"


def _jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setattr(oidc, "CONFIG_FILE", str(tmp_path / "oidc.json"))
    oidc._discovery.clear()
    oidc._states.clear()
    oidc.save_config(
        {
            "enabled": True,
            "issuer": ISSUER,
            "client_id": "zettnas",
            "client_secret": "s3cret",
            "admin_groups": ["nas-admins"],
            "role_map": {"family": "share_user"},
        }
    )
    seen = {}
    claims = {
        "sub": "u-123",
        "preferred_username": "Alice",
        "email": "alice@example.test",
        "name": "Alice A",
        "groups": ["nas-admins"],
    }

    def handler(req: httpx.Request):
        if req.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "userinfo_endpoint": f"{ISSUER}/userinfo",
                },
            )
        if req.url.path.endswith("/token"):
            form = dict(urllib.parse.parse_qsl(req.content.decode()))
            seen["token_form"] = form
            idt = {**claims, "iss": ISSUER, "aud": "zettnas", "exp": time.time() + 300, "nonce": seen["nonce"]}
            return httpx.Response(200, json={"id_token": _jwt(idt), "access_token": "at"})
        if req.url.path.endswith("/userinfo"):
            return httpx.Response(200, json={"sub": claims["sub"], "groups": claims["groups"]})
        return httpx.Response(404)

    client = lambda: httpx.Client(transport=httpx.MockTransport(handler))  # noqa: E731
    return seen, claims, client


def _login(seen, client):
    url = oidc.start_login("http://nas.local:8082", client())
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    seen["nonce"] = q["nonce"]
    assert q["code_challenge_method"] == "S256" and q["redirect_uri"] == "http://nas.local:8082/api/auth/oidc/callback"
    return q


def test_full_sign_in_creates_an_admin_from_groups(provider):
    seen, claims, client = provider
    q = _login(seen, client)
    got = oidc.finish_login("the-code", q["state"], client())
    assert seen["token_form"]["code_verifier"] and seen["token_form"]["client_secret"] == "s3cret"
    user = oidc.user_for_claims(got)
    assert user["username"] == "alice" and user["role_id"] == "superadmin" and user["idp_type"] == "oidc"
    # the same person signs in again after a rename at the IdP: same account
    claims["preferred_username"] = "alice.new"
    q = _login(seen, client)
    assert oidc.user_for_claims(oidc.finish_login("c2", q["state"], client()))["id"] == user["id"]


def test_state_is_single_use_and_checked(provider):
    seen, claims, client = provider
    q = _login(seen, client)
    oidc.finish_login("c", q["state"], client())
    with pytest.raises(oidc.OidcError, match="expired or was already used"):
        oidc.finish_login("c", q["state"], client())
    q = _login(seen, client)
    seen["nonce"] = "forged"
    with pytest.raises(oidc.OidcError, match="does not belong"):
        oidc.finish_login("c", q["state"], client())


def test_never_takes_over_a_local_account(provider):
    from backend.users_db import create_user, get_user_by_username

    seen, claims, client = provider
    if not get_user_by_username("bob"):
        create_user(username="bob", display_name="Bob", password="local-pass-123", email="bob@example.test")
    claims.update(
        sub="u-bob", preferred_username="bob", email="bob@example.test", email_verified=True, groups=["family"]
    )
    q = _login(seen, client)
    user = oidc.user_for_claims(oidc.finish_login("c", q["state"], client()))
    assert user["username"] == "bob-sso" and user["role_id"] == "share_user"
    assert get_user_by_username("bob")["idp_type"] in ("local", None, "")


def test_endpoints(client, auth_headers, provider):
    assert client.get("/api/auth/oidc/config").json() == {"enabled": True, "label": "Single sign-on"}
    s = client.get("/api/auth/oidc/settings", headers=auth_headers).json()
    assert s["client_secret"] == "********" and s["redirect_uri"].endswith("/api/auth/oidc/callback")
    r = client.get("/api/auth/oidc/callback?state=nope&code=x", follow_redirects=False)
    assert r.status_code == 303 and "sso_error=" in r.headers["location"]
    assert client.put("/api/auth/oidc/settings", json={"issuer": "ftp://x"}, headers=auth_headers).status_code == 400
