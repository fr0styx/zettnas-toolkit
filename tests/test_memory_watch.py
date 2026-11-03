"""The backend's memory over time (hardware budget follow-up): samples, growth per run, breakdown."""

import pytest

from backend import db
from backend.services import memory_watch


@pytest.fixture
def fresh(monkeypatch):
    db.init_db()
    with db.history_session() as conn:
        conn.execute("DELETE FROM memory_samples")
    monkeypatch.setitem(memory_watch._STATE, "at", 0.0)
    monkeypatch.setitem(memory_watch._STATE, "pruned", 0.0)
    yield


def fake(pid, rss):
    return lambda now: {
        "ts": int(now),
        "pid": pid,
        "uptime_s": 60,
        "rss_kb": rss,
        "anon_kb": rss // 2,
        "file_kb": rss // 2,
        "threads": 20,
    }


def test_reads_this_process_and_a_status_file(tmp_path):
    own = memory_watch.current()
    assert own["pid"] > 0 and own["rss_kb"] > 0 and own["threads"] >= 1
    f = tmp_path / "status"
    f.write_text("Name:\tpython\nVmRSS:\t  2048 kB\nRssAnon:\t 1500 kB\nRssFile:\t 548 kB\nThreads:\t29\n")
    assert memory_watch.read_status(str(f)) == {"rss_kb": 2048, "anon_kb": 1500, "file_kb": 548, "threads": 29}
    assert memory_watch.read_status(str(tmp_path / "missing")) == {
        "rss_kb": 0,
        "anon_kb": 0,
        "file_kb": 0,
        "threads": 0,
    }


def test_samples_every_ten_minutes_and_measures_growth_per_run(fresh):
    t0 = 1_800_000_000
    assert memory_watch.sample(t0, read=fake(11, 200_000))["rss_kb"] == 200_000
    assert memory_watch.sample(t0 + 60, read=fake(11, 999_999)) is None  # too soon
    memory_watch.sample(t0 + 3600, read=fake(11, 210_000))
    memory_watch.sample(t0 + 7200, read=fake(11, 220_000))
    memory_watch.sample(t0 + 9000, read=fake(12, 190_000))  # restarted
    rows = memory_watch.history(24, now=t0 + 9000)
    assert [r["rss_kb"] for r in rows] == [200_000, 210_000, 220_000, 190_000]
    runs = memory_watch.growth(rows)
    assert [(r["pid"], r["kb_per_hour"]) for r in runs] == [(11, 10_000), (12, None)]


def test_old_samples_are_pruned(fresh):
    t0 = 1_800_000_000
    memory_watch.sample(t0, read=fake(1, 100))
    memory_watch.sample(t0 + memory_watch.KEEP_SECS + 3600, read=fake(1, 200))
    rows = memory_watch.history(24 * 30, now=t0 + memory_watch.KEEP_SECS + 3600)
    assert [r["rss_kb"] for r in rows] == [200]


def test_a_failed_save_is_not_an_error(fresh, monkeypatch):
    class Broken:
        def __enter__(self):
            raise memory_watch.sqlite3.OperationalError("database is locked")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(db, "history_session", lambda: Broken())
    assert memory_watch.sample(1_800_000_000, read=fake(1, 100)) is None


def test_breakdown_counts_objects_and_traces_only_when_asked():
    counts = memory_watch.object_counts(3, objects=[1, 2, "a", 3.0, 4])
    assert counts[0] == {"type": "int", "count": 3}
    assert memory_watch.top_allocations() == [] or memory_watch.tracing()
    try:
        assert memory_watch.set_tracing(True) is True
        assert memory_watch.set_tracing(True) is True
        junk = [bytearray(1024) for _ in range(200)]
        top = memory_watch.top_allocations(5)
        assert top and top[0]["kb"] > 0 and ":" in top[0]["where"]
        b = memory_watch.breakdown(5)
        assert b["tracing"] is True and b["objects"] and b["now"]["rss_kb"] > 0
        del junk
    finally:
        assert memory_watch.set_tracing(False) is False
    assert memory_watch.set_tracing(False) is False


def test_the_endpoints(fresh, monkeypatch):
    from backend.api import metrics

    memory_watch.sample(1_800_000_000, read=fake(5, 300_000))
    monkeypatch.setattr(memory_watch, "history", lambda hours: [fake(5, 300_000)(1_800_000_000)])
    out = metrics.memory_history(48)
    assert out["samples"][0]["rss_kb"] == 300_000 and out["runs"][0]["pid"] == 5
    assert metrics.memory_breakdown(500)["objects"]
    assert metrics.memory_tracing(metrics.TracingIn(on=False)) == {"tracing": False}


def test_a_restart_in_the_same_container_starts_a_new_run():
    rows = [
        {"ts": 0, "pid": 1, "uptime_s": 10, "rss_kb": 100},
        {"ts": 3600, "pid": 1, "uptime_s": 3610, "rss_kb": 160},
        {"ts": 4000, "pid": 1, "uptime_s": 5, "rss_kb": 90},
        {"ts": 7600, "pid": 1, "uptime_s": 3605, "rss_kb": 95},
    ]
    runs = memory_watch.growth(rows)
    assert [(r["rss_kb_first"], r["kb_per_hour"]) for r in runs] == [(100, 60), (90, 5)]
