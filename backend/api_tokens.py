import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json

TOKENS_FILE = os.path.join(DATA_DIR, "api_tokens.json")
# Format: { "<token_id>": { "hash": "<sha256>", "masked_token": "zat_...", "name": "...", "created": ts } }

_TOKENS_CACHE = {}
_tokens_file_mtime_ns = 0
_tokens_lock = threading.RLock()


def load_tokens() -> dict:
    """Thread-safe cached token loader with st_mtime_ns invalidation and legacy format migration."""
    global _TOKENS_CACHE, _tokens_file_mtime_ns
    with _tokens_lock:
        try:
            if not os.path.exists(TOKENS_FILE):
                _TOKENS_CACHE = {}
                _tokens_file_mtime_ns = 0
                return {}
            mtime = os.stat(TOKENS_FILE).st_mtime_ns
            if mtime == _tokens_file_mtime_ns and _TOKENS_CACHE:
                return _TOKENS_CACHE
            with open(TOKENS_FILE, "r") as f:
                raw_data = json.load(f)

            # Auto-migrate legacy format where raw token was the dictionary key
            migrated = False
            normalized = {}
            for k, val in raw_data.items():
                if k.startswith("zat_"):
                    tid = str(uuid.uuid4())
                    token_hash = hashlib.sha256(k.encode("utf-8")).hexdigest()
                    masked = k[:8] + "..." + k[-4:]
                    normalized[tid] = {
                        "hash": token_hash,
                        "masked_token": masked,
                        "name": val.get("name", "Legacy Token"),
                        "created": val.get("created", time.time()),
                    }
                    migrated = True
                elif isinstance(val, dict) and "hash" in val:
                    normalized[k] = val
                else:
                    # Generic fallback
                    normalized[k] = val

            if migrated:
                atomic_write_json(TOKENS_FILE, normalized)
                if os.path.exists(TOKENS_FILE):
                    mtime = os.stat(TOKENS_FILE).st_mtime_ns

            _TOKENS_CACHE = normalized
            _tokens_file_mtime_ns = mtime
            return _TOKENS_CACHE
        except Exception as e:
            logger.warning(f"Failed to load API tokens: {e}")
            _TOKENS_CACHE = {}
            _tokens_file_mtime_ns = 0
            return {}


def save_tokens(tokens: dict) -> None:
    """Thread-safe token persistence with atomic cache synchronization."""
    global _TOKENS_CACHE, _tokens_file_mtime_ns
    with _tokens_lock:
        atomic_write_json(TOKENS_FILE, tokens)
        _TOKENS_CACHE = dict(tokens)
        if os.path.exists(TOKENS_FILE):
            try:
                _tokens_file_mtime_ns = os.stat(TOKENS_FILE).st_mtime_ns
            except OSError:
                pass


def generate_token(name: str) -> str:
    """Generate a scoped API token, storing only its SHA-256 hash and returning the raw secret once."""
    tokens = load_tokens()
    raw_token = "zat_" + secrets.token_urlsafe(32)
    token_id = str(uuid.uuid4())
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    masked = raw_token[:8] + "..." + raw_token[-4:]

    tokens[token_id] = {
        "hash": token_hash,
        "masked_token": masked,
        "name": name,
        "created": time.time(),
    }
    save_tokens(tokens)
    return raw_token


def revoke_token(token_id_or_raw: str) -> bool:
    """Revoke a token by its UUID identifier or raw secret token."""
    if not token_id_or_raw:
        return False
    tokens = load_tokens()
    target_id = None

    # Check direct ID match (UUID)
    for tid in tokens.keys():
        if hmac.compare_digest(str(tid), str(token_id_or_raw)):
            target_id = tid
            break

    # Fallback: check if caller supplied raw token to revoke
    if not target_id and token_id_or_raw.startswith("zat_"):
        candidate_hash = hashlib.sha256(token_id_or_raw.encode("utf-8")).hexdigest()
        for tid, data in tokens.items():
            stored_hash = data.get("hash")
            if stored_hash and hmac.compare_digest(stored_hash, candidate_hash):
                target_id = tid
                break

    if target_id:
        del tokens[target_id]
        save_tokens(tokens)
        return True
    return False


def validate_api_token(token: str) -> bool:
    """Constant-time token validation against stored SHA-256 digests."""
    if not token or not token.startswith("zat_"):
        return False
    tokens = load_tokens()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    for item in tokens.values():
        stored_hash = item.get("hash")
        if stored_hash and hmac.compare_digest(token_hash, stored_hash):
            return True
    return False
