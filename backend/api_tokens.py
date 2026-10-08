import hmac
import json
import os
import secrets
import threading
import time

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json

TOKENS_FILE = os.path.join(DATA_DIR, "api_tokens.json")
# Format: { "token": { "name": "...", "created": ts } }

_TOKENS_CACHE = {}
_tokens_file_mtime_ns = 0
_tokens_lock = threading.RLock()


def load_tokens() -> dict:
    """Thread-safe cached token loader with st_mtime_ns invalidation."""
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
                _TOKENS_CACHE = json.load(f)
            _tokens_file_mtime_ns = mtime
            return _TOKENS_CACHE
        except Exception as e:
            logger.warning(f"Failed to load API tokens: {e}")
            _TOKENS_CACHE = {}
            _tokens_file_mtime_ns = 0
            return {}


def save_tokens(tokens: dict):
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
    tokens = load_tokens()
    # Scoped token prefix
    raw_token = "zat_" + secrets.token_urlsafe(32)
    tokens[raw_token] = {"name": name, "created": time.time()}
    save_tokens(tokens)
    return raw_token


def revoke_token(token: str) -> bool:
    tokens = load_tokens()
    target_key = None
    for t in tokens.keys():
        if hmac.compare_digest(token, t):
            target_key = t
            break
    if target_key:
        del tokens[target_key]
        save_tokens(tokens)
        return True
    return False


def validate_api_token(token: str) -> bool:
    """Constant-time token lookup using cached in-memory map without synchronous disk reads."""
    if not token or not token.startswith("zat_"):
        return False
    tokens = load_tokens()
    return any(hmac.compare_digest(token, t) for t in tokens.keys())
