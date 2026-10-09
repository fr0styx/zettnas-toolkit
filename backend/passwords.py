"""
Enterprise password hashing using Argon2id (RFC 9106) with transparent zero-downtime
migration from legacy scrypt and unsalted SHA-256 formats.

Target format: $argon2id$v=19$m=65536,t=3,p=4$...
Legacy format 1: scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>
Legacy format 2: <64 hex chars> (sha256(password))
"""

import hashlib
import hmac
import secrets

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    _ARGON2_AVAILABLE = True
    _PH = PasswordHasher(
        time_cost=3,
        memory_cost=65536,  # 64 MB
        parallelism=4,
        hash_len=32,
        salt_len=16,
    )
except ImportError:
    _ARGON2_AVAILABLE = False
    _PH = None

_N, _R, _P = 2**14, 8, 1
_DKLEN = 32


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id (falling back to scrypt if argon2-cffi is unavailable)."""
    if _ARGON2_AVAILABLE and _PH:
        return _PH.hash(password)
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def is_legacy_hash(stored: str) -> bool:
    """True if stored is a legacy SHA-256 or scrypt hash (i.e. not Argon2id)."""
    if not stored:
        return False
    if stored.startswith("$argon2id$") or stored.startswith("$argon2i$"):
        return False
    return True


def needs_rehash(stored: str) -> bool:
    """Returns True if the stored hash should be upgraded to modern Argon2id on successful login."""
    if not stored:
        return True
    if not stored.startswith("$argon2id$"):
        return True
    try:
        return _PH.check_needs_rehash(stored) if _PH else False
    except Exception:
        return True


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification against Argon2id, scrypt, or legacy SHA-256 hashes."""
    if not stored or password is None:
        return False

    # 1. Argon2id (RFC 9106)
    if stored.startswith("$argon2"):
        if _ARGON2_AVAILABLE and _PH:
            try:
                return _PH.verify(stored, password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False
            except Exception:
                return False
        return False

    # 2. scrypt format
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt_hex, hash_hex = stored.split("$")
            dk = hashlib.scrypt(
                password.encode(),
                salt=bytes.fromhex(salt_hex),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(hash_hex) // 2,
            )
            return hmac.compare_digest(dk.hex(), hash_hex)
        except (ValueError, TypeError):
            return False

    # 3. Legacy unsalted SHA-256
    if len(stored) == 64:
        return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)

    return False
