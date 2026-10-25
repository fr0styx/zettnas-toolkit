"""
Encryption at rest for small secrets stored in the users database (SEC-14).

TOTP seeds were stored in plain text, so anyone who got a copy of users.db (a
backup, a snapshot, a readable appdata share) could generate valid 2FA codes.
They are now sealed with AES-256-GCM under a key derived from the install's
SECRET_KEY (data/secret.key). Values without the "enc1:" prefix are legacy
plain text and are read as-is until migrate_plaintext_mfa_secrets() seals them.
"""

import base64
import hashlib
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend import config

logger = logging.getLogger("ZettNAS")

PREFIX = "enc1:"
_AAD = b"zettnas:mfa_secret:v1"


class SecretBoxError(ValueError):
    pass


def _key(secret: str | None = None) -> bytes:
    secret = str(secret if secret is not None else (getattr(config, "SECRET_KEY", "") or ""))
    if not secret:
        raise SecretBoxError("SECRET_KEY is not set")
    return hashlib.sha256(b"zettnas-secret-box-v1:" + secret.encode("utf-8")).digest()


def _previous_secret() -> str:
    """The key before a rotation that hasn't finished (see services/key_rotation.py)."""
    try:
        with open(str(getattr(config, "SECRET_KEY_FILE", "")) + ".previous", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def is_sealed(value: str) -> bool:
    return bool(value) and value.startswith(PREFIX)


def seal(plain: str) -> str:
    if not plain:
        return ""
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plain.encode("utf-8"), _AAD)
    return PREFIX + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def unseal(value: str) -> str:
    if not value or not is_sealed(value):
        return value or ""
    try:
        raw = base64.urlsafe_b64decode(value[len(PREFIX) :].encode("ascii"))
    except ValueError as e:
        raise SecretBoxError("A stored secret is damaged") from e
    for secret in (None, _previous_secret()):
        if secret == "":
            continue
        try:
            return AESGCM(_key(secret)).decrypt(raw[:12], raw[12:], _AAD).decode("utf-8")
        except (InvalidTag, ValueError):
            continue
    raise SecretBoxError("Could not decrypt a stored secret (was SECRET_KEY changed?)")


def migrate_plaintext_mfa_secrets(db_path: str = "") -> int:
    """Seals every TOTP seed still stored in plain text. Returns how many were sealed."""
    from backend.users_db import users_db_session

    sealed = 0
    with users_db_session(db_path or None) as conn:
        rows = conn.execute("SELECT id, mfa_secret FROM users WHERE COALESCE(mfa_secret, '') != ''").fetchall()
        for row in rows:
            if not is_sealed(row["mfa_secret"]):
                conn.execute("UPDATE users SET mfa_secret = ? WHERE id = ?", (seal(row["mfa_secret"]), row["id"]))
                sealed += 1
    if sealed:
        logger.info(f"[Security] Encrypted {sealed} stored two-factor secret(s)")
    return sealed
