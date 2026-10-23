"""AI-15: document embeddings are batched, and a file never mixes neural and lexical vectors."""

import io
import json
import struct

import pytest

from backend.services import rag_engine


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _reset():
    rag_engine._EMBED_BREAKER["until"] = 0.0
    rag_engine._EMBED_MODEL_SEEN.clear()
    yield
    rag_engine._EMBED_BREAKER["until"] = 0.0
    rag_engine._EMBED_MODEL_SEEN.clear()


def test_batches_and_normalizes(monkeypatch):
    calls = []

    def fake(req, timeout=None):
        body = json.loads(req.data)
        calls.append(len(body["input"]))
        return _Resp(json.dumps({"embeddings": [[3.0, 4.0]] * len(body["input"])}).encode())

    monkeypatch.setattr(rag_engine.urllib.request, "urlopen", fake)
    out = rag_engine.compute_neural_embeddings_batch(["t"] * 70, "nomic-embed-text", host="http://x:11434")
    assert calls == [32, 32, 6] and len(out) == 70
    assert struct.unpack("<2f", out[0]) == pytest.approx((0.6, 0.8))


def test_one_failed_batch_means_no_neural_vectors_and_breaker(monkeypatch):
    calls = []

    def fake(req, timeout=None):
        calls.append(1)
        if len(calls) > 1:
            raise OSError("down")
        body = json.loads(req.data)
        return _Resp(json.dumps({"embeddings": [[1.0]] * len(body["input"])}).encode())

    monkeypatch.setattr(rag_engine.urllib.request, "urlopen", fake)
    assert rag_engine.compute_neural_embeddings_batch(["t"] * 40, "nomic-embed-text", host="http://x:11434") is None
    n = len(calls)
    assert rag_engine.compute_neural_embeddings_batch(["t"], "nomic-embed-text", host="http://x:11434") is None
    assert len(calls) == n  # skipped while the breaker is open


def test_unknown_model_name_never_falls_back_to_another_model(monkeypatch):
    """Only the model and its :latest tag: EmbeddingGemma 1 must not stand in for 2."""
    import urllib.error

    tried = []

    def fake(req, timeout=None):
        body = json.loads(req.data)
        tried.append(body["model"])
        if body["model"] != "embeddinggemma-2-ov:latest":
            raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)
        return _Resp(json.dumps({"embeddings": [[1.0, 0.0]]}).encode())

    monkeypatch.setattr(rag_engine.urllib.request, "urlopen", fake)
    monkeypatch.setitem(rag_engine._EMBED_BREAKER, "until", 0.0)
    assert rag_engine.compute_neural_embeddings_batch(["t"], "embeddinggemma-2-ov", host="http://x:11434")
    assert tried == ["embeddinggemma-2-ov", "embeddinggemma-2-ov:latest"]
    tried.clear()
    monkeypatch.setitem(rag_engine._EMBED_BREAKER, "until", 0.0)
    assert rag_engine.compute_neural_embeddings_batch(["t"], "google/embeddinggemma-2", host="http://x:11434") is None
    assert tried == ["google/embeddinggemma-2", "google/embeddinggemma-2:latest"]
