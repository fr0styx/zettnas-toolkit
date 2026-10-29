"""B14 AI-40: embeddings from an OpenAI-style server (OVMS /v3/embeddings), not only Ollama."""

import io
import json
import math

import pytest

from backend.services import rag_embeddings as emb


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def server(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data)
        seen.append((req.full_url, body))
        n = len(body["input"])
        # answered out of order on purpose: the client sorts by index
        data = [{"index": i, "embedding": [3.0, 4.0 + i]} for i in reversed(range(n))]
        return Resp(json.dumps({"data": data}).encode())

    monkeypatch.setattr(emb.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(emb, "_EMBED_BREAKER", {"until": 0.0})
    return seen


@pytest.mark.parametrize(
    ("host", "openai"),
    [("http://ovms:8000/v3", True), ("http://lm:1234/v1/", True), ("http://ollama:11434", False), (None, False)],
)
def test_which_servers_speak_openai(host, openai):
    assert emb.is_openai_host(host) is openai


def test_a_batch_goes_to_v3_embeddings_in_order(server):
    blobs = emb.compute_neural_embeddings_batch(["a", "b"], model="zettnas-embed", host="http://ovms:8000/v3")
    assert server[0] == ("http://ovms:8000/v3/embeddings", {"model": "zettnas-embed", "input": ["a", "b"]})
    vecs = [emb.unpack_embedding(b) for b in blobs]
    assert vecs[0] == pytest.approx([0.6, 0.8])
    assert vecs[1] == pytest.approx([3 / math.sqrt(34), 5 / math.sqrt(34)])


def test_one_text_goes_there_too(server):
    blob, vec = emb.compute_neural_embedding_via_ollama("hello", model="zettnas-embed", host="http://ovms:8000/v3")
    assert server[0][0] == "http://ovms:8000/v3/embeddings"
    assert vec == pytest.approx([0.6, 0.8]) and emb.unpack_embedding(blob) == pytest.approx([0.6, 0.8])


def test_a_failing_server_gives_none(monkeypatch):
    def down(req, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(emb.urllib.request, "urlopen", down)
    monkeypatch.setattr(emb, "_EMBED_BREAKER", {"until": 0.0})
    assert emb.compute_neural_embedding_via_ollama("hello", model="m", host="http://ovms:8000/v3") is None
