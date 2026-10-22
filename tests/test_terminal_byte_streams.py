"""Terminal WebSockets forward raw bytes so split UTF-8 characters survive."""

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

from backend.services.console_proxy import stream_unix_socket_to_websocket

SPLIT = "é→✓".encode()  # multi-byte characters


def test_serial_proxy_sends_bytes_unchanged_across_split_reads():
    async def run():
        d = tempfile.mkdtemp(prefix="ser")
        path = os.path.join(d, "s.sock")

        async def handle(reader, writer):
            # split in the middle of a multi-byte character
            writer.write(b"boot " + SPLIT[:3])
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.write(SPLIT[3:] + b"\r\n")
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.close()

        server = await asyncio.start_unix_server(handle, path=path)
        ws = MagicMock()
        ws.send_bytes = AsyncMock()
        ws.send_text = AsyncMock()

        async def receive():
            await asyncio.sleep(1)
            return {"type": "websocket.disconnect"}

        ws.receive = receive
        ws.close = AsyncMock()
        try:
            await asyncio.wait_for(stream_unix_socket_to_websocket(ws, path), 5)
        finally:
            server.close()
        sent = b"".join(c.args[0] for c in ws.send_bytes.call_args_list)
        assert sent == b"boot " + SPLIT + b"\r\n"
        assert sent.decode("utf-8") == "boot é→✓\r\n"
        # no lossy per-chunk text decoding
        for c in ws.send_text.call_args_list:
            assert "�" not in c.args[0]

    asyncio.run(run())


def test_docker_terminal_forwards_bytes():
    import inspect

    from backend.services import docker_terminal

    src = inspect.getsource(docker_terminal.stream_container_terminal)
    assert "await ws.send_bytes(data)" in src
    assert 'data.decode("utf-8", errors="replace")' not in src
