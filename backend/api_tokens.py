import json
import os
import secrets

from backend.config import DATA_DIR, logger

TOKENS_FILE = os.path.join(DATA_DIR, "api_tokens.json")
# Format: { "token": { "name": "...", "created": ts } }

def load_tokens() -> dict:
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load API tokens: {e}")
    return {}

def save_tokens(tokens: dict):
    from backend.fsutil import atomic_write_json
    atomic_write_json(TOKENS_FILE, tokens)

def generate_token(name: str) -> str:
    import time
    tokens = load_tokens()
    # Scoped token prefix
    raw_token = "zat_" + secrets.token_urlsafe(32)
    tokens[raw_token] = {
        "name": name,
        "created": time.time()
    }
    save_tokens(tokens)
    return raw_token

def revoke_token(token: str):
    tokens = load_tokens()
    if token in tokens:
        del tokens[token]
        save_tokens(tokens)
        return True
    return False

def validate_api_token(token: str) -> bool:
    if not token or not token.startswith("zat_"):
        return False
    tokens = load_tokens()
    return token in tokens
