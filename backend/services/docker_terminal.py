"""
ZettNAS Toolkit - Interactive Docker Container Terminal Service
Provides multiplexed bidirectional PTY streaming over WebSockets via Docker Engine socket.
Supports ANSI terminal I/O, live character input, interactive shells (/bin/bash, /bin/sh),
and dynamic terminal resize events.
"""

import asyncio
import json
import os
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
from backend.config import logger

DOCKER_SOCK_PATH = "/var/run/docker.sock"


async def _docker_create_exec(container_id: str, shell: str = "/bin/sh") -> Optional[str]:
    """Creates an interactive exec instance in the target container."""
    try:
        reader, writer = await asyncio.open_unix_connection(DOCKER_SOCK_PATH)
        body = json.dumps(
            {
                "AttachStdin": True,
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": True,
                "Cmd": [shell],
            }
        ).encode("utf-8")

        req = (
            f"POST /containers/{container_id}/exec HTTP/1.1\r\n"
            f"Host: docker\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n"
        ).encode("utf-8") + body

        writer.write(req)
        await writer.drain()

        resp = await reader.read(4096)
        writer.close()
        await writer.wait_closed()

        resp_text = resp.decode("utf-8", errors="replace")
        if "\r\n\r\n" in resp_text:
            _, bdy = resp_text.split("\r\n\r\n", 1)
            parsed = json.loads(bdy)
            return parsed.get("Id")
    except Exception as e:
        logger.warning(f"[DockerTerminal] Failed to create exec instance for {container_id}: {e}")
    return None


async def _docker_resize_exec(exec_id: str, cols: int, rows: int) -> None:
    """Resizes the active exec PTY window."""
    try:
        reader, writer = await asyncio.open_unix_connection(DOCKER_SOCK_PATH)
        req = (f"POST /exec/{exec_id}/resize?h={rows}&w={cols} HTTP/1.1\r\nHost: docker\r\n\r\n").encode("utf-8")
        writer.write(req)
        await writer.drain()
        await reader.read(1024)
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        logger.debug(f"[DockerTerminal] Failed to resize exec {exec_id}: {e}")


async def stream_container_terminal(
    ws: WebSocket,
    container_id: str,
    shell: str = "/bin/sh",
) -> None:
    """
    Bridges an active WebSocket connection to an interactive PTY session inside
    the target Docker container via /var/run/docker.sock.
    """
    if not os.path.exists(DOCKER_SOCK_PATH):
        await ws.send_text("\r\n\x1b[31m[Error] Docker socket (/var/run/docker.sock) not accessible.\x1b[0m\r\n")
        await ws.close(code=1011, reason="Docker socket unavailable")
        return

    # 1. Create Exec Instance
    exec_id = await _docker_create_exec(container_id, shell)
    if not exec_id and shell != "/bin/sh":
        # Fallback to /bin/sh if bash wasn't found
        exec_id = await _docker_create_exec(container_id, "/bin/sh")

    if not exec_id:
        await ws.send_text(
            f"\r\n\x1b[31m[Error] Unable to initialize interactive shell in container '{container_id}'.\x1b[0m\r\n"
        )
        await ws.close(code=1011, reason="Exec creation failed")
        return

    # 2. Connect and Hijack via HTTP Upgrade
    try:
        reader, writer = await asyncio.open_unix_connection(DOCKER_SOCK_PATH)
        start_body = json.dumps({"Detach": False, "Tty": True}).encode("utf-8")
        start_req = (
            f"POST /exec/{exec_id}/start HTTP/1.1\r\n"
            f"Host: docker\r\n"
            f"Content-Type: application/json\r\n"
            f"Connection: Upgrade\r\n"
            f"Upgrade: tcp\r\n"
            f"Content-Length: {len(start_body)}\r\n\r\n"
        ).encode("utf-8") + start_body

        writer.write(start_req)
        await writer.drain()

        # Read past HTTP 101 UPGRADED header
        header_buf = b""
        while b"\r\n\r\n" not in header_buf:
            chunk = await reader.read(1024)
            if not chunk:
                break
            header_buf += chunk

        if b"\r\n\r\n" in header_buf:
            leftover = header_buf.split(b"\r\n\r\n", 1)[1]
            if leftover:
                await ws.send_text(leftover.decode("utf-8", errors="replace"))
        else:
            await ws.send_text("\r\n\x1b[31m[Error] Docker upgrade protocol failed.\x1b[0m\r\n")
            writer.close()
            await ws.close(code=1011, reason="Upgrade failed")
            return

    except Exception as e:
        logger.error(f"[DockerTerminal] Error hijacking docker exec stream: {e}")
        await ws.close(code=1011, reason=f"Stream error: {e}")
        return

    # 3. Bidirectional Async Forwarding Loops
    async def forward_docker_to_ws():
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                # Send raw ANSI terminal stream
                await ws.send_text(data.decode("utf-8", errors="replace"))
        except (asyncio.CancelledError, Exception):
            pass

    async def forward_ws_to_docker():
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break

                if "text" in msg and msg["text"]:
                    raw_text = msg["text"]
                    # Check for JSON control frames (e.g. resize or structured input)
                    if raw_text.startswith("{") and raw_text.endswith("}"):
                        try:
                            parsed = json.loads(raw_text)
                            if parsed.get("type") == "resize":
                                cols = int(parsed.get("cols", 80))
                                rows = int(parsed.get("rows", 24))
                                asyncio.create_task(_docker_resize_exec(exec_id, cols, rows))
                                continue
                            elif parsed.get("type") == "input" and "data" in parsed:
                                writer.write(parsed["data"].encode("utf-8"))
                                await writer.drain()
                                continue
                        except Exception:
                            pass

                    # Regular raw text / keystroke input
                    writer.write(raw_text.encode("utf-8"))
                    await writer.drain()

                elif "bytes" in msg and msg["bytes"]:
                    writer.write(msg["bytes"])
                    await writer.drain()

        except WebSocketDisconnect:
            pass
        except (asyncio.CancelledError, Exception):
            pass

    t_docker = asyncio.create_task(forward_docker_to_ws())
    t_ws = asyncio.create_task(forward_ws_to_docker())

    try:
        done, pending = await asyncio.wait([t_docker, t_ws], return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
