"""M3: connecting a fresh Immich to ZettNAS's sign-in provider through Immich's API."""

import json

import httpx
import pytest

from backend.services import immich_sso


class FakeImmich:
    def __init__(self, initialized=False):
        self.initialized = initialized
        self.users = {}
        self.config = {"oauth": {"enabled": False, "mobileOverrideEnabled": False}, "ffmpeg": {"crf": 23}}

    def __call__(self, req: httpx.Request):
        p, body = req.url.path, json.loads(req.content or b"{}")
        if p == "/api/server/config":
            return httpx.Response(200, json={"isInitialized": self.initialized})
        if p == "/api/auth/admin-sign-up":
            self.users[body["email"]] = body["password"]
            self.initialized = True
            return httpx.Response(201, json={"id": "u1"})
        if p == "/api/auth/login":
            ok = self.users.get(body["email"]) == body["password"]
            return httpx.Response(201 if ok else 401, json={"accessToken": "tok"} if ok else {})
        if p == "/api/system-config":
            assert req.headers["authorization"] == "Bearer tok"
            if req.method == "GET":
                return httpx.Response(200, json=self.config)
            self.config = body
            return httpx.Response(200, json=body)
        return httpx.Response(404)


OIDC = {
    "issuer": "https://auth.home.lan/application/o/zettnas",
    "client_id": "zettnas",
    "client_secret": "s",
    "label": "Authentik",
}


def test_fresh_immich_gets_admin_and_oauth(tmp_path):
    fake = FakeImmich()
    res = immich_sso.connect("http://nas:2283", "me@home.lan", str(tmp_path), OIDC, transport=httpx.MockTransport(fake))
    assert res["steps"] == ["admin created", "signed in", "oauth enabled"]
    o = fake.config["oauth"]
    assert o["enabled"] and o["issuerUrl"] == OIDC["issuer"] and o["clientId"] == "zettnas" and o["autoRegister"]
    assert o["buttonText"] == "Sign in with Authentik" and fake.config["ffmpeg"] == {"crf": 23}  # other settings kept
    assert "http://nas:2283/auth/login" in res["redirect_uris"]
    # running it again reuses the stored admin password
    again = immich_sso.connect(
        "http://nas:2283", "me@home.lan", str(tmp_path), OIDC, transport=httpx.MockTransport(fake)
    )
    assert again["steps"] == ["signed in", "oauth enabled"]


def test_existing_foreign_admin_and_missing_setup(tmp_path):
    fake = FakeImmich(initialized=True)
    with pytest.raises(immich_sso.ImmichSsoError, match="by hand"):
        immich_sso.connect("http://nas:2283", "me@home.lan", str(tmp_path), OIDC, transport=httpx.MockTransport(fake))
    with pytest.raises(immich_sso.ImmichSsoError, match="Single sign-on"):
        immich_sso.connect("http://nas:2283", "me@home.lan", str(tmp_path), {}, transport=httpx.MockTransport(fake))
