import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_stream_docker_container_logs_socket_missing(client):
    """
    When docker.sock does not exist (or in mock env), stream endpoint should gracefully
    fall back to get_container_logs_chunk and yield events before completing.
    """
    mock_chunk = {
        "lines": [
            {"stream": "stdout", "ts": "2026-10-19T12:00:00Z", "msg": "Starting server..."},
            {
                "stream": "stderr",
                "ts": "2026-10-19T12:00:01Z",
                "msg": "Warning: config file not found, using defaults.",
            },
        ],
        "total": 2,
    }

    with (
        patch("os.path.exists", return_value=False),
        patch("backend.services.compose_synthesizer.get_container_logs_chunk", return_value=mock_chunk),
    ):
        headers = {"Authorization": "Bearer admin-token-test", "Cookie": "zettnas_session=admin-token-test"}
        with patch(
            "backend.auth.validate_user_session",
            return_value={"user_id": "u1", "username": "admin", "role_id": "superadmin", "scopes": ["*"]},
        ):
            response = client.get(
                "/api/docker/containers/c_test_123/logs/stream?tail=50&follow=false",
                headers=headers,
            )
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            content = response.text
            assert "Starting server..." in content
            assert "Warning: config file not found" in content
            assert "event: done" in content


def test_stream_docker_container_logs_socket_multiplexed(client):
    """
    Test streaming logs over simulated Unix socket connection with 8-byte Docker multiplex header.
    """
    import struct

    log_msg = b"2026-10-19T12:00:00.123456789Z Container healthy and serving traffic\n"
    hdr = b"\x01\x00\x00\x00" + struct.pack(">I", len(log_msg))
    http_data = b"HTTP/1.1 200 OK\r\n\r\n" + hdr + log_msg

    class MockReader:
        def __init__(self, data: bytes):
            self.data = data
            self.pos = 0

        async def read(self, n=-1):
            if self.pos >= len(self.data):
                return b""
            chunk = self.data[self.pos : self.pos + n]
            self.pos += len(chunk)
            return chunk

    class MockWriter:
        def write(self, data):
            pass

        async def drain(self):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    mock_reader = MockReader(http_data)
    mock_writer = MockWriter()

    with (
        patch("os.path.exists", return_value=True),
        patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer)),
        patch(
            "backend.auth.validate_user_session",
            return_value={"user_id": "u1", "username": "admin", "role_id": "superadmin", "scopes": ["*"]},
        ),
    ):
        headers = {"Authorization": "Bearer admin-token-test", "Cookie": "zettnas_session=admin-token-test"}
        response = client.get(
            "/api/docker/containers/c_test_123/logs/stream?tail=50&follow=false",
            headers=headers,
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        content = response.text
        assert "Container healthy and serving traffic" in content
        assert "event: done" in content
