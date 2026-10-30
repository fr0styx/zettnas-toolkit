"""
Tests for TOTP 2FA secret generation, OTPAuth URI synthesis,
and Version 4-M QR Code SVG generation & Reed-Solomon interleaving.
"""

import xml.etree.ElementTree as ET

from backend.totp import (
    generate_qr_svg,
    generate_recovery_codes,
    generate_totp_code,
    generate_totp_secret,
    get_otpauth_uri,
    hash_recovery_code,
    verify_totp_code,
)


def test_totp_secret_and_uri():
    secret = generate_totp_secret()
    assert len(secret) == 32
    assert secret.isalnum()

    uri = get_otpauth_uri("testuser", secret, issuer="ZettNAS")
    assert uri.startswith("otpauth://totp/")
    assert "testuser" in uri
    assert f"secret={secret}" in uri
    assert "issuer=ZettNAS" in uri


def test_totp_code_verification():
    secret = generate_totp_secret()
    code = generate_totp_code(secret)
    assert len(code) == 6
    assert code.isdigit()

    assert verify_totp_code(secret, code, user_id="test-user-1") is True
    # Replay protection within the same step should reject the identical code
    assert verify_totp_code(secret, code, user_id="test-user-1") is False
    # Invalid code
    assert verify_totp_code(secret, "000000", user_id="test-user-2") is False


def test_recovery_codes_generation_and_hashing():
    codes = generate_recovery_codes(8)
    assert len(codes) == 8
    for c in codes:
        assert len(c) == 9  # xxxx-xxxx
        assert "-" in c
        h = hash_recovery_code(c)
        assert h.startswith(("$argon2", "scrypt$"))  # hashed like a password, not a fast hash


def test_generate_qr_svg_structure():
    uri = get_otpauth_uri("admin", generate_totp_secret(), issuer="ZettNAS")
    svg_str = generate_qr_svg(uri)

    assert isinstance(svg_str, str)
    assert svg_str.startswith("<svg")
    assert svg_str.endswith("</svg>")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg_str
    assert "viewBox=" in svg_str

    # Must be valid XML
    root = ET.fromstring(svg_str)
    # Must have path elements (modules/pixels)
    paths = root.findall(".//{http://www.w3.org/2000/svg}path")
    assert len(paths) >= 1
    d_attr = paths[0].attrib.get("d", "")
    assert len(d_attr) > 100
    assert "M" in d_attr and "z" in d_attr
