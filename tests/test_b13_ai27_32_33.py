"""B13 (AI-27, AI-32, AI-33): a stuck embedder costs one deadline and trips the shared breaker;
grounding embeds in one batched call; a mid-stream failure is not answered twice and the prompt
goes to at most two servers; the evidence is trimmed before the question; tokens are estimated by
script; Ollama gets think:false and a reply cap."""

import io
import json
import time
import urllib.error

import pytest

from backend.services import ai_chat_agent, chat_context, rag_embeddings, rag_grounding


# --- AI-27 ------------------------------------------------------------------------------------
def test_a_stuck_embedder_costs_one_deadline_then_is_skipped(monkeypatch):
    calls = []

    def stuck(text, model, host=None, timeout=1.8, target_dim=None, is_query=False, task_prompt=None, deadline=None):
        calls.append((timeout, deadline))
        return None

    monkeypatch.setattr(rag_embeddings, "compute_neural_embedding_via_ollama", stuck)
    rag_embeddings._QUERY_VEC_CACHE.clear()
    model, _vec = rag_embeddings.compute_multimodal_query_embedding("where is the lease", model="embeddinggemma")
    assert model == "zett_lexical_384d" and 1 <= len(calls) <= 2
    assert all(d is not None and t <= rag_embeddings.QUERY_EMBED_TIMEOUT for t, d in calls)
    assert rag_embeddings._EMBED_BREAKER["until"] > time.time()
    calls.clear()
    assert (
        rag_embeddings.compute_multimodal_query_embedding("and the deposit", model="embeddinggemma")[0]
        == "zett_lexical_384d"
    )
    assert calls == []  # the breaker: no second wait


def test_every_request_of_one_embedding_shares_the_deadline(monkeypatch):
    waits = []

    def urlopen(req, timeout=None):
        waits.append(timeout)
        raise urllib.error.URLError("down")

    monkeypatch.setattr(rag_embeddings.urllib.request, "urlopen", urlopen)
    assert (
        rag_embeddings.compute_neural_embedding_via_ollama(
            "x", model="m", host="http://h:1", timeout=5, deadline=time.monotonic() + 2
        )
        is None
    )
    assert waits and all(w <= 2 for w in waits)
    waits.clear()
    assert (
        rag_embeddings.compute_neural_embedding_via_ollama(
            "x", model="m", host="http://h:1", deadline=time.monotonic() - 1
        )
        is None
    )
    assert waits == []  # past its deadline: nothing is sent


def test_grounding_embeds_sources_and_sentences_in_one_call():
    batches = []

    def embed(text):
        raise AssertionError("one call per text")

    def many(texts):
        batches.append(list(texts))
        return [[1.0, 0.0]] * len(texts)

    embed.many = many
    res = rag_grounding.score_answer_grounding(
        "The rent is due on the first. It is paid by transfer.",
        [{"name": "lease.pdf", "excerpt": "Rent due monthly"}],
        embed=embed,
    )
    assert len(batches) == 1 and res["method"] == "neural"
    assert len(batches[0]) == 1 + res["total"]


def test_grounding_without_vectors_stays_lexical():
    def embed(text):
        return None

    embed.many = lambda texts: None
    res = rag_grounding.score_answer_grounding(
        "The rent is due on the first.", [{"name": "lease", "excerpt": "rent first"}], embed=embed
    )
    assert res["method"] == "lexical"


def test_batched_question_vectors_share_the_breaker(monkeypatch):
    monkeypatch.setattr(rag_embeddings, "_resolve_ollama_host", lambda host: "http://h:1")
    monkeypatch.setattr(
        rag_embeddings, "_embed_one_batch", lambda host, model, batch, timeout=None: [[3.0, 4.0]] * len(batch)
    )
    assert (
        rag_embeddings.embed_for_question(["a", "b"], "embeddinggemma")
        == [[pytest.approx(0.6), pytest.approx(0.8)]] * 2
    )
    monkeypatch.setattr(rag_embeddings, "_embed_one_batch", lambda host, model, batch, timeout=None: None)
    assert rag_embeddings.embed_for_question(["a"], "embeddinggemma") is None
    assert rag_embeddings._EMBED_BREAKER["until"] > time.time()
    assert rag_embeddings.embed_for_question(["a"], "embeddinggemma") is None
    assert rag_embeddings.embed_for_question([], "embeddinggemma") is None


# --- AI-33 ------------------------------------------------------------------------------------
def test_the_evidence_is_shortened_before_the_question():
    question = "Wann muss die Miete bezahlt werden und an wen?"
    evidence = "\n".join(f"[{i}] Source {i}: " + "Lorem ipsum dolor sit amet " * 40 for i in range(40))
    msgs = [
        {"role": "system", "content": "You answer from the sources.\nLive Context:\n" + evidence},
        {"role": "user", "content": question},
    ]
    out = chat_context._fit_to_window(msgs, None, 4096)
    assert out[-1]["content"] == question
    assert "[evidence shortened to fit]" in out[0]["content"] and out[0]["content"].startswith("You answer")
    assert "[1] Source 1" in out[0]["content"] and "[39] Source 39" not in out[0]["content"]  # weakest go
    total = sum(chat_context.estimate_tokens(m["content"]) + 4 for m in out)
    assert total <= 4096 - chat_context.REPLY_TOKENS


def test_without_marked_evidence_the_last_turn_is_shortened_as_before():
    msgs = [{"role": "system", "content": "short"}, {"role": "user", "content": "x" * 40000}]
    out = chat_context._fit_to_window(msgs, None, 4096)
    assert out[-1]["content"].endswith("[context shortened to fit]")


def test_tokens_are_estimated_by_script():
    assert chat_context.estimate_tokens("abcd" * 10) == 10
    german = "Größenänderung der Straße über Brücken " * 4
    assert chat_context.estimate_tokens(german) == -(-len(german) // 3.2)
    russian = "привет мир " * 10
    assert chat_context.estimate_tokens(russian) == -(-len(russian) // 2.5)
    assert chat_context.estimate_tokens("") == 0 and chat_context.estimate_tokens("红烧肉") == 3


# --- AI-32 and the Ollama request ---------------------------------------------------------------
class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Broken:
    """A stream that sends one piece of the answer and then the connection drops."""

    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        yield json.dumps({"message": {"content": "The rent is "}}).encode() + b"\n"
        raise ConnectionResetError("dropped")


@pytest.fixture
def ollama(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ZETTNAS_TEST_MODE", "0")
    monkeypatch.setattr(ai_chat_agent, "_get_docker_host_ips", lambda: ["10.9.9.1", "10.9.9.2", "10.9.9.3"])
    ai_chat_agent._ACTIVE_ENDPOINT_CACHE.clear()
    ai_chat_agent._ENDPOINT_REGISTRY.__init__() if hasattr(ai_chat_agent._ENDPOINT_REGISTRY, "__init__") else None
    posts, plan = [], {}

    def urlopen(req, timeout=None):
        url = req.full_url
        host = url.split("//")[1].split(":")[0]
        behaviour = plan.get(host, "down")
        if url.endswith("/api/tags"):
            if behaviour == "down":
                raise urllib.error.URLError("no route")
            return _Resp(json.dumps({"models": [{"name": "qwen3:4b"}]}).encode())
        if url.endswith("/api/ps"):
            return _Resp(b'{"models": []}')
        body = json.loads(req.data)
        posts.append((host, body, timeout))
        if behaviour == "drops":
            return _Broken()
        if behaviour == "no-think" and "think" in body:
            raise urllib.error.HTTPError(url, 400, "think not supported", {}, io.BytesIO(b""))
        if behaviour == "silent":
            raise TimeoutError("no answer")
        reply = {"message": {"content": "The rent is due on the first."}, "done": True, "eval_count": 7}
        return _Resp((json.dumps(reply) + "\n").encode())

    monkeypatch.setattr(ai_chat_agent.urllib.request, "urlopen", urlopen)
    return posts, plan


def _stream(events):
    def sink(kind, text):
        events.append((kind, text))

    return ai_chat_agent._TOKEN_SINK.set(sink)


def test_a_dropped_stream_is_reset_before_the_fallback_answers(ollama):
    posts, plan = ollama
    plan.update({"10.9.9.1": "drops", "10.9.9.2": "ok"})
    events = []
    token = _stream(events)
    try:
        reply = ai_chat_agent._try_local_llm_completion("qwen3:4b", "", [{"role": "user", "content": "rent?"}])
    finally:
        ai_chat_agent._TOKEN_SINK.reset(token)
    assert reply[0] == "The rent is due on the first."
    kinds = [k for k, _ in events]
    assert kinds.index("reset") < len(kinds) - 1 and ("token", "The rent is ") in events
    assert [h for h, _b, _t in posts] == ["10.9.9.1", "10.9.9.2"]


def test_the_prompt_goes_to_two_servers_at_most(ollama):
    posts, plan = ollama
    plan.update({"10.9.9.1": "silent", "10.9.9.2": "silent", "10.9.9.3": "ok"})
    reply = ai_chat_agent._try_local_llm_completion("qwen3:4b", "", [{"role": "user", "content": "rent?"}])
    assert reply[0] is None and [h for h, _b, _t in posts] == ["10.9.9.1", "10.9.9.2"]


def test_a_host_that_does_not_answer_gets_no_prompt(ollama):
    posts, plan = ollama
    plan.update({"10.9.9.3": "ok"})  # .1 and .2 are down
    assert ai_chat_agent._try_local_llm_completion("qwen3:4b", "", [{"role": "user", "content": "hi"}])[0]
    assert [h for h, _b, _t in posts] == ["10.9.9.3"]


def test_ollama_answers_without_thinking_and_within_a_cap(ollama):
    posts, plan = ollama
    plan.update({"10.9.9.1": "ok"})
    ai_chat_agent._try_local_llm_completion("qwen3:4b", "", [{"role": "user", "content": "hi"}])
    body = posts[0][1]
    assert body["think"] is False and body["options"]["num_predict"] == chat_context.REPLY_TOKENS


def test_an_ollama_without_the_think_field_is_asked_again_without_it(ollama):
    posts, plan = ollama
    plan.update({"10.9.9.1": "no-think"})
    reply = ai_chat_agent._try_local_llm_completion("qwen3:4b", "", [{"role": "user", "content": "hi"}])
    assert reply[0] == "The rent is due on the first." and "think" not in posts[-1][1]
