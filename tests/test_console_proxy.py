"""
Unit & Integration Tests for VM Console Proxy and WebSockets
Tests RFB VNC streaming, serial PTY console, ticket authorization, and timeout handling.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
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
    with pytest.raises(Exception):
        with client.websocket_connect("/api/vms/vm-123/console/ws?ticket=invalid_ticket") as ws:
            pass

    with pytest.raises(Exception):
        with client.websocket_connect("/api/vms/vm-123/serial/ws?ticket=invalid_ticket") as ws:
            pass
