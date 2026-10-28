"""B15 small idle fixes: the backup scheduler waits once a minute and stops at once (PERF-21); the
JSON cache remembers a missing file (PERF-22); thumbnails touched at most daily and 304 when the
browser has them (PERF-26); event writes debounced and unchanged conditions not repeated for an
hour (PERF-27); a cached database check in /api/health and a lighter Docker health check
(PERF-30); the PIL LCD skips unchanged samples and waits on its wake event while blanked (PERF-16)."""

import json
import os
import threading
import time
import types

import pytest

from backend import fsutil, state
from backend.services import backup_engine


def test_the_scheduler_waits_a_minute_and_stops_at_once(monkeypatch, tmp_path):
    jobs = tmp_path / "jobs.json"
    jobs.write_text("[]")
    monkeypatch.setattr(backup_engine, "BACKUP_JOBS_FILE", str(jobs))
    reads = []
    real = fsutil.read_json

    def counting(path, default=None):
        reads.append(path)
        return real(path, default)

    monkeypatch.setattr(fsutil, "read_json", counting)
    monkeypatch.setattr(backup_engine, "SCHEDULER_TICK_SECS", 30.0)
    backup_engine._SCHEDULER_WAKE.clear()
    t = threading.Thread(target=backup_engine.backup_scheduler_daemon, daemon=True)
    t.start()
    time.sleep(0.3)
    started = time.monotonic()
    backup_engine.stop_backup_scheduler()
    t.join(timeout=5)
    assert not t.is_alive() and time.monotonic() - started < 2  # no 60 one-second sleeps to sit out
    assert len(reads) <= 1


def test_a_missing_settings_file_is_remembered(monkeypatch, tmp_path):
    path = str(tmp_path / "optional.json")
    stats = []
    real_stat = os.stat
    monkeypatch.setattr(fsutil.os, "stat", lambda p, *a, **k: stats.append(p) or real_stat(p, *a, **k))
    fsutil._JSON_CACHE.pop(path, None)
    assert fsutil.read_json_cached(path, {"d": 1}, max_age=60) == {"d": 1}
    assert fsutil.read_json_cached(path, {"d": 2}, max_age=60) == {"d": 2}  # each caller's default
    assert stats.count(path) == 1  # remembered: not stat'ed again within max_age
    fsutil.atomic_write_json(path, {"now": "here"})
    assert fsutil.read_json_cached(path, {}, max_age=60) == {"now": "here"}  # a write refreshes it


def test_a_thumbnail_hit_touches_the_file_at_most_daily(monkeypatch, tmp_path):
    from backend.services import thumbs

    src = tmp_path / "photo.jpg"
    src.write_bytes(b"x")
    hit = tmp_path / "hit.webp"
    hit.write_bytes(b"webp")
    monkeypatch.setattr(thumbs, "_paths", lambda key: (str(hit), str(tmp_path / "fail")))
    real_utime = os.utime
    touched = []
    monkeypatch.setattr(thumbs.os, "utime", lambda p, *a: touched.append(p))
    assert thumbs.get(str(src)) == b"webp"
    assert touched == []  # just written: no touch
    old = time.time() - 2 * 86400
    real_utime(hit, (old, old))
    thumbs.get(str(src))
    assert touched == [str(hit)]


def test_a_thumbnail_the_browser_has_is_a_304(client, auth_headers, monkeypatch):
    from PIL import Image

    pool = os.environ["POOL_PATH"]
    path = os.path.join(pool, "perf26.jpg")
    Image.new("RGB", (40, 30), (10, 200, 30)).save(path)
    try:
        r = client.get("/api/fs/preview/image", params={"path": path, "thumb": 1}, headers=auth_headers)
        assert r.status_code == 200 and r.headers.get("etag")
        from backend.services import thumbs

        monkeypatch.setattr(thumbs, "get", lambda *a: pytest.fail("read the thumbnail for a 304"))
        r2 = client.get(
            "/api/fs/preview/image",
            params={"path": path, "thumb": 1},
            headers={**auth_headers, "If-None-Match": r.headers["etag"]},
        )
        assert r2.status_code == 304 and not r2.content
    finally:
        os.remove(path)


def test_events_are_written_in_batches_and_unchanged_ones_not_repeated(monkeypatch, tmp_path):
    events_file = tmp_path / "events.json"
    monkeypatch.setattr(state, "EVENTS_FILE", str(events_file))
    monkeypatch.setattr(state, "EVENT_FLUSH_SECS", 0.3)
    writes = []
    real = state.atomic_write_json
    monkeypatch.setattr(state, "atomic_write_json", lambda p, d: writes.append(len(d)) or real(p, d))
    monkeypatch.setattr(state, "_event_dedup_cache", {})
    monkeypatch.setattr(state, "_event_last_message", {})
    clock = {"t": 1_000_000}
    monkeypatch.setattr(state.time, "time", lambda: clock["t"])
    with state.Z_STATE.lock:
        state.Z_STATE.event_log.clear()
    for i in range(5):
        state.add_event("warning", f"Disk {i} hot", "52 C")
    assert writes == []  # not yet: one write for the batch
    time.sleep(0.6)
    assert writes == [5] and len(json.loads(events_file.read_text())) == 5
    clock["t"] += 120
    state.add_event("warning", "Disk 0 hot", "52 C")  # unchanged: not again within the hour
    state.add_event("warning", "Disk 1 hot", "57 C")  # changed: logged after a minute, as before
    with state.Z_STATE.lock:
        titles = [e["title"] + " " + e["message"] for e in state.Z_STATE.event_log]
    assert titles.count("Disk 0 hot 52 C") == 1 and "Disk 1 hot 57 C" in titles
    clock["t"] += 3600
    state.add_event("warning", "Disk 0 hot", "52 C")
    with state.Z_STATE.lock:
        assert [e["title"] for e in state.Z_STATE.event_log].count("Disk 0 hot") == 2
    state.flush_events()
    time.sleep(0.5)


def test_health_opens_the_database_at_most_every_five_minutes(monkeypatch):
    from backend.api import system

    opened = []

    class Session:
        def __enter__(self):
            opened.append(1)
            return types.SimpleNamespace(execute=lambda *a: types.SimpleNamespace(fetchone=lambda: (1,)))

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("backend.users_db.users_db_session", lambda _p: Session())
    monkeypatch.setattr(system, "_DB_CHECK", {"state": "", "at": 0.0})
    for _ in range(3):
        assert system._health_checks()["database"] == "ok"
    assert len(opened) == 1
    monkeypatch.setattr(system, "_DB_CHECK", {"state": "failed", "at": time.time()})
    system._health_checks()
    assert len(opened) == 2  # a failure is looked at again on the next probe


def test_the_docker_health_check_is_light():
    with open("Dockerfile", encoding="utf-8") as f:
        src = f.read()
    hc = src.split("HEALTHCHECK", 1)[1].split("\n\n", 1)[0]
    assert "--interval=60s" in hc and "python3 -S -I" in hc


def test_the_pil_lcd_skips_unchanged_samples_and_sleeps_while_blanked(monkeypatch):
    from backend.services import lcd_pil

    renders, waits = [], []

    class Wake:
        def __init__(self):
            self.n = 0
            self.st = None

        def wait(self, t):
            waits.append(t)
            self.n += 1
            if self.n >= 4:
                self.st.shutting_down = True
            return False

        def clear(self):
            pass

    st = types.SimpleNamespace(
        lcd_wake=Wake(), ui_wake=None, shutting_down=False, lock=threading.Lock(),
        cached_stats={"cpu": 10}, current_lcd_page=0,
    )  # fmt: skip
    st.lcd_wake.st = st
    monkeypatch.setattr(lcd_pil, "render_frame", lambda stats, page: renders.append(1) or object())
    monkeypatch.setattr(lcd_pil, "to_framebuffer", lambda img: types.SimpleNamespace(tobytes=lambda: b"same"))
    fb = types.SimpleNamespace(write_image=lambda f: None)
    monkeypatch.setattr(lcd_pil, "seconds_to_next_minute", lambda: 40.0)
    lcd_pil.run_loop(fb, 30.0, lambda fb, b: False, st)
    assert len(renders) == 1  # the same sample on the same page in the same minute: one render
    st2 = types.SimpleNamespace(**{**st.__dict__, "shutting_down": False, "lcd_wake": Wake()})
    st2.lcd_wake.st = st2
    waits.clear()
    lcd_pil.run_loop(fb, 30.0, lambda fb, b: True, st2)
    assert waits and all(w >= 30.0 for w in waits)  # blanked: no 1 s polling
