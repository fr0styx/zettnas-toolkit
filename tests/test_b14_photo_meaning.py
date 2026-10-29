"""B14: photo search by meaning without Immich (SigLIP 2 vectors from stored thumbnails)."""

import json
import struct
from unittest import mock

import pytest
from PIL import Image

from backend.services import photo_vectors as pv
from backend.services import rag_engine as re_mod
from backend.services.rag_engine import RagSearchEngine

# ranking and indexing, not permissions: a search without a principal sees every file
pytestmark = pytest.mark.usefixtures("search_as_system")

DIM = 4


def unit(*xs):
    n = sum(x * x for x in xs) ** 0.5
    return [x / n for x in xs]


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(re_mod, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = RagSearchEngine(db_path=str(tmp_path / "rag_index.db"))
    eng._ensure_schema()
    eng.update_config({"photo_vector_host": "http://clip:11436", "respect_standby": False})
    colours = {"IMG_0001.jpg": (250, 120, 40), "IMG_0002.jpg": (30, 60, 200), "IMG_0003.jpg": (40, 160, 60)}
    with mock.patch("backend.services.rag_standby.is_backing_disk_in_standby", return_value=False):
        for name, rgb in colours.items():
            p = tmp_path / name
            Image.new("RGB", (64, 48), rgb).save(p, "JPEG")
            st = p.stat()
            eng._index_single_file(str(p), p.name, ".jpg", st.st_size, st.st_mtime_ns, None, force_wake=True)
    yield eng
    eng.close()


def test_vectors_come_from_the_stored_thumbnails_in_batches(engine):
    sent = []

    def post(host, model, items):
        sent.append((host, model, len(items)))
        assert all(isinstance(it["image"], str) and it["image"] for it in items)
        return [unit(1, 0, 0, i) for i in range(len(items))]

    q = pv.PhotoVectorQueue(engine, idle=lambda: True, post=post)
    assert q.process_batch() == "done"
    assert sent == [("http://clip:11436", "siglip2", 3)]
    assert q.process_batch() == "empty"  # every photo has one now
    assert q.status()["done"] == 3


def test_nothing_happens_while_busy_or_without_a_server(engine):
    assert pv.PhotoVectorQueue(engine, idle=lambda: False, post=lambda *a: 1 / 0).process_batch() == "busy"
    engine.update_config({"photo_vector_host": ""})
    assert pv.PhotoVectorQueue(engine, idle=lambda: True, post=lambda *a: 1 / 0).process_batch() == "disabled"


def _store(engine, vecs):
    c = engine._get_conn()
    try:
        pv.ensure_schema(c)
        ids = [r[0] for r in c.execute("SELECT file_id FROM photo_assets ORDER BY file_name")]
        c.executemany(
            "INSERT OR REPLACE INTO photo_semantic VALUES (?, 'siglip2', ?)",
            [(i, pv.pack(v)) for i, v in zip(ids, vecs, strict=True)],
        )
        c.commit()
        return ids
    finally:
        c.close()


def test_a_search_finds_the_photo_that_shows_it(engine, monkeypatch):
    ids = _store(engine, [unit(1, 0, 0, 0), unit(0, 1, 0, 0), unit(0, 0, 1, 0)])
    monkeypatch.setattr(pv, "query_vector", lambda cfg, q: unit(0, 0.05, 1, 0) if q == "ein Wald" else None)
    res = engine.search("ein Wald", mode="photos", limit=5)
    hits = res.get("results") or res.get("photos") or []
    assert hits and hits[0]["file_id"] == ids[2] and hits[0]["meaning_match"]
    assert not engine.search("zzqx", mode="photos", limit=5).get("results")  # no vector, no words: nothing


def test_scores_are_relative_to_the_question_when_there_are_enough_photos():
    assert pv.scaled(0.20) == 1.0 and pv.scaled(0.05) == 0.0  # small libraries: absolute scale
    assert pv.scaled(0.10, mean=0.03, std=0.01) == 1.0  # 7 deviations above the rest
    assert pv.scaled(0.05, mean=0.03, std=0.01) == 0.0  # 2 deviations: not a match
    assert 0.0 < pv.scaled(0.07, mean=0.03, std=0.01) < 1.0


def test_the_server_answer_is_checked_and_ordered(monkeypatch):
    class Resp:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.data).encode()

    sent = []

    def urlopen(req, timeout=None):
        sent.append((req.full_url, req.get_header("Authorization")))
        n = len(json.loads(req.data)["input"])
        rows = [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]
        return Resp({"data": rows if n == 2 else rows[1:]})

    monkeypatch.setenv("PHOTO_VECTOR_TOKEN", "t0k")
    monkeypatch.setattr(pv.urllib.request, "urlopen", urlopen)
    assert pv.post_embeddings("http://clip:11436", "siglip2", ["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert sent[0] == ("http://clip:11436/v1/embeddings", "Bearer t0k")
    with pytest.raises(ValueError):  # three asked, two answered
        pv.post_embeddings("http://clip:11436", "siglip2", ["a", "b", "c"])
    pv._QUERY_CACHE.clear()
    assert pv.query_vector({"photo_vector_host": "http://clip:11436"}, "a") == [1.0, 0.0]
    assert pv.query_vector({}, "a") is None
    assert struct.unpack("<2f", pv.pack([1.0, 0.0])) == (1.0, 0.0)


def test_a_large_library_scores_each_photo_against_the_rest(monkeypatch):
    import sqlite3

    conn = sqlite3.connect(":memory:")
    pv.ensure_schema(conn)
    rows = [(i, "siglip2", pv.pack(unit(1, 0.02 * (i % 5), 0, 0))) for i in range(1, 41)]  # 40 alike
    rows.append((99, "siglip2", pv.pack(unit(0.3, 0, 1, 0))))  # one that shows it
    conn.executemany("INSERT INTO photo_semantic VALUES (?, ?, ?)", rows)
    monkeypatch.setattr(pv, "query_vector", lambda cfg, q: unit(0, 0, 1, 0))
    got = pv.matches(conn, {"photo_vector_host": "http://clip:11436"}, "something")
    assert list(got) == [99] and got[99] == 1.0
    monkeypatch.setattr(pv, "query_vector", lambda cfg, q: None)
    assert pv.matches(conn, {}, "something") == {}
    empty = sqlite3.connect(":memory:")
    monkeypatch.setattr(pv, "query_vector", lambda cfg, q: unit(0, 0, 1, 0))
    assert pv.matches(empty, {}, "something") == {}  # no table yet


def test_the_background_loop_keeps_going_after_errors(engine):
    states = []

    def boom(*a):
        raise OSError("server down")

    q = pv.PhotoVectorQueue(engine, idle=lambda: True, post=boom)

    def sleep(secs):
        states.append((q.last_state, secs))
        if len(states) >= 2:
            raise StopIteration

    with pytest.raises(StopIteration):
        q.run_forever(sleep=sleep)
    assert states[0] == ("error", 120) and "server down" in q.last_error


def test_the_queue_starts_with_the_engine_and_an_idle_check(engine, monkeypatch):
    monkeypatch.setattr(pv, "_QUEUE", None)
    with pytest.raises(RuntimeError):
        pv.get_queue()
    q = pv.get_queue(engine, lambda: True)
    assert pv.get_queue() is q
    monkeypatch.setattr(pv, "_QUEUE", None)


def test_startup_runs_the_queue_with_the_engine_and_the_idle_check(monkeypatch):
    from backend import main
    from backend.services import vision_queue

    got = {}

    class Q:
        def run_forever(self):
            got["ran"] = True

    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(pv, "get_queue", lambda engine, idle: got.update(idle=idle) or Q())
    main._photo_vector_daemon()
    assert got == {"idle": vision_queue.system_idle, "ran": True}
