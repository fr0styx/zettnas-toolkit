"""scripts/llm_bench.py: time to the first token of a long document question, per runtime."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("llm_bench", ROOT / "scripts" / "llm_bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def test_ollama_run_from_the_stream(monkeypatch):
    sent = []

    def stream(url, body, timeout=900.0):
        sent.append(body)
        if body["prompt"] == "Hi":
            return iter([{"response": "Hello", "done": True}])
        return iter(
            [
                {"thinking": "Let me", "response": ""},  # a thinking model streams its thinking first
                {"response": "The"},
                {
                    "done": True,
                    "prompt_eval_count": 6000,
                    "prompt_eval_duration": 20_000_000_000,
                    "eval_count": 100,
                    "eval_duration": 10_000_000_000,
                },
            ]
        )

    monkeypatch.setattr(bench, "_post_stream", stream)
    r = bench.run_ollama("http://h", "qwen3:4b", "long prompt", cpu=True, num_predict=128, num_ctx=8192)
    assert r["runtime"] == "ollama-cpu" and r["prompt_tokens"] == 6000
    assert r["prompt_tokens_per_s"] == 300.0 and r["tokens_per_s"] == 10.0 and r["first_token_s"] >= 0
    assert sent[0]["options"]["num_gpu"] == 0 and sent[1]["options"]["num_ctx"] == 8192


def test_main_prints_one_line_per_run_and_a_median(monkeypatch, capsys):
    monkeypatch.setattr(
        bench, "run_ollama", lambda *a: {"runtime": "ollama", "first_token_s": 2.0, "tokens_per_s": 9.0}
    )
    assert bench.main(["ollama", "--model", "m", "--runs", "3", "--tokens", "500"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 4 and "median_first_token_s" in lines[-1]
