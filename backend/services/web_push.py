"""
Web Push to the installed phone app (M1).

Each browser that turns on notifications sends its push subscription; ZettNAS keeps
them in data/push_subscriptions.json, per user. Alerts are encrypted for that browser
(RFC 8291, aes128gcm, via http_ece) and signed with this NAS's VAPID key (RFC 8292),
then posted to the browser vendor's push service (Google, Mozilla, Apple, Microsoft).
The push service only sees ciphertext.

Only signed-in users subscribe; alerts go to admins' devices. Subscriptions the push
service reports as gone (404/410) are dropped.
"""

import base64
import json
import os
import threading
import time
import urllib.parse
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from backend.config import DATA_DIR, logger

KEY_FILE = os.path.join(DATA_DIR, "vapid.json")
SUBS_FILE = os.path.join(DATA_DIR, "push_subscriptions.json")
CONTACT = os.environ.get("ZETTNAS_PUSH_CONTACT", "https://github.com/fr0styx/zettnas-toolkit")
_lock = threading.Lock()


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _keys() -> tuple[ec.EllipticCurvePrivateKey, str]:
    with _lock:
        try:
            with open(KEY_FILE, encoding="utf-8") as f:
                pem = json.load(f)["private_pem"].encode()
            priv = serialization.load_pem_private_key(pem, password=None)
            assert isinstance(priv, ec.EllipticCurvePrivateKey)
        except (OSError, ValueError, KeyError, AssertionError):
            priv = ec.generate_private_key(ec.SECP256R1())
            pem = priv.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
            tmp = KEY_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"private_pem": pem.decode(), "created": time.time()}, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, KEY_FILE)
    pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return priv, b64u(pub)


def public_key() -> str:
    """The applicationServerKey browsers subscribe with (base64url, uncompressed P-256 point)."""
    return _keys()[1]


def vapid_header(endpoint: str, now: float | None = None) -> str:
    priv, pub = _keys()
    p = urllib.parse.urlsplit(endpoint)
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = b64u(
        json.dumps(
            {"aud": f"{p.scheme}://{p.netloc}", "exp": int((now or time.time()) + 12 * 3600), "sub": CONTACT}
        ).encode()
    )
    signing_input = f"{header}.{claims}".encode()
    r, s = decode_dss_signature(priv.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"vapid t={header}.{claims}.{b64u(sig)}, k={pub}"


def _load_subs() -> dict[str, dict[str, Any]]:
    try:
        with open(SUBS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_subs(subs: dict[str, dict[str, Any]]) -> None:
    tmp = SUBS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(subs, f, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SUBS_FILE)


def valid_endpoint(endpoint: str) -> bool:
    """Push services are public https endpoints; never a LAN address (SSRF)."""
    if not str(endpoint).startswith("https://") or len(endpoint) > 1024:
        return False
    try:
        from backend.services.ssrf_guard import validate_public_url

        return validate_public_url(endpoint)[0]
    except Exception:
        logger.debug("web_push: endpoint check failed", exc_info=True)
        return False


def subscribe(username: str, sub: dict[str, Any], user_agent: str = "") -> None:
    endpoint = str(sub.get("endpoint") or "")
    keys = sub.get("keys") or {}
    if not valid_endpoint(endpoint) or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("Not a valid push subscription")
    b64u_decode(keys["p256dh"])
    b64u_decode(keys["auth"])
    with _lock:
        subs = _load_subs()
        subs[endpoint] = {
            "user": username,
            "p256dh": keys["p256dh"],
            "auth": keys["auth"],
            "ua": user_agent[:120],
            "created": time.time(),
        }
        _save_subs(subs)


def unsubscribe(endpoint: str, username: str | None = None) -> bool:
    with _lock:
        subs = _load_subs()
        if endpoint in subs and (username is None or subs[endpoint]["user"] == username):
            del subs[endpoint]
            _save_subs(subs)
            return True
    return False


def subscriptions(username: str | None = None) -> list[dict[str, Any]]:
    return [{"endpoint": e, **v} for e, v in _load_subs().items() if username is None or v["user"] == username]


def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    import http_ece

    eph = ec.generate_private_key(ec.SECP256R1())
    return http_ece.encrypt(
        payload, private_key=eph, dh=b64u_decode(p256dh), auth_secret=b64u_decode(auth), version="aes128gcm"
    )


def send(sub: dict[str, Any], message: dict[str, Any], ttl: int = 86400, client: httpx.Client | None = None) -> int:
    body = encrypt(json.dumps(message).encode(), sub["p256dh"], sub["auth"])
    headers = {
        "Authorization": vapid_header(sub["endpoint"]),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Urgency": "high" if message.get("level") in ("critical", "alert", "error") else "normal",
    }
    own = client is None
    c = client or httpx.Client(timeout=10)
    try:
        return c.post(sub["endpoint"], content=body, headers=headers).status_code
    finally:
        if own:
            c.close()


def notify(
    title: str,
    body: str,
    level: str = "normal",
    url: str = "/",
    users: list[str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, int]:
    """Sends to the devices of `users` (default: all admins). Returns status per endpoint."""
    if users is None:
        from backend.users_db import list_users

        users = [u["username"] for u in list_users() if u.get("role_id") in ("superadmin", "admin")]
    out: dict[str, int] = {}
    msg = {"title": title[:120], "body": body[:400], "level": level, "url": url, "ts": int(time.time())}
    for sub in subscriptions():
        if sub["user"] not in users:
            continue
        try:
            status = send(sub, msg, client=client)
        except Exception as e:
            logger.debug(f"[WebPush] send failed: {e}")
            status = 0
        out[sub["endpoint"][:60]] = status
        if status in (404, 410):
            unsubscribe(sub["endpoint"])
    return out
