"""AI-09 / AI-10: Ollama gets a context window that fits, and token numbers are the runtime's."""

import io
import json

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


def test_context_window_grows_with_prompt(monkeypatch):
    monkeypatch.delenv("ZETTNAS_AI_NUM_CTX", raising=False)
    assert ai_chat_agent._context_window_for([{"content": "hi"}]) == 4096
    assert ai_chat_agent._context_window_for([{"content": "x" * 30000}]) == 16384
    monkeypatch.setenv("ZETTNAS_AI_NUM_CTX", "32768")
    assert ai_chat_agent._context_window_for([{"content": "hi"}]) == 32768


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
