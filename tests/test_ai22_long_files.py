"""AI-22: a whole-file question about a long file is answered from notes on each part."""

from backend.services import chat_nas_tools, file_map_reduce


def _chunks(n, size=5000):
    return [
        {
            "chunk_id": i,
            "text": f"section {i} " + "x" * size,
            "heading": "",
            "line_start": i * 10 + 1,
            "line_end": i * 10 + 10,
        }
        for i in range(n)
    ]


def test_parts_follow_the_reading_order_and_stay_under_the_size():
    parts = file_map_reduce.windows(_chunks(5), size=12000)
    assert [[c["chunk_id"] for c in p] for p in parts] == [[0, 1], [2, 3], [4]]


def test_a_very_long_file_is_read_at_evenly_spread_parts():
    parts = file_map_reduce.windows(_chunks(40), size=6000, limit=4)
    assert [p[0]["chunk_id"] for p in parts] == [0, 10, 20, 30]


def test_parts_without_anything_relevant_are_left_out():
    answers = iter(["- rent is 900", "-", "- ends in May"])
    notes = file_map_reduce.map_notes("lease.pdf", "summary?", _chunks(5), lambda m: next(answers))
    assert [n["part"] for n in notes] == [1, 3] and notes[0]["of"] == 3


def test_no_model_means_no_notes():
    assert file_map_reduce.map_notes("a.pdf", "q", _chunks(3), lambda m: None) is None


def test_the_question_and_the_part_reach_the_model():
    seen = []
    file_map_reduce.map_notes("lease.pdf", "Was steht drin?", _chunks(1, 100), lambda m: seen.append(m) or "- x")
    prompt = seen[0][1]["content"]
    assert "Was steht drin?" in prompt and "Part 1 of 1" in prompt and "section 0" in prompt


class _Rag:
    def __init__(self, total):
        self.total = total

    def file_chunks(self, path, max_chars=16000):
        chunks, used = [], 0
        for c in _chunks(self.total):
            if used + len(c["text"]) > max_chars:
                break
            used += len(c["text"])
            chunks.append(c)
        return {
            "found": True,
            "file_id": 7,
            "name": "report.pdf",
            "title": "Report",
            "doc_type": "document",
            "chunks": chunks,
            "complete": len(chunks) == self.total,
        }

    def get_config(self):
        return {"active_model": "m", "llm_endpoint": "http://llm"}

    def get_folder_manifest(self, *a):
        return None

    def ask(self, **kw):
        return {"citations": [], "answer": ""}


def _ask(monkeypatch, question, reply):
    rag = _Rag(10)
    monkeypatch.setattr(chat_nas_tools, "_core", lambda: type("C", (), {"get_rag_engine": staticmethod(lambda: rag)}))
    from backend.services import chat_llm_runtime

    calls = []
    monkeypatch.setattr(
        chat_llm_runtime,
        "_try_local_llm_completion",
        lambda **kw: calls.append(kw) or (reply, "x", 0, None, None, None),
    )
    token = chat_nas_tools.FOCUS_PATH.set("/mnt/user/docs/report.pdf")
    try:
        return chat_nas_tools.tool_search_nas_knowledge(question), calls
    finally:
        chat_nas_tools.FOCUS_PATH.reset(token)


def test_a_summary_of_a_long_file_reads_every_part(monkeypatch):
    out, calls = _ask(monkeypatch, "Fasse den Bericht zusammen", "- Umsatz stieg um 4 %")
    assert len(calls) == 5 and all(c["tools"] is None for c in calls)
    assert out["citations_count"] == 5 and out["citations"][0]["breadcrumb"] == "part 1 of 5"
    assert "Notes from part 5 of 5" in out["context_text"] and "Umsatz" in out["context_text"]
    assert out["citations"][-1]["line_end"] == 100


def test_without_a_model_the_first_part_is_read_as_before(monkeypatch):
    out, calls = _ask(monkeypatch, "summarize this", None)
    assert len(calls) == 1
    assert "section 0" in out["context_text"] and "Notes from" not in out["context_text"]
