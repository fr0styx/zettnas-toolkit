"""SMART velocity is reused until a disk's counters change (PERF-1, PERF-4)."""

import time

from backend import db


def _log(ts, dev, pending=0, realloc=0, temp=35.0):
    db.log_smart_metrics(ts, dev, temp=temp, metrics={"realloc": realloc, "pending": pending}, power_on_hours=0)


def _statements(dev):
    seen = []
    with db.db_session() as conn:
        conn.set_trace_callback(seen.append)
        res = db.query_smart_velocity(dev, conn=conn)
    return res, [s for s in seen if s.lstrip().upper().startswith("SELECT")]


def test_repeat_calls_skip_the_full_evaluation():
    db.init_db()
    now = int(time.time())
    for i in range(30):
        _log(now - (30 - i) * 600, "perf_a")
    first, q1 = _statements("perf_a")
    again, q2 = _statements("perf_a")
    assert again == first
    assert len(q2) <= 3 < len(q1)  # head row, self-test time, database name


def test_a_counter_change_is_seen_at_once():
    db.init_db()
    now = int(time.time())
    for i in range(10):
        _log(now - (10 - i) * 600, "perf_b")
    assert db.query_smart_velocity("perf_b")["realloc_current"] == 0
    _log(now, "perf_b", realloc=4)
    assert db.query_smart_velocity("perf_b")["realloc_current"] == 4


def test_temperature_only_samples_are_throttled(monkeypatch):
    db.init_db()
    now = int(time.time())
    _log(now - 1200, "perf_c")
    _log(now - 600, "perf_c")
    db.query_smart_velocity("perf_c")
    _log(now, "perf_c", temp=41.0)
    _, q = _statements("perf_c")
    assert len(q) <= 3
    monkeypatch.setattr(db, "VELOCITY_RECHECK_SECS", 0)
    _, q = _statements("perf_c")
    assert len(q) > 3


def test_stuck_pending_uses_one_aggregate():
    db.init_db()
    now = int(time.time())
    for h in range(0, 47, 3):
        _log(now - (46 - h) * 3600, "perf_d", pending=2)
    res, q = _statements("perf_d")
    assert res["stuck_pending"] is True
    assert not any("pending_sectors FROM smart_history" in s and "ORDER BY ts ASC" in s for s in q)
    _log(now + 1, "perf_d", pending=0)
    assert db.query_smart_velocity("perf_d")["stuck_pending"] is False


def test_sparkline_is_bucketed_and_cache_hits_are_cheap(monkeypatch):
    import copy

    db.init_db()
    now = int(time.time())
    with db.db_session() as conn:
        conn.executemany(
            "INSERT INTO smart_history (ts, dev, temp, reallocated_sectors, pending_sectors) VALUES (?, ?, ?, 0, 0)",
            [(now - 29 * 86400 + i * 15, "perf_e", 35.0) for i in range(20000)],
        )
    first = db.query_smart_velocity("perf_e")
    assert 0 < len(first["sparkline_points"]) <= 30 * 86400 // db.SPARKLINE_BUCKET_SECS + 1
    monkeypatch.setattr(copy, "deepcopy", lambda *a, **k: (_ for _ in ()).throw(AssertionError("deep copy")))
    again = db.query_smart_velocity("perf_e")
    assert again == first and again is not first
