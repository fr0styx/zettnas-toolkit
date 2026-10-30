"""Single-use tickets: stream tickets (SSE/WebSocket, 60 s) and VM console tickets.

Shared by the auth middleware and the API, so they live outside the API layer (ARCH-2).
"""

import threading
import time
from typing import Any

# VM console tickets: ticket -> {"vm_id", "user_id", "username", "created_at", "expires_at"}
CONSOLE_TICKETS: dict[str, dict[str, Any]] = {}

STREAM_TICKETS: dict[str, dict[str, Any]] = {}
STREAM_TICKETS_LOCK = threading.RLock()


def create_stream_ticket(
    user_id: str, username: str, scopes: list[str], role_id: str, folders: list[str] | None = None, token_id: str = ""
) -> str:
    """A token's folder limit goes into its tickets: a ticket must not reach more than the
    credential that asked for it (NSEC-1)."""
    import secrets

    ticket = f"zst_{secrets.token_urlsafe(32)}"
    now = time.time()
    with STREAM_TICKETS_LOCK:
        expired = [k for k, v in STREAM_TICKETS.items() if v["expires_at"] < now]
        for k in expired:
            STREAM_TICKETS.pop(k, None)

        STREAM_TICKETS[ticket] = {
            "user_id": user_id,
            "username": username,
            "scopes": scopes,
            "role_id": role_id,
            "folders": list(folders or []),
            "token_id": token_id,
            "expires_at": now + 60,
        }
    return ticket


def validate_and_consume_stream_ticket(ticket: str) -> dict[str, Any] | None:
    if not ticket or not ticket.startswith("zst_"):
        return None
    now = time.time()
    with STREAM_TICKETS_LOCK:
        entry = STREAM_TICKETS.pop(ticket, None)
        if entry and entry.get("expires_at", 0) > now:
            return {
                "user_id": entry["user_id"],
                "username": entry["username"],
                "role_id": entry["role_id"],
                "scopes": entry["scopes"],
                "folders": list(entry.get("folders") or []),
                "token_id": entry.get("token_id", ""),
                "is_stream_ticket": True,
            }
    return None
