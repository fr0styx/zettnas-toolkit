"""B13 (AI-23): the keyword top 250 is chosen among what the person may read in the chosen folder,
and a small scope is scored whole, so a folder search finds its files even when hundreds of
better keyword matches lie elsewhere."""

import os

import pytest

from backend.services import rag_engine_search
from backend.services.rag_engine import RagSearchEngine

# ranking and indexing, not permissions: a search without a principal sees every file
pytestmark = pytest.mark.usefixtures("search_as_system")


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    root = tmp_path_factory.mktemp("ai23")
    noise = root / "archive"
    noise.mkdir()
    for i in range(300):  # far better keyword matches than the one in "taxes"
        (noise / f"invoice_{i:03}.txt").write_text(f"Invoice invoice invoice number {i}. Invoice total due. Invoice.\n")
    target = root / "taxes"
    target.mkdir()
    (target / "letter.txt").write_text(
        "Dear tax office, please find attached the documents for 2025, including the invoice from the plumber.\n"
    )
    (target / "notes.txt").write_text("Remember to ask about the deduction for the home office.\n")
    engine = RagSearchEngine(db_path=str(root / "rag.db"))
    engine.index_directory(str(root))
    yield engine, root
    engine.close()


def _paths(res):
    return [r.get("canonical_path") or r.get("path") for r in res.get("results", [])]


def test_a_folder_search_finds_its_file_past_a_global_top_250(index):
    engine, root = index
    res = engine.search(query="invoice", mode="documents", path_prefix=str(root / "taxes"), match_tab="keyword")
    assert str(root / "taxes" / "letter.txt") in _paths(res)
    assert all(p.startswith(str(root / "taxes")) for p in _paths(res))


def test_without_a_folder_the_best_matches_still_lead(index):
    engine, root = index
    res = engine.search(query="invoice", mode="documents", match_tab="keyword", limit=10)
    assert _paths(res) and all("/archive/" in p for p in _paths(res)[:5])


def test_a_small_scope_is_scored_whole(index, monkeypatch):
    engine, root = index
    seen = []
    real = rag_engine_search.cosine_similarity_vec

    def counting(a, b):
        seen.append(1)
        return real(a, b)

    monkeypatch.setattr(rag_engine_search, "cosine_similarity_vec", counting)
    engine.search(query="deduction", mode="documents", path_prefix=str(root / "taxes"))
    small = len(seen)
    assert small >= 2  # both files of the folder, keyword hit or not
    monkeypatch.setattr(rag_engine_search, "DIRECT_SCOPE_CHUNKS", 0)  # too big to score whole
    seen.clear()
    res = engine.search(query="deduction", mode="documents", path_prefix=str(root / "taxes"))
    assert str(root / "taxes" / "notes.txt") in _paths(res)


def test_the_keyword_candidates_carry_the_filters():
    import inspect

    src = inspect.getsource(rag_engine_search)
    for table in ("rag_chunks_fts", "rag_photos_fts"):
        start = src.index(f"FROM {table}\n")
        block = src[start : src.index("LIMIT 250", start)]
        assert "JOIN indexed_files f" in block and "MATCH ? AND" in block, table
    assert os.path.basename(rag_engine_search.__file__) == "rag_engine_search.py"
