import asyncio
import json
from typing import Any

from backend.config import logger
from backend.fast_json import dumps as fast_dumps


class StatsBroadcaster:
    """
    Centralized SSE Broadcaster:
    - Eliminates redundant per-client polling loops.
    - Serializes stats payload once and fans out to all active client queues.
    - Pushes immediately when hardware/state updates occur (0ms reaction time).
    - Drops stale frames for slow clients using bounded queues.
    """

    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()
        self._latest_payload: str | None = None
        self._latest_full_data: dict[str, Any] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def get_subscriber_count(self) -> int:
        return len(self._subscribers)

    async def subscribe(self, initial_data: dict[str, Any] | None = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=10)

        # Immediately send complete snapshot to newly connected client before registering
        full_data = initial_data or self._latest_full_data
        if full_data is not None:
            payload = f"data: {fast_dumps(full_data)}\n\n"
            await q.put(payload)
        elif self._latest_payload is not None:
            await q.put(self._latest_payload)

        self._subscribers.add(q)
        return q

    def shutdown(self) -> None:
        """Signal all active subscriber queues to cleanly exit."""
        for q in list(self._subscribers):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(None)
            except Exception:
                logger.debug("backend.services.broadcaster.StatsBroadcaster.shutdown: ignored error", exc_info=True)
        self._subscribers.clear()

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _snapshot_payload(self) -> str | None:
        if self._latest_full_data is None:
            return None
        try:
            return f"data: {fast_dumps(self._latest_full_data)}\n\n"
        except (TypeError, ValueError):
            return None

    def _deliver(self, payload: str) -> None:
        self._latest_payload = payload
        snapshot: str | None = None
        dead_queues = []
        for q in list(self._subscribers):
            try:
                if q.full():
                    # Live messages are deltas, so a client that fell behind must not
                    # just lose one: clear its backlog and resync it with a full snapshot.
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    if snapshot is None:
                        snapshot = self._snapshot_payload() or payload
                    q.put_nowait(snapshot)
                else:
                    q.put_nowait(payload)
            except Exception as e:
                logger.debug(f"[BROADCASTER] Failed delivering to subscriber: {e}")
                dead_queues.append(q)

        for q in dead_queues:
            self._subscribers.discard(q)

    def broadcast(self, data: dict[str, Any], full_data: dict[str, Any] | None = None) -> None:
        """Broadcast data to all connected clients. Thread-safe."""
        if full_data is not None:
            self._latest_full_data = full_data
        elif self._latest_full_data is None:
            self._latest_full_data = data

        try:
            payload = f"data: {fast_dumps(data)}\n\n"
        except (TypeError, ValueError) as e:
            logger.warning(f"[BROADCASTER] Serialization error: {e}")
            return

        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._deliver, payload)
            except RuntimeError:
                pass
        else:
            # Fallback if running synchronously or loop not yet set
            self._latest_payload = payload


# Global singleton broadcaster
broadcaster = StatsBroadcaster()
