"""AI-28: one re-ask when an answer isn't backed by its sources, and "Sources", not "Verified"."""

from backend.services import ai_chat_agent as agent
from backend.services import chat_reask

LOW = {
    "score": 0,
    "supported": 0,
    "total": 2,
    "sentences": [{"text": "The roof is red.", "supported": False}, {"text": "It cost 9 EUR.", "supported": False}],
}
HIGH = {"score": 100, "supported": 2, "total": 2, "sentences": []}


def test_when_to_reask():
    assert chat_reask.needs_reask(LOW)
    assert not chat_reask.needs_reask(HIGH)
    assert not chat_reask.needs_reask(None)
    assert not chat_reask.needs_reask({"score": 0, "total": 1})  # one sentence is too little to judge
    assert not chat_reask.needs_reask({"score": 50, "total": 4})


def test_the_reask_names_the_unsupported_sentences():
    msgs = chat_reask.reask_messages(
        [{"role": "system", "content": "s"}, {"role": "tool", "content": ""}], "first", LOW
    )
    assert [m["role"] for m in msgs] == ["system", "assistant", "user"]
    assert "The roof is red." in msgs[-1]["content"] and "[1]" in msgs[-1]["content"]
    assert "(most of them)" in chat_reask.reask_messages([], "x", {"sentences": []})[-1]["content"]


def test_better():
    assert chat_reask.better(LOW, HIGH)
    assert not chat_reask.better(HIGH, LOW)
    assert not chat_reask.better(LOW, dict(LOW))  # a tie keeps the first
    assert not chat_reask.better(LOW, None)
    assert chat_reask.better(None, LOW)


def _run(monkeypatch, second, second_detail):
    asked = []

    def complete(**kw):
        asked.append(kw)
        assert agent._TOKEN_SINK.get() is None  # the re-ask is not streamed
        return (second, "Ollama (m)", 1, None, None, None)

    monkeypatch.setattr(agent, "_try_local_llm_completion", complete)
    monkeypatch.setattr(agent, "score_answer_grounding", lambda text, cites, embed=None: second_detail)
    monkeypatch.setattr(agent, "_grounding_embedder", lambda cfg: None)
    shown = []
    token = agent._TOKEN_SINK.set(lambda kind, text: shown.append((kind, text)))
    try:
        out = agent._turn_reask(
            active_model="m",
            cfg={},
            citations=[{"name": "a.md"}],
            grounding_detail=LOW,
            grounding_score=0,
            llm_endpoint="",
            llm_messages=[{"role": "user", "content": "q"}],
            llm_reply="first",
            web_sources=[],
        )
    finally:
        agent._TOKEN_SINK.reset(token)
    return out, asked, shown


def test_a_better_second_answer_replaces_the_first(monkeypatch):
    (reply, detail, score), asked, shown = _run(monkeypatch, "The roof is blue [1].", HIGH)
    assert reply.startswith("The roof is blue") and score == 100 and detail["reasked"] is True
    assert len(asked) == 1 and asked[0]["tools"] is None
    assert shown[0] == ("reset", "") and shown[1][0] == "token"


def test_a_worse_second_answer_keeps_the_first(monkeypatch):
    (reply, detail, score), asked, shown = _run(monkeypatch, "Still guessing.", LOW)
    assert reply == "first" and score == 0 and detail["reasked"] is True and shown == []


def test_no_second_answer_keeps_the_first(monkeypatch):
    (reply, detail, score), asked, shown = _run(monkeypatch, None, HIGH)
    assert reply == "first" and detail is LOW and shown == []


def test_no_reask_for_web_answers_or_supported_ones(monkeypatch):
    def never(**kw):
        raise AssertionError("asked again")

    monkeypatch.setattr(agent, "_try_local_llm_completion", never)
    common = dict(active_model="m", cfg={}, grounding_score=0, llm_endpoint="", llm_messages=[], llm_reply="first")
    assert agent._turn_reask(citations=[{}], grounding_detail=LOW, web_sources=[{"url": "u"}], **common)[0] == "first"
    assert agent._turn_reask(citations=[{}], grounding_detail=HIGH, web_sources=[], **common)[0] == "first"
    assert agent._turn_reask(citations=[], grounding_detail=LOW, web_sources=[], **common)[0] == "first"
