"""B14 AI-39: ZettNAS sends EMBEDDING_TOKEN to the embedding server, and only when it is set."""

import json
from unittest.mock import patch

from backend.services import rag_embeddings


def test_no_token_no_header(monkeypatch):
    monkeypatch.delenv("EMBEDDING_TOKEN", raising=False)
    assert "Authorization" not in rag_embeddings.embed_headers()


def test_the_token_goes_with_every_embedding_request(monkeypatch):
    monkeypatch.setenv("EMBEDDING_TOKEN", " s3cret ")
    seen = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"embeddings": [[0.6, 0.8]]}).encode()

    def fake_urlopen(req, timeout=None):
        seen.append(req.get_header("Authorization"))
        return Resp()

    with patch.object(rag_embeddings.urllib.request, "urlopen", fake_urlopen):
        rag_embeddings.compute_neural_embedding_via_ollama("hello", model="m", host="http://emb:11434", timeout=2)
    assert seen and all(h == "Bearer s3cret" for h in seen)
