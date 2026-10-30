"""B14 COMP-07: AI for apps, one OpenAI-compatible endpoint with a key per app."""

import io
import json
import urllib.error

import pytest

from backend.services import ai_access, ai_apps

CFG = {
    "active_model": "Qwen3-4B",
    "llm_endpoint": "http://ovms:8000/v1",
    "llm_fallback_model": "qwen3:4b",
    "ollama_host": "http://ollama:11434",
    "embedding_model": "embeddinggemma-2-ov",
    "embedding_host": "http://eg2:11434",
}


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def cfg(monkeypatch):
    c = dict(CFG)
    monkeypatch.setattr(ai_apps, "_config", lambda: c)
    monkeypatch.setattr(ai_access, "log_request", lambda *a, **k: None)
    return c


@pytest.fixture
def key(client, auth_headers):
    r = client.post("/api/v1/ai/apps/keys", json={"app": "paperless"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    yield data
    client.delete(f"/api/v1/ai/apps/keys/{data['id']}", headers=auth_headers)


def bearer(key):
    return {"Authorization": f"Bearer {key['key']}"}


def test_a_key_comes_with_the_apps_settings_filled_in(key):
    s = key["settings"]
    assert s["PAPERLESS_AI_LLM_BACKEND"] == "openai-like"
    assert s["PAPERLESS_AI_LLM_API_KEY"] == key["key"]
    assert s["PAPERLESS_AI_LLM_ENDPOINT"].endswith("/api/v1/ai/openai")
    assert s["PAPERLESS_AI_LLM_MODEL"] == ai_apps.CHAT_MODEL


def test_the_key_lists_its_models_and_can_do_nothing_else(client, key, auth_headers):
    r = client.get("/api/v1/ai/openai/models", headers=bearer(key))
    assert r.status_code == 200
    assert [m["id"] for m in r.json()["data"]] == [ai_apps.CHAT_MODEL, ai_apps.EMBED_MODEL]
    assert client.get("/api/v1/ai/apps", headers=bearer(key)).status_code == 403  # not an admin's key
    assert client.get("/api/v1/users", headers=bearer(key)).status_code in (401, 403)
    listed = client.get("/api/v1/ai/apps", headers=auth_headers).json()
    assert key["id"] in [k["id"] for k in listed["keys"]]
    assert "key" not in json.dumps(listed["keys"][0]).lower().replace("masked_key", "")


def test_a_session_without_the_scope_is_refused(client, monkeypatch, cfg):
    r = client.post("/api/v1/ai/openai/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code in (401, 403)


def test_chat_goes_to_the_chat_server_with_its_model_and_only_known_fields(client, key, cfg, monkeypatch):
    sent = []

    def fake_open(url, payload, timeout):
        sent.append((url, payload))
        return FakeResp(json.dumps({"choices": [{"message": {"content": "hello"}}], "model": "Qwen3-4B"}).encode())

    monkeypatch.setattr(ai_apps, "_open", fake_open)
    body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "user": "x"}
    r = client.post("/api/v1/ai/openai/chat/completions", json=body, headers=bearer(key))
    assert r.status_code == 200, r.text
    assert r.json()["model"] == ai_apps.CHAT_MODEL
    url, payload = sent[0]
    assert url == "http://ovms:8000/v1/chat/completions"
    assert payload == {
        "messages": body["messages"],
        "temperature": 0.2,
        "stream": False,
        "model": "Qwen3-4B",
        "n": 1,  # NAI-13: one answer, a bounded length
        "max_tokens": ai_apps.APP_MAX_TOKENS,
    }


def test_the_fallback_model_answers_when_the_chat_server_is_down(client, key, cfg, monkeypatch):
    urls = []

    def fake_open(url, payload, timeout):
        urls.append((url, payload["model"]))
        if "ovms" in url:
            raise urllib.error.URLError("connection refused")
        return FakeResp(b'{"choices": []}')

    monkeypatch.setattr(ai_apps, "_open", fake_open)
    monkeypatch.setattr(
        "backend.services.rag_embeddings._resolve_ollama_host", lambda h=None: h or "http://ollama:11434"
    )
    r = client.post(
        "/api/v1/ai/openai/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=bearer(key),
    )
    assert r.status_code == 200
    assert urls == [
        ("http://ovms:8000/v1/chat/completions", "Qwen3-4B"),
        ("http://ollama:11434/v1/chat/completions", "qwen3:4b"),
    ]


def test_nothing_answering_is_a_502_in_openai_form(client, key, cfg, monkeypatch):
    def down(url, payload, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(ai_apps, "_open", down)
    for stream in (False, True):
        r = client.post(
            "/api/v1/ai/openai/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": stream},
            headers=bearer(key),
        )
        assert r.status_code == 502
        assert r.json()["error"]["type"] == "server_error"


def test_a_streamed_reply_is_passed_on(client, key, cfg, monkeypatch):
    lines = b'data: {"choices":[{"delta":{"content":"he"}}]}\n\ndata: {"choices":[{"delta":{"content":"llo"}}]}\n\ndata: [DONE]\n\n'
    monkeypatch.setattr(ai_apps, "_open", lambda url, payload, timeout: FakeResp(lines))
    r = client.post(
        "/api/v1/ai/openai/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
        headers=bearer(key),
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.content == lines


def test_embeddings_come_from_the_configured_embedder(client, key, cfg, monkeypatch):
    seen = []

    def fake_embed(text, model, host, timeout):
        seen.append((text, model, host))
        return b"", [0.6, 0.8]

    monkeypatch.setattr("backend.services.rag_embeddings.compute_neural_embedding_via_ollama", fake_embed)
    r = client.post("/api/v1/ai/openai/embeddings", json={"input": ["a", "b"], "model": "x"}, headers=bearer(key))
    assert r.status_code == 200, r.text
    data = r.json()
    assert [d["index"] for d in data["data"]] == [0, 1] and data["model"] == ai_apps.EMBED_MODEL
    assert seen == [("a", "embeddinggemma-2-ov", "http://eg2:11434"), ("b", "embeddinggemma-2-ov", "http://eg2:11434")]
    assert client.post("/api/v1/ai/openai/embeddings", json={"input": []}, headers=bearer(key)).status_code == 400


def test_the_owners_role_switch_still_applies(client, key, cfg, monkeypatch):
    monkeypatch.setattr(ai_access, "allowed", lambda principal, cfg=None, feature="ask": False)
    r = client.post(
        "/api/v1/ai/openai/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=bearer(key),
    )
    assert r.status_code == 403 and "turned off" in r.json()["error"]["message"]


def test_bad_bodies(client, key, cfg):
    url = "/api/v1/ai/openai/chat/completions"
    assert client.post(url, json={"messages": []}, headers=bearer(key)).status_code == 400
    assert client.post(url, json=[1], headers=bearer(key)).status_code == 400
    r = client.post(url, content=b"nope", headers={**bearer(key), "Content-Type": "application/json"})
    assert r.status_code == 400


@pytest.mark.parametrize(
    ("endpoint", "want"),
    [
        ("http://ovms:8000/v3", "http://ovms:8000/v3/chat/completions"),
        ("http://lm:1234/v1/chat/completions", "http://lm:1234/v1/chat/completions"),
        ("http://ollama:11434", "http://ollama:11434/v1/chat/completions"),
    ],
)
def test_where_chat_goes(endpoint, want, monkeypatch):
    monkeypatch.setattr("backend.services.rag_embeddings._resolve_ollama_host", lambda h=None: "http://ollama:11434")
    ups = ai_apps.chat_upstreams({"active_model": "m", "llm_endpoint": endpoint})
    assert ups == [(want, "m")]
    assert ai_apps.chat_upstreams({"active_model": "m"}) == [("http://ollama:11434/v1/chat/completions", "m")]
