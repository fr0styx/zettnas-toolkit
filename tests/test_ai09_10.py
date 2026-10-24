"""AI-09 / AI-10: Ollama gets a context window that fits, and token numbers are the runtime's."""

import io
import json

import pytest

from backend.services import ai_chat_agent


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _setup(monkeypatch, handler):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ZETTNAS_TEST_MODE", "0")
    monkeypatch.setattr(ai_chat_agent, "_get_docker_host_ips", lambda: ["10.9.9.9"])
    ai_chat_agent._ACTIVE_ENDPOINT_CACHE.clear()
    sent = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "10.9.9.9" not in url:
            raise OSError("unreachable")
        body = json.loads(req.data) if getattr(req, "data", None) else None
        sent.append((url, body))
        out = handler(url, body)
        if out is None:
            raise OSError("unreachable")
        return _Resp(json.dumps(out).encode())

    monkeypatch.setattr(ai_chat_agent.urllib.request, "urlopen", fake_urlopen)
    return sent


def test_context_window_is_fixed_and_prompts_fit_it(monkeypatch):
    """AI-7: one num_ctx (no model reloads, no oversized KV cache); the prompt is fitted to it."""
    monkeypatch.delenv("ZETTNAS_AI_NUM_CTX", raising=False)
    assert ai_chat_agent._context_window_for([{"content": "hi"}]) == 8192
    assert ai_chat_agent._context_window_for([{"content": "x" * 30000}]) == 8192
    monkeypatch.setenv("ZETTNAS_AI_NUM_CTX", "16384")
    assert ai_chat_agent._context_window_for() == 16384

    msgs = [{"role": "system", "content": "rules"}]
    msgs += [{"role": "user", "content": "old " * 2000}, {"role": "assistant", "content": "older " * 2000}]
    msgs += [{"role": "user", "content": "question\n" + "context " * 20000}]
    fitted = ai_chat_agent._fit_to_window(msgs, None, 8192)
    total = sum(ai_chat_agent.estimate_tokens(m["content"]) + 4 for m in fitted)
    assert total <= 8192 - ai_chat_agent.REPLY_TOKENS + 50
    assert fitted[0]["content"] == "rules" and fitted[-1]["content"].startswith("question")
    assert len(fitted) == 2  # history went first


def test_token_estimate_counts_cjk_characters():
    assert ai_chat_agent.estimate_tokens("abcd" * 10) == 10
    assert ai_chat_agent.estimate_tokens("红烧肉要炖多久") == 7


def test_routing_uses_whole_words():
    """AI-7: "temperature" in a recipe question is not a hardware question; "ram" is not in
    "program", "lan" is not in "plan"."""
    assert not ai_chat_agent._mentions("which program copies photos", ("ram",))
    assert not ai_chat_agent._mentions("the q3 plan", ("lan",))
    assert ai_chat_agent._mentions("how much ram is free", ("ram",))
    assert not ai_chat_agent._HARDWARE_TEMP_RE.search("at what temperature do i bake the banana bread")
    assert ai_chat_agent._HARDWARE_TEMP_RE.search("what is the cpu temperature")


def test_ollama_request_sets_num_ctx_and_reports_real_tokens(monkeypatch):
    def handler(url, body):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen2.5:7b"}]}
        if url.endswith("/api/chat"):
            return {"message": {"content": "Hello"}, "eval_count": 0}
        return None

    sent = _setup(monkeypatch, handler)
    reply = ai_chat_agent._try_local_llm_completion("qwen2.5:7b", "", [{"role": "user", "content": "x" * 20000}])
    chat = [b for u, b in sent if u.endswith("/api/chat")][0]
    assert chat["options"]["num_ctx"] == 8192
    assert reply[0] == "Hello" and reply[1] == "Ollama (qwen2.5:7b)"
    assert reply[2] == 0 and reply[3] is None  # nothing reported, nothing invented


def test_model_server_never_swaps_models(monkeypatch):
    def handler(url, body):
        if url.endswith("/v1/models"):
            return {"data": [{"id": "OpenVINO/qwen2.5-1.5b-int4", "owned_by": "OVMS"}]}
        if url.endswith("/chat/completions"):
            return {"choices": [{"message": {"content": "wrong model"}}]}
        return None

    sent = _setup(monkeypatch, handler)
    reply = ai_chat_agent._try_local_llm_completion("llama3.1:8b", "", [{"role": "user", "content": "hi"}])
    assert reply[0] is None
    assert not any(u.endswith("/chat/completions") for u, _ in sent)
    assert "not served" in ai_chat_agent._LAST_MODEL_PROBLEM["text"]
    ai_chat_agent._LAST_MODEL_PROBLEM["text"] = ""


@pytest.mark.parametrize("vram,device", [(5_000_000_000, "GPU"), (0, "CPU")])
def test_reported_model_and_device_match_the_runtime(monkeypatch, vram, device):
    """Batch 3 exit check: the label shows the model Ollama ran and the device /api/ps reports."""

    def handler(url, body):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "llama3.2:3b"}]}
        if url.endswith("/api/chat"):
            return {"message": {"content": "Hi"}, "eval_count": 3, "eval_duration": 1_500_000_000}
        if url.endswith("/api/ps"):
            return {"models": [{"name": "llama3.2:3b", "size_vram": vram}]}
        return None

    _setup(monkeypatch, handler)
    reply, label, toks, tok_sec, accel, _ = ai_chat_agent._try_local_llm_completion(
        "llama3.2:3b", "", [{"role": "user", "content": "hi"}]
    )
    assert label == "Ollama (llama3.2:3b)"
    assert accel["name"] == device and toks == 3 and tok_sec == 2.0
