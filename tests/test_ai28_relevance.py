"""AI-12/AI-28: the reranker reads whole chunks, and tells Zetty when no found document answers."""

import json

import httpx

from backend.services import ai_chat_agent as agent
from backend.services import rag_rerank

URL = "http://zettnas-xenc:8000/v3/rerank"


def _client(scores, seen=None):
    def handle(request):
        if seen is not None:
            seen.update(json.loads(request.content))
        rows = [{"index": i, "relevance_score": s} for i, s in enumerate(scores)]
        return httpx.Response(200, json={"results": rows})

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_relevance_is_the_best_score_and_none_without_a_reranker():
    seen = {}
    assert rag_rerank.relevance("q", ["a", "", "b"], {"rerank_endpoint": URL}, _client([0.2, 0.7], seen)) == 0.7
    assert seen["documents"] == ["a", "b"]
    assert rag_rerank.relevance("q", ["a"], {}, _client([0.9])) is None
    assert rag_rerank.relevance(" ", ["a"], {"rerank_endpoint": URL}, _client([0.9])) is None
    assert rag_rerank.relevance("q", [], {"rerank_endpoint": URL}, _client([0.9])) is None
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert rag_rerank.relevance("q", ["a"], {"rerank_endpoint": URL}, down) is None


def test_the_reranker_reads_the_whole_chunk_with_the_configured_weight():
    assert rag_rerank.weight({}) == rag_rerank.RERANK_WEIGHT
    assert rag_rerank.weight({"rerank_weight": "x"}) == rag_rerank.RERANK_WEIGHT
    assert rag_rerank.weight({"rerank_weight": 0.4}) == 0.4 and rag_rerank.weight({"rerank_weight": 7}) == 1.0
    seen = {}
    items = [
        {"title": "a", "score": 0.9, "excerpt": "short", "raw_chunk_text": "the whole first chunk"},
        {"title": "b", "score": 0.8, "excerpt": "b's excerpt"},
    ]
    cfg = {"rerank_endpoint": URL}
    out = rag_rerank.rerank_items("q", [dict(i) for i in items], cfg, _client([0.1, 0.9], seen))
    assert [i["title"] for i in out] == ["a", "b"]
    assert seen["documents"] == ["a\nthe whole first chunk", "b\nb's excerpt"]
    moved = rag_rerank.rerank_items("q", [dict(i) for i in items], {**cfg, "rerank_weight": 0.8}, _client([0.1, 0.9]))
    assert [i["title"] for i in moved] == ["b", "a"]


class _Engine:
    def __init__(self, cfg):
        self.cfg = cfg

    def get_config(self):
        return self.cfg


RESULTS = [
    {
        "tool": "search_nas_knowledge",
        "citations": [
            {"name": "garantia_lavadora.txt", "raw_chunk_text": "Garantía hasta noviembre de 2027."},
            {"name": "x.md", "excerpt": "an excerpt"},
        ],
    },
    {"tool": "get_weather", "citations": [{"name": "not a document"}]},
]


def test_zetty_says_not_found_when_no_document_answers(monkeypatch):
    asked = []
    monkeypatch.setattr(agent, "get_rag_engine", lambda: _Engine({"rerank_endpoint": URL}))
    monkeypatch.setattr(rag_rerank, "relevance", lambda q, texts, cfg: asked.append((q, texts)) or 0.0004)
    assert agent._documents_unrelated("Wann läuft die Garantie meines Fernsehers ab?", RESULTS)
    assert asked[0][1] == ["garantia_lavadora.txt\nGarantía hasta noviembre de 2027.", "x.md\nan excerpt"]
    assert not agent._documents_unrelated("q", [*RESULTS, {"tool": "browse_internet"}])  # web answers
    monkeypatch.setattr(rag_rerank, "relevance", lambda q, texts, cfg: 0.93)
    assert not agent._documents_unrelated("Wann läuft die Garantie der Waschmaschine ab?", RESULTS)
    monkeypatch.setattr(rag_rerank, "relevance", lambda q, texts, cfg: None)  # the reranker is down
    assert not agent._documents_unrelated("q", RESULTS)


def test_without_a_reranker_nothing_is_asked(monkeypatch):
    monkeypatch.setattr(agent, "get_rag_engine", lambda: _Engine({}))
    monkeypatch.setattr(rag_rerank, "relevance", lambda *a: (_ for _ in ()).throw(AssertionError("asked")))
    assert not agent._documents_unrelated("q", RESULTS)


def test_the_reply_is_in_the_question_s_language():
    from tests.rag_eval.run_eval import says_not_found

    for q, lang in [
        ("Wann läuft die Garantie meines Fernsehers ab und wo ist die Rechnung?", "de"),
        ("¿Qué día vence el seguro del coche y cuánto cuesta?", "es"),
        ("Quelle est l'heure de fermeture de la salle de sport ?", "fr"),
        ("我的护照号码是多少？", "zh"),
        ("When does the TV warranty end?", "en"),
    ]:
        reply = agent.not_found_reply(q)
        assert reply == agent.NOT_FOUND_REPLY[lang] and says_not_found(reply, q)


def test_the_model_is_not_asked_when_no_document_answers(monkeypatch):
    shown = []
    monkeypatch.setattr(agent, "_documents_unrelated", lambda q, tr: True)
    monkeypatch.setattr(agent, "_try_local_llm_completion", lambda **kw: (_ for _ in ()).throw(AssertionError("asked")))
    monkeypatch.setattr(agent, "get_rag_engine", lambda: _Engine({"rerank_endpoint": URL}))
    found = {**RESULTS[0], "status": "ok", "citations_count": 2, "photos": [], "photos_count": 0, "answer_summary": ""}
    monkeypatch.setattr(agent, "tool_search_nas_knowledge", lambda *a, **kw: dict(found))
    token = agent._TOKEN_SINK.set(lambda kind, text: shown.append((kind, text)))
    try:
        out = agent.run_agentic_chat("Wann läuft die Garantie meines Fernsehers ab?", allow_web_search=False)
    finally:
        agent._TOKEN_SINK.reset(token)
    assert agent.NOT_FOUND_REPLY["de"] in (out.get("reply") or "")
    assert ("token", agent.NOT_FOUND_REPLY["de"]) in shown
