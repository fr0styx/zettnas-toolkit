"""M1 push: VAPID-signed, RFC 8291-encrypted messages a browser can decrypt."""

import base64
import json

import http_ece
import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from backend.services import web_push as wp


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(wp, "KEY_FILE", str(tmp_path / "vapid.json"))
    monkeypatch.setattr(wp, "SUBS_FILE", str(tmp_path / "subs.json"))
    monkeypatch.setattr(wp, "valid_endpoint", lambda e: e.startswith("https://"))


def _browser():
    """A fake browser subscription: its keys, and the JSON it would send."""
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    return (
        priv,
        auth,
        {
            "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
            "keys": {"p256dh": wp.b64u(pub), "auth": wp.b64u(auth)},
        },
    )


def test_message_decrypts_in_the_browser_and_vapid_verifies(store):
    priv, auth, sub = _browser()
    wp.subscribe("admin", sub)
    seen = {}

    def handler(req: httpx.Request):
        seen["headers"] = dict(req.headers)
        seen["body"] = req.content
        return httpx.Response(201)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    out = wp.notify("Disk sdb is failing", "Back up its data.", level="critical", users=["admin"], client=client)
    assert list(out.values()) == [201]
    h = seen["headers"]
    assert h["content-encoding"] == "aes128gcm" and h["urgency"] == "high"
    plain = http_ece.decrypt(seen["body"], private_key=priv, auth_secret=auth, version="aes128gcm")
    msg = json.loads(plain)
    assert msg["title"] == "Disk sdb is failing" and msg["level"] == "critical"
    # VAPID: JWT signed by the key in k=, audience is the push service origin
    t = h["authorization"].split("t=")[1].split(",")[0]
    k = h["authorization"].split("k=")[1]
    head, claims, sig = t.split(".")
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), wp.b64u_decode(k))
    raw = wp.b64u_decode(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    pub.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    assert json.loads(base64.urlsafe_b64decode(claims + "==="))["aud"] == "https://fcm.googleapis.com"
    assert k == wp.public_key()


def test_gone_subscriptions_are_dropped(store):
    _, _, sub = _browser()
    wp.subscribe("admin", sub)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(410)))
    wp.notify("x", "y", users=["admin"], client=client)
    assert wp.subscriptions() == []


def test_rejects_bad_subscriptions(store, monkeypatch):
    monkeypatch.setattr(wp, "valid_endpoint", lambda e: False)
    with pytest.raises(ValueError):
        wp.subscribe("admin", {"endpoint": "http://192.168.1.1/x", "keys": {"p256dh": "a", "auth": "b"}})


def test_api_subscribe_and_key(client, auth_headers, store):
    assert len(wp.b64u_decode(client.get("/api/push/vapid-public-key", headers=auth_headers).json()["key"])) == 65
    _, _, sub = _browser()
    assert client.post("/api/push/subscribe", json=sub, headers=auth_headers).status_code == 200
    assert client.get("/api/push/devices", headers=auth_headers).json()[0]["endpoint_host"] == "fcm.googleapis.com"
    assert client.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]}, headers=auth_headers).json()[
        "removed"
    ]
