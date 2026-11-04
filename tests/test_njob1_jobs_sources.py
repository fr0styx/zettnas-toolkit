"""NJOB-1: the Jobs centre shows the background work people ask about: the AI index learning files,
the thumbnail pass and a folder's thumbnails being made."""

import sqlite3

import pytest

from backend.services import jobs, rag_engine, thumb_prefetch
from backend.services.jobs import job_manager


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "HISTORY_FILE", str(tmp_path / "jobs_history.json"))
    monkeypatch.setattr(job_manager, "_history", [])
    monkeypatch.setattr(job_manager, "_history_loaded", True)
    monkeypatch.setattr(job_manager, "_jobs", {})
    # only the sources this file is about (other tests leave finished transfers behind)
    monkeypatch.setattr(jobs, "SOURCES", {k: v for k, v in jobs.SOURCES.items() if k in ("aiindex", "thumbs")})
    thumb_prefetch._queue.clear()
    thumb_prefetch._queued.clear()
    yield
    thumb_prefetch._queue.clear()
    thumb_prefetch._queued.clear()


class _Engine:
    def __init__(self, state="running"):
        self._sync_state = state
        self._sync_progress = {"indexed_files": 12, "skipped_unchanged": 300, "deferred_standby": 4, "started_at": 1.0}
        self.stopped = False

    def stop_sync(self):
        self.stopped = True


def test_the_ai_index_shows_while_it_learns_files(monkeypatch):
    monkeypatch.setattr(rag_engine, "_RAG_ENGINE", None)
    assert jobs._ai_index() == []  # the engine is never started just to look
    eng = _Engine()
    monkeypatch.setattr(rag_engine, "_RAG_ENGINE", eng)
    (job,) = jobs._ai_index()
    assert job.kind == "ai_index" and job.status == "running" and job.can_cancel
    assert job.detail == "12 indexed, 300 unchanged, 4 waiting for sleeping disks"
    eng._sync_state = "paused"
    assert jobs._ai_index()[0].status == "paused"
    eng._sync_state = "idle"
    assert jobs._ai_index() == []


def test_stopping_the_ai_index_from_the_jobs_centre(monkeypatch):
    monkeypatch.setattr(rag_engine, "_RAG_ENGINE", None)
    assert jobs._cancel_ai_index("sync") is False
    eng = _Engine()
    monkeypatch.setattr(rag_engine, "_RAG_ENGINE", eng)
    assert job_manager.cancel("aiindex:sync", everyone=True) and eng.stopped


def test_a_folders_waiting_thumbnails_show(monkeypatch):
    assert thumb_prefetch.folder_jobs() == []
    thumb_prefetch._queue.extend(["/a.jpg", "/b.mov"])
    (job,) = thumb_prefetch.folder_jobs()
    assert jobs.SOURCES["thumbs"][0] is thumb_prefetch.folder_jobs
    assert job.kind == "thumbnails" and job.detail == "2 waiting" and not job.can_cancel


class _Index:
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


def test_a_thumbnail_pass_that_makes_some_is_a_job_with_a_history(tmp_path, monkeypatch):
    rows = [(i, f"/mnt/user/p/{i}.jpg", "image", "ok", "sdb") for i in range(1, 5)]
    monkeypatch.setattr(thumb_prefetch, "make", lambda p: not p.endswith("2.jpg"))
    bf = thumb_prefetch.Backfill(_Index(str(tmp_path / "i.db"), rows), lambda: True, asleep=lambda d: False)
    assert bf.step() == "more"
    active = job_manager.list(everyone=True)["active"]
    (job,) = [j for j in active if j["kind"] == "thumbnails"]
    assert job["detail"] == "3 made, 0 waiting for sleeping disks" and job["percent"] == 99.0
    assert bf.step() == "done"
    done = job_manager.list(everyone=True)
    assert not [j for j in done["active"] if j["kind"] == "thumbnails"]
    assert done["history"][0]["status"] == "done" and done["history"][0]["detail"].startswith("3 made")


def test_a_pass_with_nothing_to_make_stays_out_of_the_jobs_centre(tmp_path, monkeypatch):
    rows = [(1, "/mnt/user/p/1.jpg", "image", "ok", "sdb")]
    monkeypatch.setattr(thumb_prefetch, "make", lambda p: False)
    bf = thumb_prefetch.Backfill(_Index(str(tmp_path / "i.db"), rows), lambda: True, asleep=lambda d: False)
    assert bf.step() == "more" and bf.step() == "done"
    assert job_manager.list(everyone=True) == {"active": [], "history": []}
