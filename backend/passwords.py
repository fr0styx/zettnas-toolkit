"""
Password hashing using scrypt (stdlib, memory-hard) with transparent
migration from the legacy unsalted SHA-256 format.

Stored format:  scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>
Legacy format:  <64 hex chars>  (sha256(password))
"""

import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
_DKLEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def is_legacy_hash(stored: str) -> bool:
    return bool(stored) and not stored.startswith("scrypt$") and len(stored) == 64


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification against scrypt or legacy SHA-256 hashes."""
    if not stored or password is None:
        return False
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt_hex, hash_hex = stored.split("$")
            dk = hashlib.scrypt(
                password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2
            )
            return hmac.compare_digest(dk.hex(), hash_hex)
        except (ValueError, TypeError):
            return False
    if is_legacy_hash(stored):
        return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)
    return False
