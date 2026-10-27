"""The GPU order (PERF-1): chat, then search, then indexing, then photo reading."""

import threading
import time

from backend.services import gpu_queue as gq


def test_foreground_work_never_waits():
    with gq.use(gq.CHAT):
        assert gq.wait_turn(gq.QUERY) == 0.0
        assert gq.wait_turn(gq.CHAT) == 0.0
        assert gq.ahead_of(gq.QUERY) and gq.ahead_of(gq.INDEX) and gq.ahead_of(gq.VISION)
        assert not gq.ahead_of(gq.CHAT)
    assert not gq.ahead_of(gq.VISION)


def test_indexing_waits_for_a_chat_reply_to_finish():
    started = threading.Event()

    def chat():
        with gq.use(gq.CHAT):
            started.set()
            time.sleep(0.3)

    t = threading.Thread(target=chat)
    t.start()
    started.wait(2)
    waited = gq.wait_turn(gq.INDEX, max_wait=5)
    t.join()
    assert 0.15 < waited < 2.0
    assert gq.snapshot()["running"] == {"chat": 0, "query": 0, "index": 0, "vision": 0}


def test_indexing_is_slowed_but_never_stopped():
    with gq.use(gq.QUERY):
        t0 = time.monotonic()
        gq.wait_turn(gq.INDEX, max_wait=0.2)
        assert time.monotonic() - t0 < 1.0


def test_photo_reading_waits_for_indexing_but_indexing_not_for_it():
    with gq.use(gq.INDEX):
        assert gq.ahead_of(gq.VISION)
    with gq.use(gq.VISION):
        assert gq.wait_turn(gq.INDEX, max_wait=1) < 0.05


def test_the_decorator_marks_the_whole_call():
    seen = []

    @gq.holds(gq.CHAT)
    def reply():
        seen.append(gq.snapshot()["running"]["chat"])
        return "hi"

    assert reply() == "hi" and seen == [1]
    assert gq.snapshot()["running"]["chat"] == 0


def test_search_questions_and_file_batches_mark_their_turn(monkeypatch):
    from backend.services import rag_embeddings as emb

    seen = {}

    def one(**k):
        seen["query"] = gq.snapshot()["running"]["query"]
        return b"", [0.1, 0.2]

    monkeypatch.setattr(emb, "compute_neural_embedding_via_ollama", one)
    emb._QUERY_VEC_CACHE.clear()
    emb.compute_multimodal_query_embedding("where is the boiler manual", model="embeddinggemma")
    assert seen["query"] == 1

    def batch(host, model, texts):
        seen["index"] = gq.snapshot()["running"]["index"]
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(emb, "_embed_one_batch", batch)
    monkeypatch.setitem(emb._EMBED_BREAKER, "until", 0)
    assert len(emb.compute_neural_embeddings_batch(["a", "b"], "embeddinggemma")) == 2
    assert seen["index"] == 1


def test_photo_reading_waits_while_anything_else_runs(monkeypatch):
    from backend.services import chat_llm_runtime, vision_queue

    monkeypatch.setattr(chat_llm_runtime, "chat_recently_active", lambda now=None: False)
    monkeypatch.setattr(vision_queue.os, "getloadavg", lambda: (0.0, 0.0, 0.0))
    monkeypatch.setattr("backend.hardware.cpu.read_cpu_temp", lambda: 40.0)
    assert vision_queue.system_idle()
    with gq.use(gq.INDEX):
        assert not vision_queue.system_idle()


def test_a_chat_reply_holds_the_gpu():
    from backend.services import chat_llm_runtime

    assert hasattr(chat_llm_runtime._try_local_llm_completion, "__wrapped__")
