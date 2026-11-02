"""NAI-10: a chat template that opens the reasoning block itself (Qwen3 thinking models) sends
'reasoning</think>answer'. The reasoning must not reach the person as the answer."""

from backend.services import ai_chat_agent as agent
from backend.services import chat_llm_runtime as rt

STRAY = "Okay, let me try to figure out how long it bakes.\n\nThe recipe says 60.\n</think>\n\nIt bakes for 60 minutes."


def test_stray_close_tag_is_reasoning():
    think, reply = agent.extract_and_strip_reasoning(STRAY)
    assert reply == "It bakes for 60 minutes."
    assert think.startswith("Okay, let me try") and "</think>" not in think


def test_normalize_wraps_template_opened_reasoning():
    out = rt.normalize_reasoning(STRAY)
    assert out.startswith("<think>\nOkay") and out.endswith("</think>\n\nIt bakes for 60 minutes.")
    assert rt.normalize_reasoning("</think>Just the answer") == "Just the answer"


def test_whole_blocks_and_plain_text_unchanged():
    whole = "<think>hmm</think>\n\nAnswer"
    assert rt.normalize_reasoning(whole) == whole
    assert rt.normalize_reasoning("Plain answer") == "Plain answer"
    assert rt.normalize_reasoning("") == ""
    assert agent.extract_and_strip_reasoning(whole) == ("hmm", "Answer")


def test_quoted_close_tag_after_a_real_block_is_left_alone():
    text = "<think>a</think>Write </think> to end it."
    assert rt.normalize_reasoning(text) == text


def _collect():
    out = []
    return out, lambda kind, text: out.append((kind, text))


def test_stream_takes_back_template_opened_reasoning():
    out, sink = _collect()
    sp = rt._ThinkSplitter(sink)
    for piece in ("Okay, let", " me think.\n</th", "ink>\n\nIt bakes ", "60 minutes."):
        sp.feed(piece)
    sp.flush()
    kinds = [k for k, _ in out]
    assert "reset" in kinds
    after = out[kinds.index("reset") + 1 :]
    assert "".join(t for k, t in after if k == "think") == "Okay, let me think.\n"
    assert "".join(t for k, t in after if k == "token") == "It bakes 60 minutes."


def test_stream_without_tags_never_resets():
    out, sink = _collect()
    sp = rt._ThinkSplitter(sink)
    for piece in ("It bakes ", "60 min", "utes."):
        sp.feed(piece)
    sp.flush()
    assert [k for k, _ in out] == ["token"] * len(out)
    assert "".join(t for _, t in out) == "It bakes 60 minutes."


def test_stream_close_tag_first_is_not_a_reset():
    out, sink = _collect()
    sp = rt._ThinkSplitter(sink)
    sp.feed("</think>\n\nAnswer")
    sp.flush()
    assert ("reset", "") not in out
    assert "".join(t for k, t in out if k == "token") == "Answer"


def test_stream_real_block_then_quoted_close_tag_stays_answer():
    out, sink = _collect()
    sp = rt._ThinkSplitter(sink)
    sp.feed("<think>a</think>Write </think> to end it.")
    sp.flush()
    assert "".join(t for k, t in out if k == "token") == "Write </think> to end it."
