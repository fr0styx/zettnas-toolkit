"""A discovered Ollama address is looked up again later, so a runtime that moves is followed."""

from backend.services import rag_embeddings as rag


class _Ok:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_moved_runtime_is_found_again(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(rag, "_CACHED_OLLAMA_HOST", None)
    monkeypatch.setattr(rag, "_CACHED_OLLAMA_UNTIL", 0.0)
    where = {"host": "192.0.2.10"}
    monkeypatch.setattr("backend.services.ai_endpoints.candidate_hosts", lambda ip: ["zettnas-ollama", "192.0.2.10"])

    def fake_open(req, timeout=0):
        if where["host"] in req.full_url:
            return _Ok()
        raise OSError("refused")

    monkeypatch.setattr(rag.urllib.request, "urlopen", fake_open)
    clock = {"t": 1000.0}
    monkeypatch.setattr(rag.time, "time", lambda: clock["t"])
    assert rag._resolve_ollama_host() == "http://192.0.2.10:11434"
    where["host"] = "zettnas-ollama"  # moved onto the Docker network
    assert rag._resolve_ollama_host() == "http://192.0.2.10:11434"  # still cached
    clock["t"] += rag.OLLAMA_HOST_RECHECK_SECS + 1
    assert rag._resolve_ollama_host() == "http://zettnas-ollama:11434"
