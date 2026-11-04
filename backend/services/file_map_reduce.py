"""Long files in parts (AI-22).

When a question covers a whole file that is longer than the model can read at once, each part
is read on its own for notes that help answer the question (map), and the answer is written
from those notes (reduce). Up to MAX_PARTS parts; a longer file is read at evenly spread parts.
"""

from collections.abc import Callable
from typing import Any

WINDOW_CHARS = 12000
MAX_PARTS = 6
NOTHING = "-"

SYSTEM = (
    "You take notes from one part of a document so that someone can later answer a question "
    "about the whole document. Use only the text you are given."
)


def windows(
    chunks: list[dict[str, Any]], size: int = WINDOW_CHARS, limit: int = MAX_PARTS
) -> list[list[dict[str, Any]]]:
    """The file's chunks in reading order, grouped into parts of about `size` characters."""
    groups: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    used = 0
    for c in chunks:
        n = len(c.get("text") or "")
        if cur and used + n > size:
            groups.append(cur)
            cur, used = [], 0
        cur.append(c)
        used += n
    if cur:
        groups.append(cur)
    if len(groups) > limit:
        step = len(groups) / limit
        groups = [groups[int(i * step)] for i in range(limit)]
    return groups


def notes_messages(name: str, question: str, part: int, total: int, text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": (
                f"Document: {name}\nPart {part} of {total}\nQuestion: {question}\n\n<part>\n{text}\n</part>\n\n"
                "Write short notes, at most 8 bullet points, with the facts from this part that help "
                "answer the question: names, numbers, dates, decisions. Write in the language of the "
                f"question. If nothing in this part helps, reply with a single {NOTHING}"
            ),
        },
    ]


def map_notes(
    name: str,
    question: str,
    chunks: list[dict[str, Any]],
    complete: Callable[[list[dict[str, str]]], str | None],
) -> list[dict[str, Any]] | None:
    """Notes per part, in order; parts with nothing relevant are left out. None when the model
    gives no answer for a part (not running, say), so the caller can fall back."""
    parts = windows(chunks)
    out: list[dict[str, Any]] = []
    for i, part in enumerate(parts, 1):
        text = "\n\n".join(c.get("text") or "" for c in part)
        note = complete(notes_messages(name, question, i, len(parts), text))
        if not note:
            return None
        note = note.strip()
        if note in (NOTHING, "—", "–"):
            continue
        out.append({"part": i, "of": len(parts), "notes": note, "chunks": part})
    return out


def context_and_citations(
    path: str, one_file: dict[str, Any], parts: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    """The answer's context (the notes) and one citation per part, pointing at its lines."""
    context = "\n\n".join(f"Notes from part {p['part']} of {p['of']}:\n{p['notes']}" for p in parts)
    cites = [
        {
            "file_id": one_file.get("file_id"),
            "name": one_file.get("name"),
            "path": path,
            "doc_title": one_file.get("title") or one_file.get("name"),
            "breadcrumb": f"part {p['part']} of {p['of']}",
            "excerpt": p["notes"][:450],
            "full_parent_context": p["notes"],
            "score": 1.0,
            "parent_chunk_id": p["chunks"][0].get("chunk_id"),
            "line_start": int(p["chunks"][0].get("line_start") or 1),
            "line_end": int(p["chunks"][-1].get("line_end") or 1),
            "page": int(p["chunks"][0].get("page") or 0),
            "doc_type": one_file.get("doc_type", "document"),
            "source_modality": "document",
        }
        for p in parts
    ]
    return context, cites
