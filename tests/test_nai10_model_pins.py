"""NAI-10: the nightly eval's models are pinned by digest, so an upstream rebuild fails loudly."""

import json
import os

from tests.rag_eval import pull_models as pm

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64


def test_pins_file_names_every_model_the_nightly_pulls():
    with open(pm.PINS, encoding="utf-8") as f:
        pins = json.load(f)
    wf = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "ai-eval-nightly.yml")
    with open(wf, encoding="utf-8") as f:
        text = f.read()
    assert "api/pull" not in text and "tests.rag_eval.pull_models" in text
    for m in ("embeddinggemma", "qwen3:4b"):
        assert pm.full_name(m) in pins and pins[pm.full_name(m)].startswith("sha256:")


def test_check_says_what_differs():
    pins = {"embeddinggemma:latest": A, "qwen3:4b": A}
    assert pm.check(["embeddinggemma", "qwen3:4b"], {"embeddinggemma:latest": A, "qwen3:4b": A}, pins) == []
    out = pm.check(["qwen3:4b", "embeddinggemma", "other"], {"qwen3:4b": B}, pins)
    assert "upstream build changed" in out[0] and "not installed" in out[1] and "not pinned" in out[2]


def test_installed_digests_reads_ollama_tags(monkeypatch):
    tags = {"models": [{"name": "embeddinggemma:latest", "digest": "a" * 64}, {"model": "qwen3:4b", "digest": B}]}
    monkeypatch.setattr(pm, "_get", lambda host, path: tags)
    assert pm.installed_digests("http://x") == {"embeddinggemma:latest": A, "qwen3:4b": B}


def test_main_pulls_prints_and_fails_on_a_new_build(monkeypatch, tmp_path, capsys):
    pulled = []
    monkeypatch.setattr(pm, "_post", lambda host, path, body, timeout=3600: pulled.append(body["model"]) or {})
    monkeypatch.setattr(pm, "installed_digests", lambda host: {"embeddinggemma:latest": B})
    pins = tmp_path / "models.json"
    pins.write_text(json.dumps({"_note": "x", "embeddinggemma:latest": A}))
    monkeypatch.setattr(pm, "PINS", str(pins))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert pm.main(["embeddinggemma"]) == 1
    assert pulled == ["embeddinggemma"]
    assert "embeddinggemma:latest" in summary.read_text()
    assert "upstream build changed" in capsys.readouterr().err
    pins.write_text(json.dumps({"embeddinggemma:latest": B}))
    assert pm.main(["embeddinggemma"]) == 0
