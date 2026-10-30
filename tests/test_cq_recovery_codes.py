"""Recovery codes are hashed like passwords; codes stored the old way (SHA-256) still work once."""

import hashlib

from backend import totp


def test_new_codes_are_slow_hashed_and_verify():
    codes = totp.generate_recovery_codes(3)
    stored = [totp.hash_recovery_code(c) for c in codes]
    assert all(s.startswith(("$argon2", "scrypt$")) for s in stored)
    ok, left = totp.verify_and_consume_recovery_code(stored, codes[1].upper().replace("-", " "))
    assert ok and len(left) == 2 and stored[1] not in left
    assert totp.verify_and_consume_recovery_code(left, codes[1]) == (False, left)


def test_old_sha256_codes_still_work():
    old = hashlib.sha256(b"zettnas:recovery:abcd2345").hexdigest()
    ok, left = totp.verify_and_consume_recovery_code([old, totp.hash_recovery_code("zzzz-zzzz")], "abcd-2345")
    assert ok and len(left) == 1
    assert totp.verify_and_consume_recovery_code([old], "wrong-code")[0] is False
