"""SET-13: the history chart's data. A sleeping drive has no value (it was stored with the last
temperature it had), and the 7 and 30 day views average drives and fans (they took one arbitrary
sample per period)."""

import json
import sqlite3
import time

import pytest

from backend import db


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "history.db"))
    db.close_history_connection()
    db._METRICS_COLS.clear()
    db.init_db()
    yield db
    db.close_history_connection()
    db._METRICS_COLS.clear()


def _drive(name, temp, standby=False):
    return {"name": name, "dev": name, "temp": temp, "standby": standby, "health": "ok", "role": "data"}


def test_a_sleeping_drive_has_no_value(history):
    now = int(time.time())
    db.log_metrics(now - 600, 40, 5, 30, [_drive("sda", 34), _drive("sdb", 36, standby=True)], [900, 1100])
    db.log_metrics(now - 300, 41, 6, 31, [_drive("sda", 35), _drive("sdb", 33)], [950, None])
    first, second = db.query_history("24h")
    assert first["disks"] == [
        {"name": "sda", "temp": 34, "standby": False},
        {"name": "sdb", "temp": None, "standby": True},  # 36 was what it had when it fell asleep
    ]
    assert second["disks"][1] == {"name": "sdb", "temp": 33, "standby": False}
    assert first["fans"] == [900, 1100] and second["fans"] == [950, None]
    assert first["cpu_temp"] == 40 and first["net_rx"] == 0
    assert db.query_history("1h") == db.query_history("6h") == db.query_history("no such range")


def test_seven_days_average_each_drive_and_fan_over_the_period(history):
    # the start of a two-hour period: its two half hours are one point on the 30-day view, whatever the clock
    period = int(time.time()) // 7200 * 7200 - 7200
    db.log_metrics(
        period + 10, 40, 10, 30, [_drive("sda", 30), _drive("sdb", 50, standby=True)], [1000, 2000], 100.0, 200.0
    )
    db.log_metrics(
        period + 310, 50, 20, 40, [_drive("sda", 40), _drive("sdb", 50, standby=True)], [2000, None], 300.0, 400.0
    )
    db.log_metrics(
        period + 610,
        60,
        30,
        50,
        [_drive("sda", 50, standby=True), _drive("sdb", 50, standby=True)],
        [3000],
        500.0,
        600.0,
    )
    db.log_metrics(period + 1810, 70, 40, 60, [_drive("sdc", 44)], [], 0.0, 0.0)  # the next half hour
    first, second = db.query_history("7d")
    assert first["ts"] == period and first["samples"] == 3
    assert (first["cpu_temp"], first["cpu_util"], first["mem_pct"]) == (50.0, 20.0, 40.0)
    assert (first["net_rx"], first["net_tx"]) == (300.0, 400.0)
    assert first["disks"] == [
        {"name": "sda", "temp": 35.0, "standby": False},  # over the two samples in which it was awake
        {"name": "sdb", "temp": None, "standby": True},  # asleep the whole period
    ]
    assert first["fans"] == [2000, 2000]  # each fan over the samples that have a reading
    assert second["disks"] == [{"name": "sdc", "temp": 44.0, "standby": False}] and second["fans"] == []
    assert len(db.query_history("30d")) == 1  # both half hours fall in one two-hour period


def test_damaged_rows_and_an_old_database_do_not_break_the_chart(history, tmp_path, monkeypatch):
    now = int(time.time())
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO metrics (ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json) VALUES (?, ?, ?, ?, ?, ?)",
            (now - 60, None, None, None, "{ not json", json.dumps({"not": "a list"})),
        )
        conn.execute(
            "INSERT INTO metrics (ts, cpu_temp, cpu_util, mem_pct, disks_json, fans_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                now - 30,
                40,
                5,
                30,
                json.dumps(["text", {"temp": 3}, {"name": "sda", "temp": "hot"}, {"name": "sdb", "temp": True}]),
                json.dumps([True, "x", 800]),
            ),
        )
    damaged, odd = db.query_history("1h")
    assert damaged["disks"] == [] and damaged["fans"] == [] and damaged["cpu_temp"] == 0
    assert odd["disks"] == [
        {"name": "sda", "temp": None, "standby": False},
        {"name": "sdb", "temp": None, "standby": False},
    ]
    assert odd["fans"] == [None, None, 800]

    # a database from before the network and drive rates were stored
    old = str(tmp_path / "old.db")
    conn = sqlite3.connect(old)
    conn.execute(
        "CREATE TABLE metrics (ts INTEGER, cpu_temp REAL, cpu_util REAL, mem_pct REAL, disks_json TEXT, fans_json TEXT)"
    )
    conn.execute("INSERT INTO metrics VALUES (?, 40, 5, 30, '[]', '[]')", (now - 30,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", old)
    db.close_history_connection()
    assert db.query_history("24h")[0]["net_rx"] == 0 and db.query_history("7d")[0]["samples"] == 1
