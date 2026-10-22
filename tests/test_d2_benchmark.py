"""D2: model benchmarks measure speed and placement and recommend fast and balanced tiers."""

from backend.services import model_benchmark as mb


def _fake_ollama(speeds):
    def http(url, body=None, timeout=30):
        if url.endswith("/api/tags"):
            return {
                "models": [
                    {"name": "qwen2.5:3b", "size": 2_000_000_000, "digest": "a"},
                    {"name": "gemma3:12b", "size": 8_000_000_000, "digest": "b"},
                    {"name": "big:70b", "size": 40_000_000_000, "digest": "c"},
                    {
                        "name": "hf.co/x/qwen2.5-3b:latest",
                        "size": 2_000_000_000,
                        "digest": "a",
                    },  # same model, other name
                    {"name": "embeddinggemma:latest", "size": 600_000_000, "digest": "e"},
                ]
            }
        if url.endswith("/api/show"):
            return {"capabilities": ["embedding"] if "embedding" in body["model"] else ["completion"]}
        if url.endswith("/api/generate"):
            tps = speeds[body["model"]]
            return {
                "eval_count": 96,
                "eval_duration": int(96 / tps * 1e9),
                "prompt_eval_duration": 200_000_000,
                "load_duration": 1_000_000_000,
            }
        if url.endswith("/api/ps"):
            return {
                "models": [
                    {"name": "gemma3:12b", "size": 8, "size_vram": 8},
                    {"name": "big:70b", "size": 10, "size_vram": 4},
                    {"name": "qwen2.5:3b", "size": 2, "size_vram": 0},
                ]
            }
        raise AssertionError(url)

    return http


def test_benchmark_and_tiers(tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "RESULTS_FILE", str(tmp_path / "bench.json"))
    out = mb.run("http://ollama", _fake_ollama({"qwen2.5:3b": 45.0, "gemma3:12b": 18.0, "big:70b": 4.0}))
    names = [r["name"] for r in out["results"]]
    assert names == ["qwen2.5:3b", "gemma3:12b", "big:70b"]  # no embedding model, no duplicate name
    by = {r["name"]: r for r in out["results"]}
    assert by["qwen2.5:3b"]["tokens_per_s"] == 45.0 and by["qwen2.5:3b"]["placement"] == "CPU"
    assert by["gemma3:12b"]["placement"] == "GPU" and by["big:70b"]["placement"] == "split"
    assert by["gemma3:12b"]["first_token_s"] == 1.2
    assert out["recommended"] == {"fast": "qwen2.5:3b", "balanced": "gemma3:12b"}  # 70b is below reading speed
    assert mb.load_results()["recommended"]["balanced"] == "gemma3:12b"


def test_api_applies_the_balanced_tier(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "RESULTS_FILE", str(tmp_path / "bench.json"))
    mb.run("http://ollama", _fake_ollama({"qwen2.5:3b": 45.0, "gemma3:12b": 18.0, "big:70b": 4.0}))
    applied = {}
    from backend.services import rag_engine

    monkeypatch.setattr(rag_engine.get_rag_engine(), "update_config", lambda u: applied.update(u) or u)
    r = client.post("/api/ai/models/benchmark/apply", json={"tier": "balanced"}, headers=auth_headers)
    assert r.status_code == 200 and applied["active_model"] == "gemma3:12b"
    assert client.get("/api/ai/models/benchmark", headers=auth_headers).json()["recommended"]["fast"] == "qwen2.5:3b"
