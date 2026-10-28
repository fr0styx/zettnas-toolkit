"""When someone last chatted with the AI, and when background re-indexing may run.

A module without dependencies, so the chat runtime, the indexer and the schedulers can all read it
without importing each other (AI-14, AI-30).
"""

import time

CHAT_BUSY_SECS = 120.0
_LAST_CHAT = {"at": 0.0}
UPGRADE_HOURS = (1, 6)  # files indexed the old way are re-made between 01:00 and 06:00 (AI-30)


def mark_chat_activity() -> None:
    """Someone is chatting: background model work waits (AI-14)."""
    _LAST_CHAT["at"] = time.time()


def chat_recently_active(now: float | None = None) -> bool:
    return (now or time.time()) - _LAST_CHAT["at"] < CHAT_BUSY_SECS


def upgrade_window_open(now: float | None = None) -> bool:
    """Night, and nobody chatting: the re-index of older entries may run (AI-30). A file that
    changed is always re-indexed at once; this only holds back re-making unchanged ones."""
    hour = time.localtime(now).tm_hour
    return UPGRADE_HOURS[0] <= hour < UPGRADE_HOURS[1] and not chat_recently_active(now)
