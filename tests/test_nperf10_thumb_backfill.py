"""NPERF-10: the background thumbnail pass makes the most of a disk's awake time with a few
workers, and the folder queue survives a restart without waking a disk."""

import sqlite3
import threading
import time

import pytest

from backend.services import thumb_prefetch


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(thumb_prefetch, "QUEUE_FILE", str(tmp_path / "thumb_queue.json"))
    monkeypatch.setattr(thumb_prefetch, "_ensure_worker", lambda: None)
    for q in (thumb_prefetch._queue, thumb_prefetch._queued, thumb_prefetch._restored):
        q.clear()
    yield
    for q in (thumb_prefetch._queue, thumb_prefetch._queued, thumb_prefetch._restored):
        q.clear()


class _Engine:
    def __init__(self, path, rows):
        self.path = path
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE indexed_files (file_id INTEGER PRIMARY KEY, canonical_path TEXT, modality TEXT,"
            " parse_status TEXT, backing_dev TEXT)"
        )
        conn.executemany("INSERT INTO indexed_files VALUES (?, ?, ?, ?, ?)", rows)
        conn.commit()
        conn.close()

    def _get_conn(self):
        return sqlite3.connect(self.path)


def test_a_batch_is_shared_by_a_few_workers(tmp_path, monkeypatch):
    rows = [(i, f"/mnt/user/p/{i}.jpg", "image", "ok", "sdb") for i in range(1, 13)]
    names, made, lock = set(), [], threading.Lock()

    def make(path):
        with lock:
            names.add(threading.current_thread().name)
        time.sleep(0.02)
        with lock:
            made.append(path)
        return True

    monkeypatch.setattr(thumb_prefetch, "make", make)
    bf = thumb_prefetch.Backfill(_Engine(str(tmp_path / "i.db"), rows), lambda: True, asleep=lambda d: False)
    assert bf.workers == thumb_prefetch.BACKFILL_WORKERS == 3
    assert bf.step() == "more"
    assert sorted(made) == sorted(r[1] for r in rows) and bf.made == 12 and bf.cursor == 12
    assert len(names) > 1 and all(n.startswith("thumb-backfill") for n in names)


def test_the_folder_queue_is_kept_and_comes_back_after_a_restart(tmp_path, monkeypatch):
    folder = tmp_path / "photos"
    folder.mkdir()
    for n in ("a.jpg", "b.mov", "notes.txt"):
        (folder / n).write_bytes(b"x")
    assert thumb_prefetch.queue_folder(str(folder)) == 2
    saved = thumb_prefetch.read_json(thumb_prefetch.QUEUE_FILE, None)
    assert saved == [str(folder / "a.jpg"), str(folder / "b.mov")]
    thumb_prefetch._queue.clear()  # a restart
    thumb_prefetch._queued.clear()
    assert thumb_prefetch.restore_queue() == 2
    assert thumb_prefetch.restore_queue() == 2  # nothing twice
    assert thumb_prefetch.waiting() == 0  # not the opened-folder queue: the background pass takes them


def test_restored_files_wait_for_their_disk(tmp_path, monkeypatch):
    asleep = {"/mnt/user/p/b.jpg"}
    made = []
    monkeypatch.setattr(thumb_prefetch, "make", lambda p: made.append(p) or True)
    thumb_prefetch._restored.extend(["/mnt/user/p/a.jpg", "/mnt/user/p/b.jpg"])
    bf = thumb_prefetch.Backfill(
        _Engine(str(tmp_path / "i.db"), []), lambda: True, asleep=lambda p: p in asleep, workers=1
    )
    assert bf.step() == "done"  # the index had nothing; the restored file on an awake disk was made
    assert made == ["/mnt/user/p/a.jpg"] and list(thumb_prefetch._restored) == ["/mnt/user/p/b.jpg"]
    assert thumb_prefetch.read_json(thumb_prefetch.QUEUE_FILE, None) == ["/mnt/user/p/b.jpg"]
    asleep.clear()  # the disk woke up
    bf.step()
    assert made == ["/mnt/user/p/a.jpg", "/mnt/user/p/b.jpg"] and not thumb_prefetch._restored
    assert thumb_prefetch.read_json(thumb_prefetch.QUEUE_FILE, None) == []


def test_draining_saves_what_is_left(monkeypatch):
    monkeypatch.setattr(thumb_prefetch, "make", lambda p: True)
    thumb_prefetch._queue.extend(["/x/1.jpg", "/x/2.jpg"])
    thumb_prefetch.drain()
    assert thumb_prefetch.read_json(thumb_prefetch.QUEUE_FILE, None) == []


def test_startup_restores_the_queue(monkeypatch):
    from backend import main

    calls = []
    monkeypatch.setattr(thumb_prefetch, "restore_queue", lambda: calls.append("restore") or 0)

    class _Bf:
        def __init__(self, *a, **k):
            pass

        def run_forever(self):
            calls.append("run")

    monkeypatch.setattr(thumb_prefetch, "Backfill", _Bf)
    monkeypatch.setattr("time.sleep", lambda s: calls.append("sleep"))
    monkeypatch.setattr("backend.services.rag_engine.get_rag_engine", lambda: None)
    main._thumb_backfill_daemon()
    assert calls == ["restore", "sleep", "run"]
