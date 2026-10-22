"""
Persistent QMP (QEMU Machine Protocol) engine.

Each running VM gets one long-lived connection to its QMP monitor socket
instead of a new socket per command. QEMU's monitor serves one client at a
time, so every QMP call in the app goes through this engine.

- Commands carry an "id" and replies are matched by it, so concurrent
  commands never receive each other's answers or a stray event.
- Asynchronous QEMU events (SHUTDOWN, RESET, STOP, RESUME, GUEST_PANICKED...)
  are passed to an `on_event(vm_id, event, data)` callback.
- Connections reopen on the next command after QEMU restarts or drops them.

The engine runs its own asyncio loop on a daemon thread, so sync code (called
via asyncio.to_thread) and async code can both use it.
"""

import asyncio
import json
import os
import threading
from collections.abc import Callable
from typing import Any, Optional

from backend.config import logger

EventCallback = Callable[[str, str, dict[str, Any]], None]


class PersistentQmpClient:
    def __init__(self, vm_id: str, sock_path: str, on_event: EventCallback | None = None):
        self.vm_id = vm_id
        self.sock_path = sock_path
        self.on_event = on_event
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._listener: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._seq = 0
        self._connect_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def _read_json(self) -> dict[str, Any]:
        line = await self._reader.readline()
        if not line:
            raise ConnectionError("QMP connection closed")
        return json.loads(line.decode("utf-8", errors="replace"))

    async def connect(self, timeout: float = 2.5) -> None:
        async with self._connect_lock:
            if self.connected:
                return
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.sock_path, limit=4 * 1024 * 1024), timeout
            )
            try:
                greeting = await asyncio.wait_for(self._read_json(), timeout)
                if "QMP" not in greeting:
                    raise ConnectionError("unexpected QMP greeting")
                self._writer.write(b'{"execute": "qmp_capabilities", "id": 0}\n')
                await self._writer.drain()
                while True:  # events may arrive before the capabilities reply
                    msg = await asyncio.wait_for(self._read_json(), timeout)
                    if msg.get("id") == 0:
                        if "error" in msg:
                            raise ConnectionError(f"qmp_capabilities failed: {msg['error']}")
                        break
                    if "event" in msg:
                        self._dispatch_event(msg)
            except BaseException:
                self._drop()
                raise
            self._listener = asyncio.ensure_future(self._listen())

    def _dispatch_event(self, msg: dict[str, Any]) -> None:
        if not self.on_event:
            return
        loop = asyncio.get_running_loop()
        # Callbacks may touch disk (event log); keep them off the engine loop.
        loop.run_in_executor(None, self._safe_event, msg.get("event", ""), msg.get("data") or {})

    def _safe_event(self, event: str, data: dict[str, Any]) -> None:
        try:
            self.on_event(self.vm_id, event, data)
        except Exception as e:
            logger.debug(f"[QMP-{self.vm_id}] event handler failed for {event}: {e}")

    async def _listen(self) -> None:
        try:
            while True:
                msg = await self._read_json()
                if "event" in msg:
                    self._dispatch_event(msg)
                    continue
                fut = self._pending.pop(msg.pop("id", None), None)
                if fut is not None and not fut.done():
                    fut.set_result(msg)  # same shape as before: {"return": ...} or {"error": ...}
        except (ConnectionError, OSError, ValueError, asyncio.IncompleteReadError):
            pass
        except asyncio.CancelledError:
            raise
        finally:
            self._drop()

    def _drop(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                logger.debug("backend.services.vm_engine.PersistentQmpClient._drop: ignored error", exc_info=True)
        self._reader = self._writer = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result({"error": "QMP connection closed"})
        self._pending.clear()

    async def execute(
        self, command: str, arguments: dict[str, Any] | None = None, timeout: float = 2.5
    ) -> dict[str, Any]:
        """Runs a QMP command. Returns QEMU's reply ({"return": ...} or {"error": ...})."""
        try:
            await self.connect(timeout)
        except (TimeoutError, OSError, ConnectionError, ValueError) as e:
            return {"error": f"QMP connect failed: {e or e.__class__.__name__}"}
        self._seq += 1
        seq = self._seq
        payload: dict[str, Any] = {"execute": command, "id": seq}
        if arguments:
            payload["arguments"] = arguments
        fut = asyncio.get_running_loop().create_future()
        self._pending[seq] = fut
        try:
            self._writer.write(json.dumps(payload).encode("utf-8") + b"\n")
            await self._writer.drain()
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            return {"error": f"QMP command '{command}' timed out after {timeout:g}s"}
        except (OSError, ConnectionError, AttributeError) as e:
            self._drop()
            return {"error": f"QMP command '{command}' failed: {e}"}
        finally:
            self._pending.pop(seq, None)

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            try:
                await self._listener
            except (asyncio.CancelledError, Exception):
                logger.debug("backend.services.vm_engine.PersistentQmpClient.close: ignored error", exc_info=True)
            self._listener = None
        self._drop()


class QmpEngine:
    """One PersistentQmpClient per VM, driven from a private asyncio loop thread."""

    def __init__(self, sock_path_fn: Callable[[str], str], on_event: EventCallback | None = None):
        self._sock_path_fn = sock_path_fn
        self.on_event = on_event
        self._clients: dict[str, PersistentQmpClient] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or not self._thread or not self._thread.is_alive():
                loop = asyncio.new_event_loop()
                ready = threading.Event()

                def run():
                    asyncio.set_event_loop(loop)
                    loop.call_soon(ready.set)
                    loop.run_forever()

                self._thread = threading.Thread(target=run, daemon=True, name="qmp-engine")
                self._thread.start()
                ready.wait(5)
                self._loop = loop
            return self._loop

    def _client(self, vm_id: str) -> PersistentQmpClient:
        client = self._clients.get(vm_id)
        path = self._sock_path_fn(vm_id)
        if client is None or client.sock_path != path:
            client = PersistentQmpClient(vm_id, path, lambda v, e, d: self.on_event and self.on_event(v, e, d))
            self._clients[vm_id] = client
        return client

    def _submit(self, coro_fn, timeout: float):
        loop = self._ensure_loop()

        async def runner():
            return await coro_fn()

        return asyncio.run_coroutine_threadsafe(runner(), loop).result(timeout)

    def execute(
        self, vm_id: str, command: str, arguments: dict[str, Any] | None = None, timeout: float = 2.5
    ) -> dict[str, Any]:
        """Blocking QMP call (use from threads, e.g. via asyncio.to_thread)."""
        path = self._sock_path_fn(vm_id)
        if not os.path.exists(path):
            return {"error": f"QMP monitor socket '{path}' not found."}
        try:
            return self._submit(lambda: self._client(vm_id).execute(command, arguments, timeout), timeout * 2 + 2)
        except Exception as e:
            return {"error": f"QMP engine error: {e or e.__class__.__name__}"}

    def watch(self, vm_id: str, attempts: int = 20, interval: float = 0.25) -> None:
        """Connects in the background once QEMU has created its socket, so events flow."""
        loop = self._ensure_loop()

        async def connect_when_ready():
            client = self._client(vm_id)
            for _ in range(attempts):
                if os.path.exists(client.sock_path):
                    try:
                        await client.connect()
                        return
                    except Exception:
                        logger.debug(
                            "backend.services.vm_engine.QmpEngine.watch.connect_when_ready: ignored error",
                            exc_info=True,
                        )
                await asyncio.sleep(interval)
            logger.debug(f"[QMP-{vm_id}] monitor socket did not become ready for event watching")

        asyncio.run_coroutine_threadsafe(connect_when_ready(), loop)

    def close(self, vm_id: str) -> None:
        """Drops the VM's connection (call before QEMU's sockets are removed)."""
        client = self._clients.pop(vm_id, None)
        if client is None or self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(client.close(), self._loop).result(3)
        except Exception:
            logger.debug("backend.services.vm_engine.QmpEngine.close: ignored error", exc_info=True)

    def is_connected(self, vm_id: str) -> bool:
        client = self._clients.get(vm_id)
        return bool(client and client.connected)
