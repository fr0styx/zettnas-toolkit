"""
Answer grounding for Ask Zetty: context ordering, retrieval grading and the
grounding confidence score.

Split out of rag_engine.py (AI-21), which re-exports these names.
"""

import re
from typing import Any

from backend.services.rag_text import _STOPWORDS, _has_cjk, text_tokens


def apply_primacy_recency_inversion(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Mitigates 'Lost in the Middle' attention degradation by rearranging ranked evidence
    chunks [C1, C2, C3, C4, C5, ...] into a U-curve: [C1, C3, ..., C4, C2].
    Highest-scoring chunks occupy peak attention zones (prompt top and bottom).
    """
    if len(chunks) <= 2:
        return list(chunks)
    head_items: list[dict[str, Any]] = []
    tail_items: list[dict[str, Any]] = []
    for idx, item in enumerate(chunks):
        if idx % 2 == 0:
            head_items.append(item)
        else:
            tail_items.append(item)
    return head_items + list(reversed(tail_items))


class CRAGGrade(dict):
    """
    CRAG evaluation result dictionary that can also be compared directly against grade strings
    (e.g., res == 'high' or res['grade'] == 'high').
    """

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            return self.get("grade") == other
        return super().__eq__(other)

    def __str__(self) -> str:
        return str(self.get("grade") or "low")


def grade_rag_retrieval(
    query: str,
    retrieved_items: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> CRAGGrade:
    """
    Corrective RAG (CRAG) retrieval evaluator: assesses whether retrieved knowledge chunks
    contain sufficient grounded evidence to answer the query.
    Returns CRAGGrade with 'grade': 'high' (>=0.65), 'ambiguous' (0.30..0.64), or 'low' (<0.30).
    """
    items = retrieved_items if retrieved_items is not None else (citations or [])
    if not items:
        return CRAGGrade({"grade": "low", "confidence": 0.0, "reason": "No evidence chunks retrieved."})
    top_score = max(float(it.get("score") or 0.0) for it in items)
    avg_top3 = sum(float(it.get("score") or 0.0) for it in items[:3]) / max(1, min(3, len(items)))

    q_norm = (query or "").lower()
    q_words = [w for w in text_tokens(q_norm) if (len(w) >= 3 or _has_cjk(w)) and w not in _STOPWORDS]

    has_lexical = False
    if q_words:
        combined_text = " ".join(
            f"{it.get('name', '')} {it.get('excerpt', '')} {it.get('chunk_text', '')}" for it in items[:3]
        ).lower()
        has_lexical = any(w in combined_text for w in q_words)

    if top_score >= 0.65 or (top_score >= 0.48 and has_lexical):
        grade = "high"
        confidence = min(1.0, round(top_score * 1.1, 2))
    elif top_score >= 0.30 or has_lexical:
        grade = "ambiguous"
        confidence = round(max(0.40, top_score), 2)
    else:
        grade = "low"
        confidence = round(top_score, 2)

    return CRAGGrade(
        {
            "grade": grade,
            "confidence": confidence,
            "top_score": round(top_score, 3),
            "avg_top3": round(avg_top3, 3),
            "has_lexical_evidence": has_lexical,
        }
    )


class GroundingScoreResult(dict):
    """
    Grounding score result dictionary that can also be compared directly as an integer/float
    (e.g., res >= 75 or res['grounding_confidence_score'] >= 75).
    """

    def __ge__(self, other: Any) -> bool:
        return self.get("grounding_confidence_score", 0) >= int(other)

    def __gt__(self, other: Any) -> bool:
        return self.get("grounding_confidence_score", 0) > int(other)

    def __le__(self, other: Any) -> bool:
        return self.get("grounding_confidence_score", 0) <= int(other)

    def __lt__(self, other: Any) -> bool:
        return self.get("grounding_confidence_score", 0) < int(other)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return self.get("grounding_confidence_score", 0) == int(other)
        return super().__eq__(other)

    def __int__(self) -> int:
        return int(self.get("grounding_confidence_score", 0))

    def __float__(self) -> float:
        return float(self.get("grounding_confidence_score", 0))


def compute_grounding_confidence_score(answer_text: str, evidence_texts: str | list[str]) -> GroundingScoreResult:
    """
    Fast Python NLI entailment check (<2ms) verifying that factual claims in the generated
    response are grounded in the retrieved context evidence.
    Returns GroundingScoreResult with grounding_confidence_score (0-100%).
    """
    if isinstance(evidence_texts, str):
        evidence_list = [evidence_texts]
    elif isinstance(evidence_texts, (list, tuple, set)):
        evidence_list = list(evidence_texts)
    else:
        evidence_list = [str(evidence_texts)]

    if not answer_text or not evidence_list:
        return GroundingScoreResult(
            {
                "grounding_confidence_score": 0,
                "grounded_sentences": 0,
                "total_sentences": 0,
                "unsupported_claims": [],
            }
        )

    # Split answer into clean sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer_text) if len(s.strip()) > 15]
    if not sentences:
        # Nothing checkable is not the same as fully supported.
        return GroundingScoreResult(
            {
                "grounding_confidence_score": 0,
                "grounded_sentences": 0,
                "total_sentences": 0,
                "unsupported_claims": [],
            }
        )

    evidence_joined = " ".join(evidence_list).lower()
    evidence_tokens = set(re.findall(r"[a-z0-9_\u00c0-\u024f\u4e00-\u9fff]+", evidence_joined))

    grounded_count = 0
    unsupported: list[str] = []

    for sent in sentences:
        sent_words = [
            w
            for w in re.findall(r"[a-z0-9_\u00c0-\u024f\u4e00-\u9fff]+", sent.lower())
            if len(w) >= 3 and w not in _STOPWORDS
        ]
        if not sent_words:
            grounded_count += 1
            continue

        supported_words = sum(1 for w in sent_words if w in evidence_tokens)
        overlap_ratio = supported_words / len(sent_words)

        if overlap_ratio >= 0.30:
            grounded_count += 1
        else:
            unsupported.append(sent[:120])

    score_pct = int(round((grounded_count / len(sentences)) * 100))
    return GroundingScoreResult(
        {
            "grounding_confidence_score": score_pct,
            "grounded_sentences": grounded_count,
            "total_sentences": len(sentences),
            "unsupported_claims": unsupported[:5],
        }
    )


# ---------------------------------------------------------------------------
# Grounding of the final answer, sentence by sentence (AI-1)
# ---------------------------------------------------------------------------
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|(?<=[。！？])|\n+")
_META = re.compile(
    r"^(?:sources?|quellen|fuentes|références|来源)\s*[:：]|"
    r"\b(?:i (?:could ?n[o']t|did ?n[o']t|cannot|can't) find|not (?:in|found in) (?:your|the) (?:files|documents|sources))\b",
    re.I,
)
_DIGITS = re.compile(r"\d+")
SENTENCE_SIMILARITY_MIN = 0.72  # neural cosine at which a sentence counts as said by a source


def _answer_sentences(answer: str) -> list[str]:
    out = []
    for raw in _SENTENCE_SPLIT.split(str(answer or "")):
        t = re.sub(r"\[(\d+)\]", "", raw)  # citation markers
        t = re.sub(r"^[\s>*#\-•\d.)]+", "", t).strip(" *_`")
        if not t or _META.search(t):
            continue
        words = [w for w in text_tokens(t.lower()) if w not in _STOPWORDS]
        if len(words) < 3 and not _DIGITS.search(t) and not _has_cjk(t):
            continue  # headings, "Sure!", one-word lines
        out.append(t)
    return out


def score_answer_grounding(
    answer: str,
    sources: list[dict[str, Any]] | None,
    embed: Any = None,
) -> dict[str, Any] | None:
    """How much of the final answer the cited sources back up.

    Each factual sentence is supported when every number in it appears in one source and the
    rest matches that source: by shared words, or, when `embed` (text -> vector) is given, by
    meaning, so an English answer about a German file can count. Returns None when there is
    nothing to score (no sources or no factual sentences).
    """
    texts = [
        # everything the model was shown, not just the 320-character excerpt (AI-6)
        " ".join(
            str(src.get(k) or "")
            for k in ("name", "breadcrumb", "full_parent_context", "excerpt", "raw_chunk_text", "chunk_text")
        )
        for src in (sources or [])
    ]
    texts = [t for t in texts if t.strip()]
    sentences = _answer_sentences(answer)
    if not texts or not sentences:
        return None
    src_tokens = [set(text_tokens(t.lower())) for t in texts]
    src_digits = [set(_DIGITS.findall(t)) for t in texts]
    src_vecs: list[Any] | None = None
    method = "lexical"
    if embed is not None:
        try:
            src_vecs = [embed(t[:1500]) for t in texts]
            method = "neural" if all(v for v in src_vecs) else "lexical"
        except Exception:
            src_vecs = None

    from backend.services.rag_embeddings import cosine_similarity_vec

    rows = []
    for sent in sentences:
        digits = set(_DIGITS.findall(sent))
        words = [w for w in text_tokens(sent.lower()) if w not in _STOPWORDS and not w.isdigit()]
        sent_vec = None
        if method == "neural" and src_vecs and embed is not None:
            try:
                sent_vec = embed(sent)
            except Exception:
                sent_vec = None
        best, best_i = 0.0, None
        for i, toks in enumerate(src_tokens):
            if digits and not digits <= src_digits[i]:
                continue  # a number the source does not contain is not supported by it
            lex = (sum(1 for w in words if w in toks) / len(words)) if words else (1.0 if digits else 0.0)
            sim = cosine_similarity_vec(sent_vec, src_vecs[i]) if (sent_vec and src_vecs and src_vecs[i]) else 0.0
            support = max(lex, sim / SENTENCE_SIMILARITY_MIN * 0.6 if sim else 0.0)
            if support > best:
                best, best_i = support, i
        # numbers that all appear in the source are strong evidence, so fewer words need to match
        need = 0.4 if digits else 0.6
        source = best_i + 1 if (best_i is not None and best >= need) else None
        rows.append({"text": sent[:300], "supported": source is not None, "source": source})
    supported = sum(1 for r in rows if r["supported"])
    return {
        "score": round(100 * supported / len(rows)),
        "supported": supported,
        "total": len(rows),
        "method": method,
        "sentences": rows,
    }
