"""
Simple sliding-window rate limits for expensive or abusable endpoints.

    @router.post("/ai/chat", dependencies=[Depends(rate_limit("ai.chat", 20, 60))])

Keys are per user (signed-in requests) or per client address (public routes).
Over the limit the request gets 429 with Retry-After. Counters are in memory:
they protect against floods, not against a determined attacker across restarts.
"""

import threading
import time
from collections import deque
from typing import Deque, Dict

from fastapi import HTTPException, Request

_hits: Dict[str, Deque[float]] = {}
_lock = threading.Lock()
_MAX_KEYS = 20000


def hit(key: str, limit: int, window: float) -> int:
    """Records one request; returns 0 if allowed, else seconds until the next one is."""
    now = time.time()
    with _lock:
        q = _hits.get(key)
        if q is None:
            if len(_hits) >= _MAX_KEYS:
                for k in [k for k, v in _hits.items() if not v or now - v[-1] > window][: _MAX_KEYS // 4]:
                    _hits.pop(k, None)
            q = _hits[key] = deque()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return max(1, int(window - (now - q[0])) + 1)
        q.append(now)
        return 0


def reset() -> None:
    with _lock:
        _hits.clear()


def rate_limit(name: str, limit: int, window: float, per: str = "user"):
    """FastAPI dependency: at most `limit` requests per `window` seconds per user (or per IP)."""

    async def _dep(request: Request) -> None:
        sess = getattr(request.state, "session", None) or {}
        who = ""
        if per == "user":
            who = str(sess.get("user_id") or sess.get("username") or "")
        if not who:
            from backend.auth import client_ip

            who = "ip:" + client_ip(request)
        wait = hit(f"{name}:{who}", limit, window)
        if wait:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Try again in {wait}s.",
                headers={"Retry-After": str(wait)},
            )

    return _dep
