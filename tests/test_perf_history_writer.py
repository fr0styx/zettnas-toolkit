"""History writes: one long-lived connection, SMART rows only when they add something (PERF-3)."""

import time

from backend import db


def _rows(dev):
    with db.db_session() as conn:
        return conn.execute(
            "SELECT ts, temp, reallocated_sectors FROM smart_history WHERE dev = ? ORDER BY ts", (dev,)
        ).fetchall()


def _log(ts, dev, temp=35.0, realloc=0):
    db.log_smart_metrics(ts, dev, temp, {"realloc": realloc})


def test_unchanged_samples_are_stored_every_ten_minutes():
    db.init_db()
    t0 = int(time.time()) - 3600
    for i in range(0, 40 * 15, 15):  # 10 minutes of 15-second NVMe samples
        _log(t0 + i, "hist_a")
    _log(t0 + 600, "hist_a")
    assert [r[0] for r in _rows("hist_a")] == [t0, t0 + 600]


def test_counter_and_temperature_changes_are_stored_at_once():
    db.init_db()
    t0 = int(time.time()) - 3600
    _log(t0, "hist_b")
    _log(t0 + 15, "hist_b", temp=36.0)  # small move: skipped
    _log(t0 + 30, "hist_b", temp=39.5)  # 4.5 °C: stored
    _log(t0 + 45, "hist_b", temp=39.5, realloc=2)  # counter change: stored
    assert [(r[0], r[1], r[2]) for r in _rows("hist_b")] == [(t0, 35.0, 0), (t0 + 30, 39.5, 0), (t0 + 45, 39.5, 2)]


def test_writes_reuse_one_connection():
    db.init_db()
    db.close_history_connection()
    t0 = int(time.time()) - 7200
    _log(t0, "hist_c")
    first = db._HISTORY["conn"]
    for i in range(1, 5):
        _log(t0 + i * 700, "hist_c")
        db.log_metrics(t0 + i, 40.0, 5.0, 30.0, [], [])
    assert db._HISTORY["conn"] is first and len(_rows("hist_c")) == 5


def test_old_rows_are_pruned_once_an_hour():
    db.init_db()
    now = int(time.time())
    old = now - 91 * 86400
    with db.db_session() as conn:
        conn.execute("INSERT INTO smart_history (ts, dev, temp) VALUES (?, ?, ?)", (old, "hist_d", 30.0))
    _log(now, "hist_d", temp=50.0)
    assert [r[0] for r in _rows("hist_d")] == [now]
