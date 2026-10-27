"""B12a (REL-18): every looping daemon beats; one that stops beating is "stalled" in health and
on the Overview; the backup watch runs in its own thread; backups cut off by a restart are
marked interrupted at start."""

import threading
import time

from backend.services import backup_watch, status_summary, supervisor


def _register(name, beat_every, last_beat, started_at=None, state="running"):
    with supervisor._lock:
        supervisor._daemons[name] = {
            "state": state,
            "restarts": 0,
            "last_error": "",
            "started_at": started_at or time.time() - 3600,
            "beat_every": beat_every,
            "last_beat": last_beat,
        }


def _forget(*names):
    with supervisor._lock:
        for n in names:
            supervisor._daemons.pop(n, None)


def test_a_daemon_that_stops_beating_is_stalled():
    now = time.time()
    _register("T-ok", 10, now - 5)
    _register("T-stuck", 10, now - 400)
    _register("T-quiet", None, None)  # no beat expected
    _register("T-crashed", 10, now - 400, state="crashed")
    try:
        st = supervisor.daemon_status(now)
        assert st["T-ok"]["state"] == "running" and st["T-stuck"]["state"] == "stalled"
        assert st["T-quiet"]["state"] == "running" and st["T-crashed"]["state"] == "crashed"
        assert "T-stuck" in supervisor.stalled() and "T-ok" not in supervisor.stalled()
    finally:
        _forget("T-ok", "T-stuck", "T-quiet", "T-crashed")


def test_stalled_needs_three_intervals_and_at_least_a_minute():
    assert supervisor.stalled_after(10) == 70 and supervisor.stalled_after(60) == 180


def test_beat_records_the_calling_daemon():
    _register("T-beat", 10, None)
    try:
        supervisor.beat("T-beat", now=123.0)
        assert supervisor._daemons["T-beat"]["last_beat"] == 123.0
        supervisor.beat("not-a-daemon")  # ignored
    finally:
        _forget("T-beat")


def test_a_supervised_daemon_beats_from_its_own_thread():
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            supervisor.beat()
            time.sleep(0.01)

    supervisor.supervise("T-thread", loop, beat_every=1)
    try:
        time.sleep(0.1)
        assert supervisor.daemon_status()["T-thread"]["last_beat"]
    finally:
        stop.set()
        time.sleep(0.05)
        _forget("T-thread")


def test_health_and_the_overview_name_a_stalled_service(client):
    _register("T-health", 10, time.time() - 400)
    try:
        body = client.get("/api/health").json()
        assert body["daemons"]["T-health"]["state"] == "stalled" and "T-health" in body["stalled"]
        items = status_summary.summary()["items"]
        assert any(i["kind"] == "service_stalled" and i["subject"] == "T-health" for i in items)
    finally:
        _forget("T-health")


def test_the_backup_watch_runs_on_its_own(monkeypatch):
    from backend.services import protection_jobs

    calls = []
    monkeypatch.setattr(backup_watch, "check_and_alert", lambda now: calls.append("backups"))
    monkeypatch.setattr(protection_jobs, "check_and_alert", lambda now: calls.append("protection"))
    stop = threading.Event()
    t = threading.Thread(target=protection_jobs.watch_daemon, args=(stop, 0.01))
    t.start()
    time.sleep(0.05)
    stop.set()
    t.join(1)
    assert calls[:2] == ["backups", "protection"] and not t.is_alive()


def test_one_failing_check_does_not_stop_the_watch(monkeypatch):
    from backend.services import protection_jobs

    calls = []
    monkeypatch.setattr(backup_watch, "check_and_alert", lambda now: 1 / 0)
    monkeypatch.setattr(protection_jobs, "check_and_alert", lambda now: calls.append(1))
    stop = threading.Event()
    t = threading.Thread(target=protection_jobs.watch_daemon, args=(stop, 0.01))
    t.start()
    time.sleep(0.05)
    stop.set()
    t.join(1)
    assert calls


def test_a_backup_cut_off_by_a_restart_is_marked_interrupted(monkeypatch, tmp_path):
    from backend.fsutil import atomic_write_json
    from backend.services import backup_engine

    monkeypatch.setattr(backup_engine, "BACKUP_JOBS_FILE", str(tmp_path / "jobs.json"))
    atomic_write_json(
        backup_engine.BACKUP_JOBS_FILE,
        [
            {"id": "a", "name": "Photos", "schedule": "daily", "last_status": "running"},
            {"id": "b", "name": "Docs", "schedule": "daily", "last_status": "success", "last_success_at": time.time()},
        ],
    )
    assert backup_engine.mark_interrupted_jobs() == ["a"]
    jobs = {j["id"]: j for j in backup_engine.get_backup_jobs()}
    assert jobs["a"]["last_status"] == "interrupted" and "restarted" in jobs["a"]["last_error"]
    assert jobs["b"]["last_status"] == "success"
    assert backup_engine.mark_interrupted_jobs() == []
    late = {b["id"]: b["why"] for b in backup_watch.overdue_backups()}
    assert late.get("a") == "its last run was interrupted"
