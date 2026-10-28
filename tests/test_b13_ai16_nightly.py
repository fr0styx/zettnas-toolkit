"""B13 (AI-16): the first token's time is measured and gated; the nightly runs the shipped chat
model and the documents set."""

import json
import time

import yaml

from backend.services import chat_llm_runtime as rt
from tests.rag_eval.compare import drops
from tests.rag_eval.run_eval import first_token_summary
from tests.rag_eval.summary import render


def test_a_streamed_reply_times_its_first_token(monkeypatch):
    lines = [
        json.dumps({"message": {"content": ""}}).encode(),
        json.dumps({"message": {"content": "Hello"}}).encode(),
        json.dumps({"message": {"content": " there"}, "done": True, "eval_count": 2}).encode(),
    ]
    state = {"t_sent": time.monotonic() - 0.25}
    data = rt._read_llm_stream(iter(lines), "ollama", state)
    assert data["message"]["content"] == "Hello there"
    assert 240 <= state["first_token_ms"] < 5000
    rt._note_first_token(state, data, streaming=True)
    assert rt._FIRST_TOKEN_MS.get() == round(state["first_token_ms"], 1)


def test_a_whole_ollama_reply_says_its_prompt_time_and_others_say_nothing():
    rt._note_first_token({}, {"load_duration": 500_000_000, "prompt_eval_duration": 1_250_000_000}, streaming=False)
    assert rt._FIRST_TOKEN_MS.get() == 1750.0
    rt._note_first_token({}, {"choices": [{"message": {"content": "hi"}}]}, streaming=False)
    assert rt._FIRST_TOKEN_MS.get() is None  # an OpenAI-compatible whole reply can't tell


def test_the_telemetry_carries_the_first_token():
    rt._FIRST_TOKEN_MS.set(812.3)
    tel = rt.build_llm_execution_telemetry(active_model="qwen3:4b", runtime_name="Ollama", answer_text="hi")
    assert tel["first_token_ms"] == 812.3
    assert rt.build_llm_execution_telemetry(active_model="qwen3:4b", runtime_name=None)["first_token_ms"] is None


def test_first_token_summary():
    assert first_token_summary([]) == {"measured": 0}
    s = first_token_summary([1000, 2000, None, 3000, 4000] + [5000] * 15)
    assert s["measured"] == 19 and s["missing"] == 1 and s["p50_ms"] == 5000 and s["p95_ms"] == 5000
    assert first_token_summary([100.0, 200.0])["p50_ms"] == 100.0


def _answers(model="qwen3:4b", p95=4000.0, accuracy=0.8):
    return {
        "overall": {"recall@1": 0.9},
        "answers": {"model": model, "accuracy": accuracy, "first_token": {"p95_ms": p95}},
    }


def test_a_slower_first_token_fails_the_compare():
    assert drops(_answers(p95=5900), _answers(p95=4000), 0.02) == []
    assert any("first-token" in d for d in drops(_answers(p95=6100), _answers(p95=4000), 0.02))
    assert any("budget" in d for d in drops(_answers(p95=130000), {}, 0.02, first_token_p95_ms=120000))
    assert drops(_answers(p95=110000), {}, 0.02, first_token_p95_ms=120000) == []


def test_answers_of_another_model_are_not_compared():
    base = _answers(model="qwen3:1.7b", accuracy=0.95, p95=100)
    assert drops(_answers(model="qwen3:4b", accuracy=0.5, p95=9000), base, 0.02) == []
    assert drops(_answers(model="qwen3:1.7b", accuracy=0.5), base, 0.02)  # same model: compared


def test_the_nightly_runs_the_shipped_model_and_the_documents_set():
    with open(".github/workflows/ai-eval-nightly.yml", encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    jobs = wf["jobs"]
    assert set(jobs) == {"retrieval", "documents", "answers"}
    steps = {name: " ".join(str(s.get("run", "")) for s in job["steps"]) for name, job in jobs.items()}
    assert "--answers qwen3:4b" in steps["answers"] and "--first-token-p95-ms" in steps["answers"]
    assert "qwen3:1.7b" not in json.dumps(wf)
    assert "--set documents" in steps["documents"] and "baseline_nightly_documents.json" in steps["documents"]
    assert "--set all --distractors 2000" in steps["retrieval"]
    for job in jobs.values():
        image = job["services"]["ollama"]["image"]
        assert "@sha256:" in image  # pinned
    with open("tests/rag_eval/baseline_nightly_documents.json", encoding="utf-8") as f:
        floor = json.load(f)
    assert floor["set"] == "documents" and "latency" not in floor and floor["note"].startswith("floor")


def test_the_vector_bench_keeps_its_big_files_off_docker():
    with open(".github/workflows/hardware.yml", encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    run = " ".join(str(s.get("run", "")) for s in wf["jobs"]["vector-bench"]["steps"])
    assert "--tmp /results/" in run


def test_the_summary(tmp_path):
    p = tmp_path / "eval-answers.json"
    p.write_text(json.dumps({
        "model": "embeddinggemma", "set": "base",
        "overall": {"recall@1": 0.9, "recall@5": 0.95, "mrr@10": 0.92},
        "by_language": {"de": {"recall@1": 0.9, "recall@5": 0.9, "mrr@10": 0.9}},
        "answers": {"model": "qwen3:4b", "accuracy": 0.8, "source_hit": 0.9, "by_language": {"de": 0.8},
                    "first_token": {"p50_ms": 900.0, "p95_ms": 2100.0}},
    }))  # fmt: skip
    out = render(str(p))
    assert "| overall | 0.9 | 0.95 | 0.92 |" in out and "p95 2100.0 ms" in out
    assert render(str(tmp_path / "missing.json")) == ""
