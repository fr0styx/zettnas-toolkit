"""COMP-08: TrueNAS 27 and later. The API key never travels without encryption (TrueNAS revokes
it), and with TRUENAS_USER the WebSocket sign-in is auth.login_ex, which TrueNAS 28 requires."""

import json

import httpx
import pytest

from backend.hardware.pal import truenas_api


class _WS:
    def __init__(self, login_result):
        self.login_result, self.sent = login_result, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send(self, raw):
        self.sent.append(json.loads(raw))

    def recv(self, timeout=None):
        req = self.sent[-1]
        result = self.login_result if req["id"] == 1 else [{"name": "tank"}]
        return json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result})


def test_a_plain_http_address_is_refused_before_the_key_is_sent(monkeypatch):
    monkeypatch.setenv("TRUENAS_URL", "http://truenas.local")
    monkeypatch.setenv("TRUENAS_API_KEY", "1-secret")
    opened, requests = [], []
    monkeypatch.setattr(truenas_api, "_open_ws", lambda url: opened.append(url))
    transport = httpx.MockTransport(lambda req: requests.append(req) or httpx.Response(200, json=[]))
    with pytest.raises(truenas_api.TrueNASError, match="https://"):
        truenas_api._rpc("pool.query")
    with pytest.raises(truenas_api.TrueNASError, match="revokes"):
        truenas_api.pools(transport=transport)
    assert opened == [] and requests == []


def test_with_a_user_the_sign_in_is_login_ex(monkeypatch):
    monkeypatch.setenv("TRUENAS_URL", "https://truenas.local")
    monkeypatch.setenv("TRUENAS_API_KEY", "1-secret")
    monkeypatch.setenv("TRUENAS_USER", "zettnas")
    ws = _WS({"response_type": "SUCCESS", "user_info": None})
    seen = []
    monkeypatch.setattr(truenas_api, "_open_ws", lambda url: seen.append(url) or ws)
    assert truenas_api._rpc("pool.query") == [{"name": "tank"}]
    assert seen == ["wss://truenas.local/api/current"]
    assert ws.sent[0]["method"] == "auth.login_ex"
    assert ws.sent[0]["params"] == [{"mechanism": "API_KEY_PLAIN", "username": "zettnas", "api_key": "1-secret"}]


def test_login_ex_that_does_not_succeed_is_a_refusal(monkeypatch):
    monkeypatch.setenv("TRUENAS_URL", "https://truenas.local")
    monkeypatch.setenv("TRUENAS_USER", "zettnas")
    monkeypatch.setattr(truenas_api, "_open_ws", lambda url: _WS({"response_type": "AUTH_ERR"}))
    with pytest.raises(truenas_api.TrueNASError, match="refused"):
        truenas_api._rpc("pool.query")


def test_without_a_user_the_older_sign_in_stays(monkeypatch):
    monkeypatch.setenv("TRUENAS_URL", "https://truenas.local")
    monkeypatch.delenv("TRUENAS_USER", raising=False)
    ws = _WS(True)
    monkeypatch.setattr(truenas_api, "_open_ws", lambda url: ws)
    truenas_api._rpc("pool.query")
    assert ws.sent[0]["method"] == "auth.login_with_api_key"
