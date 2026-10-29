"""Codes, IDs and quoted phrases in a search (AI-12, AI-31).

"INV-2025-0471", "SN-7XK2-90QB", "order 58213310", "v2.3.10" or "keep the blue lantern lit" in
quotes mean that exact text. Meaning-based scoring treats INV-2025-0471 and INV-2025-0417 as the
same thing, so when a query holds such terms the keyword side leads and a file that contains all
of them exactly ranks first. A code only matches as a whole: v2.3.1 is not found inside v2.3.10.
"""

from __future__ import annotations

import re

# "…", “…”, „…“, «…», 「…」 and 『…』
_QUOTED = re.compile(
    r'"([^"]{2,120})"|“([^”]{2,120})”|„([^“”"]{2,120})[“”"]|«\s*([^»]{2,120}?)\s*»|「([^」]{2,120})」|『([^』]{2,120})』'
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]*[A-Za-z0-9]")


def _is_code(token: str) -> bool:
    digits = sum(c.isdigit() for c in token)
    letters = sum(c.isalpha() for c in token)
    seps = sum(c in "._/:-" for c in token)
    if not digits:
        return False
    if not letters and not seps:
        return digits >= 5  # an order or account number; a year or a count is not a code
    if seps and digits:
        return len(token) >= 4 and not re.fullmatch(r"\d{1,2}[:.]\d{2}", token)  # not a time or a price
    return len(token) >= 5  # WD40EFRX, SIM115, A1B2C3


def exact_terms(query: str) -> list[str]:
    """The quoted phrases and codes in a query, lower-case, in the order they appear."""
    text = query or ""
    out: list[str] = []
    for groups in _QUOTED.findall(text):
        phrase = " ".join(next(g for g in groups if g).split()).lower()
        if phrase and phrase not in out:
            out.append(phrase)
    rest = _QUOTED.sub(" ", text)
    for token in _TOKEN.findall(rest):
        token = token.rstrip(".:/-").lower()
        if _is_code(token) and token not in out:
            out.append(token)
    return out


def _contains(term: str, text: str) -> bool:
    if " " in term:
        return term in " ".join(text.split())
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def matched(terms: list[str], text: str) -> int:
    """How many of the terms the (lower-case) text contains exactly."""
    return sum(1 for t in terms if _contains(t, text))
