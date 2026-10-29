"""One more try when an answer isn't backed by its sources (AI-28).

After an answer from the person's documents, each factual sentence is checked against the
sources (rag_grounding.score_answer_grounding). When fewer than half of them are backed, the
model is asked once more, shown which sentences had no support, to answer only from the sources
and to say what they don't contain. The better-supported of the two answers is kept; a tie keeps
the first. Never more than one re-ask per turn.
"""

from __future__ import annotations

from typing import Any

LOW_SUPPORT = 50  # % of factual sentences backed by a source
MIN_SENTENCES = 2  # one short sentence is too little to judge

REASK_NOTE = (
    "Some sentences in your answer are not supported by the numbered sources above:\n{claims}\n\n"
    "Answer the question again using only what the sources say. Cite each fact with its source "
    "number like [1]. If the sources don't contain something, say so plainly instead of guessing."
)


def needs_reask(detail: dict[str, Any] | None) -> bool:
    """True when most of a checked answer has no source behind it."""
    if not detail:
        return False
    return int(detail.get("total") or 0) >= MIN_SENTENCES and int(detail.get("score") or 0) < LOW_SUPPORT


def reask_messages(messages: list[dict[str, Any]], reply: str, detail: dict[str, Any]) -> list[dict[str, Any]]:
    """The conversation so far, the first answer, and the request to answer again."""
    unsupported = [r.get("text", "") for r in detail.get("sentences") or [] if not r.get("supported")]
    claims = "\n".join(f"- {c[:200]}" for c in unsupported[:6]) or "- (most of them)"
    return [
        *[m for m in messages if m.get("role") != "tool" or m.get("content")],
        {"role": "assistant", "content": reply},
        {"role": "user", "content": REASK_NOTE.format(claims=claims)},
    ]


def better(first: dict[str, Any] | None, second: dict[str, Any] | None) -> bool:
    """True when the second answer's grounding beats the first's."""
    if not second:
        return False
    if not first:
        return True
    return int(second.get("score") or 0) > int(first.get("score") or 0)
