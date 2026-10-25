"""D5: TrueNAS companion mode reads pools/shares and snapshots through the API."""

import json

import httpx
import pytest

from backend.services import truenas_api


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("TRUENAS_URL", "https://truenas.test")
    monkeypatch.setenv("TRUENAS_API_KEY", "1-abc")
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.headers.get("authorization"), req.content))
        p = req.url.path
        if p == "/api/v2.0/pool":
            return httpx.Response(
                200, json=[{"name": "tank", "status": "ONLINE", "healthy": True, "size": 10, "allocated": 4, "free": 6}]
            )
        if p == "/api/v2.0/sharing/smb":
            return httpx.Response(200, json=[{"name": "family", "path": "/mnt/tank/family", "enabled": True}])
        if p == "/api/v2.0/sharing/nfs":
            return httpx.Response(200, json=[{"path": "/mnt/tank/media", "enabled": True}])
        if p == "/api/v2.0/zfs/snapshot":
            return httpx.Response(200, json={"name": "tank@x"})
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


def test_reads_pools_and_shares(api):
    t, seen = api
    assert truenas_api.pools(t)[0]["name"] == "tank"
    assert {s["protocol"] for s in truenas_api.shares(t)} == {"smb", "nfs"}
    assert all(h == "Bearer 1-abc" for _, _, h, _ in seen)


def test_snapshot_through_the_api(api):
    t, seen = api
    assert truenas_api.create_snapshot("tank", "ransomware-guard-20261022", transport=t)["success"]
    method, path, _, body = seen[-1]
    assert method == "POST" and path == "/api/v2.0/zfs/snapshot"
    assert json.loads(body) == {"dataset": "tank", "name": "ransomware-guard-20261022", "recursive": True}
    with pytest.raises(truenas_api.TrueNASError):
        truenas_api.create_snapshot("tank", "bad name;rm", transport=t)


def test_not_configured_by_default(monkeypatch):
    monkeypatch.delenv("TRUENAS_URL", raising=False)
    assert not truenas_api.configured()


class _FakeWS:
    """A TrueNAS JSON-RPC WebSocket that answers from a table."""

    def __init__(self, answers):
        self.answers, self.sent = answers, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send(self, msg):
        self.sent.append(json.loads(msg))

    def recv(self, timeout=None):
        req = self.sent[-1]
        return json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": self.answers[req["method"]]})


def test_truenas_26_without_rest_uses_json_rpc(monkeypatch):
    """TrueNAS 26 removed /api/v2.0: the same data comes over JSON-RPC (/api/current)."""
    import httpx

    from backend.services import truenas_api

    monkeypatch.setenv("TRUENAS_URL", "https://truenas.local")
    monkeypatch.setenv("TRUENAS_API_KEY", "1-abc")
    gone = httpx.MockTransport(lambda req: httpx.Response(404))
    ws = _FakeWS(
        {"auth.login_with_api_key": True, "pool.query": [{"name": "tank", "status": "ONLINE", "healthy": True}]}
    )
    urls = []
    monkeypatch.setattr(truenas_api, "_open_ws", lambda u: urls.append(u) or ws)
    out = truenas_api.pools(transport=gone)
    assert out[0]["name"] == "tank" and urls == ["wss://truenas.local/api/current"]
    assert ws.sent[0]["method"] == "auth.login_with_api_key" and ws.sent[0]["params"] == ["1-abc"]


def test_json_rpc_refuses_a_bad_key(monkeypatch):
    import pytest

    from backend.services import truenas_api

    monkeypatch.setenv("TRUENAS_URL", "http://truenas.local")
    monkeypatch.setenv("TRUENAS_API_KEY", "wrong")
    monkeypatch.setattr(truenas_api, "_open_ws", lambda u: _FakeWS({"auth.login_with_api_key": False}))
    with pytest.raises(truenas_api.TrueNASError, match="refused"):
        truenas_api._rpc("pool.query")
