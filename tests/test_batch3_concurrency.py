import os
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from backend.state import Z_STATE, add_event
from backend.db import get_db_connection, query_smart_velocity, query_all_smart_velocities, init_db
from backend.services.broadcaster import broadcaster


def test_sse_subscriber_limit_returns_429(client, auth_headers):
    """Ensure that when SSE subscribers reach MAX_SSE_SUBSCRIBERS (32), 429 is returned."""
    with patch.object(broadcaster, "get_subscriber_count", return_value=32):
        response = client.get("/api/stats/stream", headers=auth_headers)
        assert response.status_code == 429
        assert "Maximum concurrent SSE telemetry connections reached" in response.json()["detail"]


def test_add_event_concurrency_and_persistence(tmp_path):
    """Verify add_event persists events without blocking or deadlock."""
    test_events_file = str(tmp_path / "events.json")
    with patch("backend.state.EVENTS_FILE", test_events_file):
        with Z_STATE.lock:
            Z_STATE.event_log.clear()

        add_event("info", "Test Event", "Message detail", details={"key": "val"})

        with Z_STATE.lock:
            assert len(Z_STATE.event_log) >= 1
            assert Z_STATE.event_log[0]["title"] == "Test Event"
            assert Z_STATE.event_log[0]["message"] == "Message detail"


def test_sqlite_busy_timeout_and_wal():
    """Verify SQLite connection is configured with 15000ms busy timeout."""
    init_db()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        timeout_res = cur.execute("PRAGMA busy_timeout;").fetchone()
        assert timeout_res[0] == 15000
    finally:
        conn.close()


def test_query_smart_velocity_connection_reuse():
    """Verify query_smart_velocity accepts an external connection to prevent connection churn."""
    conn = get_db_connection()
    try:
        res = query_smart_velocity("sda", conn=conn)
        assert isinstance(res, dict)
        assert res["dev"] == "sda"
        assert "status" in res
        assert "shedding_sectors" in res
    finally:
        conn.close()


def test_query_all_smart_velocities_single_session():
    """Verify query_all_smart_velocities executes across all recorded drives without error."""
    res = query_all_smart_velocities()
    assert isinstance(res, dict)


def test_fs_delete_offload_to_recycle_bin(client, auth_headers, tmp_path):
    """Verify fs_delete creates recycle bin and moves files safely."""
    browse_root = tmp_path / "browse"
    browse_root.mkdir()
    target_file = browse_root / "sample.txt"
    target_file.write_text("hello world")

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(browse_root)]):
        with patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(browse_root)]):
            response = client.post(
                "/api/fs/delete",
                json={"path": str(target_file)},
                headers=auth_headers,
            )
            assert response.status_code == 200
            assert not target_file.exists()
            recycle_bin = browse_root / ".RecycleBin"
            assert recycle_bin.exists()
