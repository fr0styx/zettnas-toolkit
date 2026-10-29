"""AI-12, AI-31: codes, IDs and quoted phrases lead the search."""

import pytest

from backend.services import rag_engine_search as search
from backend.services import rag_exact


@pytest.mark.parametrize(
    "query,terms",
    [
        ("INV-2025-0471", ["inv-2025-0471"]),
        ("order 58213310 from 2024", ["58213310"]),
        ("what changed in firmware v2.3.10", ["v2.3.10"]),
        ('"keep the blue lantern lit"', ["keep the blue lantern lit"]),
        ("Notiz „please keep it lit“", ["please keep it lit"]),
        ("« keep the gate lit »", ["keep the gate lit"]),
        ("「keep the lantern lit」 and 『blue gate』", ["keep the lantern lit", "blue gate"]),
        ("WD40EFRX drive", ["wd40efrx"]),
        ("scan 2024-10-05.pdf", ["2024-10-05.pdf"]),
        ('"A" "a" x1 SN-1 SN-1', ["sn-1"]),  # too short for a phrase or a code, and no repeats
        ("16 TB to TiB", []),
        ("meeting at 10:30, price 12.50", []),
        ("how long do I bake the banana loaf", []),
        ("", []),
    ],
)
def test_exact_terms(query, terms):
    assert rag_exact.exact_terms(query) == terms


def test_codes_match_whole_and_phrases_across_line_breaks():
    assert rag_exact.matched(["v2.3.1"], "firmware v2.3.10 adds") == 0
    assert rag_exact.matched(["v2.3.1"], "firmware v2.3.1.") == 1
    assert rag_exact.matched(["sn-7xk2-90qa"], "serial number: sn-7xk2-90qa\n") == 1
    assert rag_exact.matched(["sn-7xk2-90qa"], "serial sn-7xk2-90qab") == 0
    assert rag_exact.matched(["keep the blue lantern lit"], "please keep the blue\nlantern lit") == 1
    assert rag_exact.matched(["58213310", "keep it"], "order 58213310") == 1


def test_fusion_weights_and_exact_score():
    assert search.fusion_weights("qa", 5, True) == (0.15, 0.60, 0.25)
    assert search.fusion_weights("code", 5, False) == (0.25, 0.55, 0.20)
    assert search.fusion_weights("qa", 5, False) == (0.60, 0.20, 0.20)
    assert search.fusion_weights("search", 2, False) == (0.35, 0.45, 0.20)
    assert search.fusion_weights("search", 3, False) == (0.50, 0.30, 0.20)
    assert search.exact_score(0.5, 2, 2) == pytest.approx(0.8)
    assert search.exact_score(0.9, 1, 1) == 1.0
    assert search.exact_score(0.5, 1, 2) == pytest.approx(0.56)
    assert search.exact_score(0.5, 0, 2) == pytest.approx(0.3)


@pytest.mark.usefixtures("search_as_system")
def test_the_file_with_the_exact_phrase_comes_first(tmp_path):
    from backend.services.rag_engine import RagSearchEngine

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# Note\n\nPlease keep the lantern lit, the blue gate is open until we are home.\n")
    (docs / "b.md").write_text("# Note\n\nPlease keep the blue lantern lit by the gate until we are home.\n")
    (docs / "c.md").write_text("# Firmware v2.3.10\n\nAdds support for 24 TB drives.\n")
    (docs / "d.md").write_text("# Firmware v2.3.1\n\nFixes the fan curve after waking.\n")
    engine = RagSearchEngine(db_path=str(tmp_path / "x.db"))
    engine.index_directory(str(docs), respect_standby=False)

    def first(q):
        items = engine.search(q, mode="documents", limit=5).get("items") or []
        return items[0]["name"] if items else None

    assert first('"keep the blue lantern lit"') == "b.md"
    assert first('"the blue gate is open"') == "a.md"
    assert first("firmware v2.3.1") == "d.md"
    assert first("firmware v2.3.10") == "c.md"
