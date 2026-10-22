"""
Unit & Integration Tests for VM Console Proxy and WebSockets
Tests RFB VNC streaming, serial PTY console, ticket authorization, and timeout handling.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from backend.services.console_proxy import (
    stream_socket_to_websocket,
    stream_unix_socket_to_websocket,
)


@pytest.mark.asyncio
async def test_stream_socket_to_websocket_connection_refusal():
    # Mock WebSocket
    mock_ws = AsyncMock()
    mock_ws.close = AsyncMock()

    # Attempt connecting to non-existent port
    await stream_socket_to_websocket(mock_ws, "127.0.0.1", 59999, timeout_sec=0.2)

    # Should close with code 1011
    mock_ws.close.assert_called_once()
    assert mock_ws.close.call_args[1]["code"] == 1011


@pytest.mark.asyncio
async def test_stream_unix_socket_missing_sends_banner():
    mock_ws = AsyncMock()
    mock_ws.send_text = AsyncMock()
    mock_ws.close = AsyncMock()

    await stream_unix_socket_to_websocket(mock_ws, "/tmp/non_existent_serial_socket_12345.sock", timeout_sec=0.2)

    mock_ws.send_text.assert_called_once()
    assert "Waiting for serial socket" in mock_ws.send_text.call_args[0][0]
    mock_ws.close.assert_called_once()
    assert mock_ws.close.call_args[1]["code"] == 1011


def test_websocket_routes_unauthorized_without_ticket(client):
    # Attempting to connect without a ticket or with invalid ticket should close with code 1008
    with pytest.raises(Exception):  # noqa: B017
        with client.websocket_connect("/api/vms/vm-123/console/ws?ticket=invalid_ticket") as ws:
            pass

    with pytest.raises(Exception):  # noqa: B017
        with client.websocket_connect("/api/vms/vm-123/serial/ws?ticket=invalid_ticket") as ws:
            pass


@pytest.mark.asyncio
async def test_stream_unix_socket_crlf_normalization():
    mock_ws = AsyncMock()
    mock_ws.receive = AsyncMock(
        side_effect=[
            {"type": "websocket.receive", "text": "echo test\r\n"},
            {"type": "websocket.receive", "bytes": b"status\r\n"},
            {"type": "websocket.receive", "text": "bad\x08cmd"},
            {"type": "websocket.receive", "bytes": b"raw\x08byte"},
            {"type": "websocket.disconnect"},
        ]
    )
    mock_writer = MagicMock()
    mock_writer.write = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    mock_reader = AsyncMock()
    mock_reader.read = AsyncMock(return_value=b"")

    with patch("os.path.exists", return_value=True):
        with patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer)):
            await stream_unix_socket_to_websocket(mock_ws, "/tmp/test.sock")

    # Both text and bytes must have \r\n normalized to single \r and \x08 normalized to \x7f
    mock_writer.write.assert_any_call(b"echo test\r")
    mock_writer.write.assert_any_call(b"status\r")
    mock_writer.write.assert_any_call(b"bad\x7fcmd")
    mock_writer.write.assert_any_call(b"raw\x7fbyte")
