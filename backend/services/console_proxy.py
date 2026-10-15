"""
ZettNAS VM Console Proxy Service
Provides multiplexed bidirectional streaming between WebSockets and QEMU VNC / serial sockets.
Supports RFB binary frames for graphical consoles and ANSI text for serial PTY consoles.
"""

import asyncio
import os
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
from backend.config import logger


async def stream_socket_to_websocket(ws: WebSocket, host: str, port: int, timeout_sec: float = 3.0):
    """
    Bridges a TCP RFB (VNC) socket to an active WebSocket connection.
    Forwards binary frame buffers from QEMU to browser and user pointer/keyboard events back to QEMU.
    """
    reader, writer = None, None
    for attempt in range(8):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout_sec,
            )
            break
        except (OSError, asyncio.TimeoutError) as e:
            if attempt < 7:
                await asyncio.sleep(0.5)
            else:
                logger.warning(
                    f"[ConsoleProxy] Failed connecting to VM VNC socket at {host}:{port} after 8 attempts - {e}"
                )
                try:
                    await ws.close(code=1011, reason=f"Cannot connect to VM display socket: {e}")
                except Exception:
                    pass
                return

    async def forward_tcp_to_ws():
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await ws.send_bytes(data)
        except Exception:
            pass

    async def forward_ws_to_tcp():
        try:
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if "bytes" in message and message["bytes"]:
                    writer.write(message["bytes"])
                    await writer.drain()
                elif "text" in message and message["text"]:
                    writer.write(message["text"].encode("utf-8"))
                    await writer.drain()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    t1 = asyncio.create_task(forward_tcp_to_ws())
    t2 = asyncio.create_task(forward_ws_to_tcp())
    try:
        done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def stream_unix_socket_to_websocket(ws: WebSocket, socket_path: str, timeout_sec: float = 3.0):
    """
    Bridges a UNIX domain socket (QEMU guest serial PTY / chardev) to an active WebSocket connection.
    Transmits ANSI terminal I/O for interactive serial console access.
    """
    reader, writer = None, None
    for attempt in range(8):
        if not os.path.exists(socket_path):
            if attempt < 7:
                await asyncio.sleep(0.5)
                continue
            banner = (
                f"\r\n\x1b[33m[ZettNAS Serial Console]\x1b[0m Waiting for serial socket at '{socket_path}'...\r\n"
                f"\x1b[90mEnsure VM is running and serial socket is initialized.\x1b[0m\r\n"
            )
            try:
                await ws.send_text(banner)
                await asyncio.sleep(0.5)
                await ws.close(code=1011, reason=f"Serial socket '{socket_path}' not available.")
            except Exception:
                pass
            return

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(socket_path),
                timeout=timeout_sec,
            )
            break
        except (OSError, asyncio.TimeoutError) as e:
            if attempt < 7:
                await asyncio.sleep(0.5)
            else:
                logger.warning(f"[ConsoleProxy] Failed opening UNIX socket {socket_path} after 8 attempts: {e}")
                try:
                    await ws.close(code=1011, reason=f"Cannot connect to serial socket: {e}")
                except Exception:
                    pass
                return

    async def forward_sock_to_ws():
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                try:
                    await ws.send_text(data.decode("utf-8", errors="replace"))
                except Exception:
                    await ws.send_bytes(data)
        except Exception:
            pass

    async def forward_ws_to_sock():
        try:
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if "text" in message and message["text"]:
                    data_str = message["text"].replace("\r\n", "\r").replace("\x08", "\x7f")
                    writer.write(data_str.encode("utf-8"))
                    await writer.drain()
                elif "bytes" in message and message["bytes"]:
                    data_bytes = message["bytes"].replace(b"\r\n", b"\r").replace(b"\x08", b"\x7f")
                    writer.write(data_bytes)
                    await writer.drain()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    t1 = asyncio.create_task(forward_sock_to_ws())
    t2 = asyncio.create_task(forward_ws_to_sock())
    try:
        done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
