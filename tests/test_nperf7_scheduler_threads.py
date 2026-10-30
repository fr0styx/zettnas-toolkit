"""NPERF-7: network-bound scheduler jobs run on their own, one at a time each, and a hung one
is named in the log."""

import threading
import time

from backend.services import scheduler


def test_a_job_runs_once_at_a_time(monkeypatch):
    monkeypatch.setattr(scheduler, "_RUNNING", {})
    gate, ran = threading.Event(), []

    def slow(x):
        ran.append(x)
        gate.wait(5)

    assert scheduler.on_its_own("slow", slow, 1) is True
    assert scheduler.on_its_own("slow", slow, 2) is False  # still going: not started twice
    assert scheduler.on_its_own("other", lambda: ran.append("o")) is True
    gate.set()
    for _ in range(100):
        if "slow" not in scheduler._RUNNING:
            break
        time.sleep(0.02)
    assert scheduler.on_its_own("slow", lambda x: ran.append(x), 3) is True
    time.sleep(0.1)
    assert sorted(map(str, ran)) == ["1", "3", "o"]


def test_a_hung_job_is_named_once(monkeypatch, caplog):
    monkeypatch.setattr(scheduler, "_RUNNING", {"Frigate": time.time() - scheduler.JOB_DEADLINE_S - 60})
    monkeypatch.setattr(scheduler, "_LATE", set())
    assert scheduler.on_its_own("Frigate", lambda: None) is False
    assert scheduler.on_its_own("Frigate", lambda: None) is False
    assert caplog.text.count("Frigate has been running for") == 1


def test_an_error_in_a_job_frees_it(monkeypatch):
    monkeypatch.setattr(scheduler, "_RUNNING", {})

    def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(threading, "excepthook", lambda args: None)
    scheduler.on_its_own("boom", boom)
    for _ in range(100):
        if "boom" not in scheduler._RUNNING:
            break
        time.sleep(0.02)
    assert "boom" not in scheduler._RUNNING


def test_the_wrapped_jobs_log_their_errors(monkeypatch, caplog):
    def broken(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr("backend.services.frigate_events.tick", broken)
    monkeypatch.setattr("backend.services.two_way_sync.run_due", broken)
    monkeypatch.setattr("backend.services.notifications.send_digest_if_due", broken)
    scheduler._run_frigate()
    scheduler._run_two_way_sync()
    scheduler._run_digest(1.0)
    assert "Frigate events failed" in caplog.text and "Two-way sync failed" in caplog.text
    assert "digest failed" in caplog.text
