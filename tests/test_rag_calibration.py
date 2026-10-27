"""Each embedding model gets its own similarity cut-off, measured on the install (AI-17)."""

import json

import pytest

from backend.services import rag_calibration as cal
from backend.services import rag_embeddings as emb
from backend.services.rag_engine import SIMILARITY_PROFILES, similarity_profile


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(cal, "STORE", str(tmp_path / "ai" / "vec_thresholds.json"))
    cal.reset()
    yield tmp_path / "ai" / "vec_thresholds.json"
    cal.reset()


def fake_model(monkeypatch, right=0.8, wrong=0.3, fail=False):
    """Vectors whose cosine is `right` between a question and its passage, `wrong` otherwise."""
    import math

    n = len(cal.PAIRS)

    def vec(i, query):
        # unit vectors: a shared axis carries the similarity, a private axis the rest
        v = [0.0] * (2 * n + 1)
        if query:
            v[i] = 1.0
            return v
        v[i] = right
        v[n + i] = math.sqrt(max(0.0, 1 - right**2 - wrong**2))
        v[2 * n] = wrong
        return v

    def batch(texts, model, target_dim=None, host=None, **k):
        if fail:
            return None
        return [emb._pack_embedding(vec(i, False), None) for i in range(len(texts))]

    def one(text, model="", host=None, timeout=0, target_dim=None, is_query=False, **k):
        i = next(j for j, (q, _) in enumerate(cal.PAIRS) if q == text)
        return b"", vec(i, True)

    monkeypatch.setattr(emb, "compute_neural_embeddings_batch", batch)
    monkeypatch.setattr(emb, "compute_neural_embedding_via_ollama", one)


def test_the_default_is_the_neural_profiles():
    assert SIMILARITY_PROFILES["neural"]["vec_min"] == cal.DEFAULT_VEC_MIN


def test_the_cut_off_only_ever_lowers_the_default():
    # a model whose unrelated passages score 0.6 keeps the tested default
    assert cal.threshold([0.75, 0.8, 0.85], [0.55, 0.6, 0.65], 0.5) == (0.5, 0.65)
    # one with a lower scale gets a lower cut-off: its noise level (90th percentile)
    assert cal.threshold([0.5, 0.55, 0.6], [0.2, 0.25, 0.3], 0.5) == (0.3, 0.3)
    # never above its weakest right matches, never below the floor
    assert cal.threshold([0.3, 0.4], [0.35, 0.36, 0.37], 0.5)[0] == 0.25
    assert cal.threshold([0.12], [0.01, 0.02], 0.5)[0] == cal.MIN_VEC_MIN


def test_a_model_is_measured_once_and_search_uses_its_cut_off(monkeypatch, store):
    fake_model(monkeypatch)
    assert similarity_profile("nomic-embed-text:latest", 768) is SIMILARITY_PROFILES["neural"]
    cal.ensure_measured("nomic-embed-text:latest", 768, None, background=False)
    data = json.loads(store.read_text())
    got = data["models"]["nomic-embed-text@768"]
    assert data["version"] == cal.VERSION and got["pairs"] == len(cal.PAIRS)
    # the right passage scores 0.8 and every other one 0: noise 0, so the floor
    assert got["noise"] == 0.0 and got["vec_min"] == cal.MIN_VEC_MIN
    prof = similarity_profile("nomic-embed-text", 768)
    assert prof["vec_min"] == got["vec_min"] and prof["vec_min_measured"]
    assert prof["ranker"] == SIMILARITY_PROFILES["neural"]["ranker"]
    # another size of the same model is another model; the lexical vectors keep their profile
    assert similarity_profile("nomic-embed-text", 256) is SIMILARITY_PROFILES["neural"]
    assert similarity_profile("zett_lexical_384d") is SIMILARITY_PROFILES["lexical"]
    # measured once: a second call does nothing
    monkeypatch.setattr(cal, "measure", lambda *a: pytest.fail("measured twice"))
    cal.ensure_measured("nomic-embed-text", 768, None, background=False)


def test_a_failing_embedder_keeps_the_default_and_is_retried_later(monkeypatch, store):
    fake_model(monkeypatch, fail=True)
    cal.ensure_measured("bge-m3", None, None, background=False)
    assert not store.exists() and cal.measured("bge-m3", None) is None
    calls = []
    monkeypatch.setattr(cal, "measure", lambda *a: calls.append(a))
    cal.ensure_measured("bge-m3", None, None, background=False)
    assert calls == []  # not again within the hour
    cal._FAILED["bge-m3@native"] -= cal.RETRY_AFTER_SECS + 1
    cal.ensure_measured("bge-m3", None, None, background=False)
    assert len(calls) == 1


def test_searches_in_tests_never_measure_as_a_side_effect(monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setattr(cal, "measure", lambda *a: pytest.fail("measured during a test search"))
    cal.ensure_measured("embeddinggemma", 768, None)  # background, as search calls it
    cal.ensure_measured("zett_lexical_384d", None, None, background=False)


def test_an_old_or_broken_store_is_ignored(store):
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({"version": 0, "models": {"x@native": {"vec_min": 0.9}}}))
    assert cal.measured("x", None) is None
    cal.reset()
    store.write_text("{not json")
    assert cal.measured("x", None) is None
