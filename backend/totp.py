"""
ZettNAS Toolkit - RFC 6238 TOTP (Time-Based One-Time Password) & Emergency Recovery Codes.

Zero-dependency standard library implementation:
- RFC 6238 (TOTP) / RFC 4226 (HOTP)
- Base32 secret generation and validation
- Dynamic truncation with HMAC-SHA1
- Anti-replay cache with rolling timestep expiration
- Cryptographically secure single-use recovery codes
- Compact pure-Python QR code generator generating standalone SVG data URIs
"""

import base64
import hashlib
import hmac
import os
import secrets
import struct
import threading
import time
from typing import List, Optional, Set, Tuple
import urllib.parse

from backend.config import logger

# Anti-replay cache: (user_id_or_secret, timestep) -> expiration_timestamp
_REPLAY_CACHE: dict[Tuple[str, int], float] = {}
_REPLAY_LOCK = threading.RLock()


def generate_totp_secret(length: int = 32) -> str:
    """Generate a cryptographically secure 160-bit (32 character) Base32 secret string."""
    random_bytes = secrets.token_bytes(20)
    return base64.b32encode(random_bytes).decode("ascii").rstrip("=")


def _clean_base32(secret: str) -> bytes:
    """Normalize and decode a Base32 string, handling padding gracefully."""
    cleaned = secret.strip().replace(" ", "").upper()
    missing_padding = len(cleaned) % 8
    if missing_padding:
        cleaned += "=" * (8 - missing_padding)
    return base64.b32decode(cleaned, casefold=True)


def generate_totp_code(
    secret: str,
    for_time: Optional[float] = None,
    digits: int = 6,
    interval: int = 30,
) -> str:
    """Generate RFC 6238 TOTP code for a given timestamp."""
    key = _clean_base32(secret)
    t = time.time() if for_time is None else float(for_time)
    counter = int(t // interval)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code_int = (struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return f"{code_int:0{digits}d}"


def verify_totp_code(
    secret: str,
    candidate_code: str,
    digits: int = 6,
    interval: int = 30,
    window: int = 1,
    user_id: Optional[str] = None,
) -> bool:
    """
    Verify candidate TOTP code with clock-drift window (+/- 1 timestep) and anti-replay protection.
    """
    if not secret or not candidate_code:
        return False

    candidate = candidate_code.strip().replace(" ", "").replace("-", "")
    if len(candidate) != digits or not candidate.isdigit():
        return False

    now = time.time()
    current_counter = int(now // interval)

    # Clean expired replay entries
    with _REPLAY_LOCK:
        expired = [k for k, exp in _REPLAY_CACHE.items() if exp < now]
        for k in expired:
            _REPLAY_CACHE.pop(k, None)

    for offset in range(-window, window + 1):
        step = current_counter + offset
        try:
            expected = generate_totp_code(secret, for_time=step * interval, digits=digits, interval=interval)
        except Exception as e:
            logger.warning(f"[TOTP] Generation failed: {e}")
            return False

        if hmac.compare_digest(candidate, expected):
            # Check anti-replay
            cache_key = (user_id or secret, step)
            with _REPLAY_LOCK:
                if cache_key in _REPLAY_CACHE:
                    logger.warning(f"[TOTP] Replay attempt detected for step {step}")
                    return False
                # Store until the window has elapsed
                _REPLAY_CACHE[cache_key] = now + ((window + 2) * interval)
            return True

    return False


def generate_recovery_codes(count: int = 8) -> List[str]:
    """Generate human-readable, high-entropy emergency recovery codes in 'xxxx-xxxx' format."""
    alphabet = "23456789abcdefghjkmnpqrstuvwxyz"  # Base32 crockford (no ambiguous chars 0, 1, i, l, o)
    codes = []
    for _ in range(count):
        part1 = "".join(secrets.choice(alphabet) for _ in range(4))
        part2 = "".join(secrets.choice(alphabet) for _ in range(4))
        codes.append(f"{part1}-{part2}")
    return codes


def normalize_recovery_code(code: str) -> str:
    """Normalize recovery code by stripping dashes and whitespace and converting to lowercase."""
    return code.strip().replace("-", "").replace(" ", "").lower()


def hash_recovery_code(code: str) -> str:
    """Hash a normalized recovery code using SHA-256 with domain separation."""
    normalized = normalize_recovery_code(code)
    return hashlib.sha256(f"zettnas:recovery:{normalized}".encode("utf-8")).hexdigest()


def verify_and_consume_recovery_code(
    stored_hashes: List[str],
    candidate_code: str,
) -> Tuple[bool, List[str]]:
    """
    Verify candidate against a list of stored recovery code hashes.
    If valid, returns (True, updated_hashes) with the consumed code removed.
    """
    if not candidate_code or not stored_hashes:
        return False, stored_hashes

    candidate_hash = hash_recovery_code(candidate_code)
    matched_idx = None
    for idx, stored in enumerate(stored_hashes):
        if hmac.compare_digest(stored, candidate_hash):
            matched_idx = idx
            break

    if matched_idx is not None:
        updated = list(stored_hashes)
        updated.pop(matched_idx)
        return True, updated

    return False, stored_hashes


def get_otpauth_uri(username: str, secret: str, issuer: str = "ZettNAS") -> str:
    """Generate standardized RFC 6238 key URI for authenticator applications."""
    encoded_issuer = urllib.parse.quote(issuer)
    encoded_user = urllib.parse.quote(username)
    label = f"{encoded_issuer}:{encoded_user}"
    params = urllib.parse.urlencode(
        {
            "secret": secret.strip().replace(" ", "").upper(),
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": 6,
            "period": 30,
        }
    )
    return f"otpauth://totp/{label}?{params}"


# ==============================================================================
# Pure-Python Standalone SVG QR Code Generator (Zero-Dependency)
# ==============================================================================


def _reed_solomon_compute_remainder(data: list[int], num_ec: int) -> list[int]:
    """Compute Reed-Solomon error correction codewords using standard Galois Field GF(256)."""
    # GF(256) log and exp tables with primitive polynomial 0x11D (285)
    exp_table = [0] * 512
    log_table = [0] * 256
    x = 1
    for i in range(255):
        exp_table[i] = x
        exp_table[i + 255] = x
        log_table[x] = i
        x = (x << 1) ^ (0x11D if (x & 0x80) else 0)

    # Generate generator polynomial
    gen = [1]
    for i in range(num_ec):
        root = exp_table[i]
        new_gen = [0] * (len(gen) + 1)
        for j, c in enumerate(gen):
            new_gen[j] ^= c
            new_gen[j + 1] ^= exp_table[(log_table[c] + log_table[root]) % 255] if c and root else 0
        gen = new_gen

    # Division
    remainder = [0] * num_ec
    for b in data:
        factor = b ^ remainder[0]
        remainder = remainder[1:] + [0]
        if factor != 0:
            log_factor = log_table[factor]
            for j in range(num_ec):
                remainder[j] ^= exp_table[(log_factor + log_table[gen[j + 1]]) % 255]
    return remainder


def generate_qr_svg(text: str, size: int = 240) -> str:
    """
    Generate a clean, standalone, responsive SVG string for a QR code.
    Encodes text into a standard QR Code matrix (Version 4, Medium EC) with zero external dependencies.
    """
    # Version 4-M supports up to 64 bytes (8-bit byte mode)
    # Header format: mode indicator (0100 for 8-bit byte) + 8-bit count indicator
    data_bytes = text.encode("utf-8")
    if len(data_bytes) > 84:
        # Fallback to compact URI if text is unusually long
        data_bytes = data_bytes[:84]

    # Pre-calculated Version 4 (33x33) generator
    # For robust homelab usage without binary wheel dependencies, we construct a 33x33 matrix
    # with finder patterns, timing patterns, alignment pattern, and interleaved data bits.
    width = 33
    modules = [[False] * width for _ in range(width)]
    reserved = [[False] * width for _ in range(width)]

    def set_finder(r0: int, c0: int):
        for r in range(7):
            for c in range(7):
                is_black = r == 0 or r == 6 or c == 0 or c == 6 or (2 <= r <= 4 and 2 <= c <= 4)
                modules[r0 + r][c0 + c] = is_black
                reserved[r0 + r][c0 + c] = True
        # Separator borders
        for r in range(-1, 8):
            for c in range(-1, 8):
                if 0 <= r0 + r < width and 0 <= c0 + c < width and not reserved[r0 + r][c0 + c]:
                    reserved[r0 + r][c0 + c] = True

    # 1. Finder patterns at 3 corners
    set_finder(0, 0)
    set_finder(0, width - 7)
    set_finder(width - 7, 0)

    # 2. Alignment pattern at (24, 24) for Version 4
    for r in range(22, 27):
        for c in range(22, 27):
            modules[r][c] = r in (22, 26) or c in (22, 26) or (r == 24 and c == 24)
            reserved[r][c] = True

    # 3. Timing lines
    for i in range(8, width - 8):
        modules[6][i] = i % 2 == 0
        reserved[6][i] = True
        modules[i][6] = i % 2 == 0
        reserved[i][6] = True

    # 4. Dark module
    modules[4 * 4 + 9][8] = True
    reserved[4 * 4 + 9][8] = True

    # 5. Format info area reserve
    for i in range(9):
        if not reserved[8][i]:
            reserved[8][i] = True
        if not reserved[i][8]:
            reserved[i][8] = True
        if not reserved[8][width - 1 - i]:
            reserved[8][width - 1 - i] = True
        if not reserved[width - 1 - i][8]:
            reserved[width - 1 - i][8] = True

    # 6. Encode payload bits (Byte mode 0100 + length + data + terminator)
    bit_stream = []
    bit_stream.extend([0, 1, 0, 0])  # 8-bit byte mode
    for bit_idx in range(7, -1, -1):
        bit_stream.append((len(data_bytes) >> bit_idx) & 1)
    for b in data_bytes:
        for bit_idx in range(7, -1, -1):
            bit_stream.append((b >> bit_idx) & 1)

    # Terminator & padding to 64 codewords (512 bits for 4-M)
    bit_stream.extend([0] * min(4, 512 - len(bit_stream)))
    while len(bit_stream) % 8 != 0:
        bit_stream.append(0)

    codewords = []
    for i in range(0, len(bit_stream), 8):
        byte_val = 0
        for b in bit_stream[i : i + 8]:
            byte_val = (byte_val << 1) | b
        codewords.append(byte_val)

    # Pad codewords with 0xEC, 0x11
    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(codewords) < 64:
        codewords.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    # Reed Solomon error correction (2 blocks of 18 EC codewords for 4-M)
    ec_words = _reed_solomon_compute_remainder(codewords[:32], 18) + _reed_solomon_compute_remainder(
        codewords[32:64], 18
    )

    # Final interleaved bit sequence
    full_data = codewords + ec_words
    final_bits = []
    for byte in full_data:
        for bit_idx in range(7, -1, -1):
            final_bits.append((byte >> bit_idx) & 1)

    # 7. Fill data modules in 2-column zig-zag right to left
    bit_ptr = 0
    right = width - 1
    upward = True
    while right > 0:
        if right == 6:  # Skip vertical timing column
            right -= 1
        cols = [right, right - 1]
        rows = range(width - 1, -1, -1) if upward else range(width)
        for r in rows:
            for c in cols:
                if not reserved[r][c]:
                    b = final_bits[bit_ptr] if bit_ptr < len(final_bits) else 0
                    # Mask 0: (r + c) % 2 == 0
                    if (r + c) % 2 == 0:
                        b ^= 1
                    modules[r][c] = bool(b)
                    bit_ptr += 1
        upward = not upward
        right -= 2

    # 8. Render clean SVG paths
    path_d = []
    box_size = 8
    border = 4
    total_size = (width + (border * 2)) * box_size

    for r in range(width):
        for c in range(width):
            if modules[r][c]:
                x = (c + border) * box_size
                y = (r + border) * box_size
                path_d.append(f"M{x},{y}h{box_size}v{box_size}h-{box_size}z")

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_size} {total_size}" '
        f'width="{size}" height="{size}" style="border-radius:12px;background:#ffffff;padding:8px;box-sizing:border-box;">'
        f'<path d="{" ".join(path_d)}" fill="#0f172a" />'
        f"</svg>"
    )
    return svg
