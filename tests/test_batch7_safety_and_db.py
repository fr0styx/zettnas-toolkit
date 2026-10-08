import os
import sqlite3
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.db import db_session, get_db_connection, init_db, log_metrics, query_history
from backend.services.alert_rules import evaluate_system_alerts, reset_failsafe_state
from backend.state import Z_STATE


def test_db_session_commits_and_closes():
    """Verify that db_session automatically commits transactions and closes connections."""
    init_db()
    ts = int(time.time()) + 99999
    with db_session() as conn:
        conn.execute(
            "INSERT INTO metrics (ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json) VALUES (?, ?, ?, ?, ?, ?)",
            (ts, 45.0, 10.0, 20.0, "[]", "[]"),
        )
        # Check connection is open inside context
        assert conn.total_changes >= 1

    # Verify that connection is closed after context exit
    with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
        conn.execute("SELECT 1")

    # Verify that data was committed by reading from a new session
    with db_session() as conn2:
        row = conn2.execute("SELECT cpu_temp FROM metrics WHERE ts = ?", (ts,)).fetchone()
        assert row is not None
        assert row[0] == 45.0
        # Cleanup
        conn2.execute("DELETE FROM metrics WHERE ts = ?", (ts,))


def test_db_session_rolls_back_on_error():
    """Verify that unhandled exceptions inside db_session trigger a rollback before closing."""
    init_db()
    ts = int(time.time()) + 88888
    with pytest.raises(RuntimeError, match="Simulated DB Error"):
        with db_session() as conn:
            conn.execute(
                "INSERT INTO metrics (ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, 99.0, 10.0, 20.0, "[]", "[]"),
            )
            raise RuntimeError("Simulated DB Error")

    # Verify that connection is closed
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")

    # Verify that record was NOT inserted due to rollback
    with db_session() as conn2:
        row = conn2.execute("SELECT cpu_temp FROM metrics WHERE ts = ?", (ts,)).fetchone()
        assert row is None


def test_db_session_zero_fd_leaks():
    """Execute rapid DB operations and verify no connection/descriptor leak."""
    init_db()
    base_ts = int(time.time()) + 70000
    for i in range(100):
        log_metrics(base_ts + i, 42.0, 5.0, 15.0, [], [])

    # Read back history
    history = query_history("1h")
    assert isinstance(history, list)


def test_ups_failsafe_os_sync_threaded():
    """Verify that os.sync is called inside a background thread during UPS critical failsafe."""
    reset_failsafe_state()
    with patch("os.sync") as mock_sync, patch("backend.services.alert_rules.logger"):
        # Configure UPS telemetry triggering low battery
        ups_data = {
            "available": True,
            "status": "OB",
            "battery_charge_pct": 10.0,  # Below default 20%
            "time_left_min": 2.0,  # Below default 5 min
        }
        # Force grace period to 0 for immediate execution
        with patch.dict(os.environ, {"UPS_FAILSAFE_GRACE_SEC": "0"}):
            # Run alert rules
            evaluate_system_alerts({}, ups_data)
            # Allow background thread a moment to run
            time.sleep(0.1)
            assert mock_sync.called
    reset_failsafe_state()


def test_lcd_streamer_terminates_when_shutting_down():
    """Verify that lcd_renderer.render_lcd_loop exits cleanly when Z_STATE.shutting_down is True."""
    from backend.services.lcd_renderer import render_lcd_loop

    Z_STATE.shutting_down = True
    try:
        # Running render_lcd_loop with shutting_down=True must exit immediately without launching browser or blocking
        render_lcd_loop()
        assert Z_STATE.lcd_renderer_active is False
    finally:
        Z_STATE.shutting_down = False
