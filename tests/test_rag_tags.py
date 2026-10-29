import pytest

"""Auto-tags and the document filters (B8): what kind of paper a file is, and its year."""

import os
import sqlite3
import time

from backend.services import rag_tags

# ranking and indexing, not permissions: a search without a principal sees every file
pytestmark = pytest.mark.usefixtures("search_as_system")

NOW = time.mktime((2026, 10, 1, 0, 0, 0, 0, 0, -1))


def test_household_papers_get_their_kind_in_five_languages():
    cases = [
        ("Rechnung_Stadtwerke.pdf", "", "Rechnungsbetrag 84,20 EUR, zahlbar bis 15.11.2026. MwSt 19 %.", "bill"),
        ("payslip_october.pdf", "", "Gross pay 3,200.00 Net pay 2,410.55 Payroll October 2026", "payslip"),
        ("bail.pdf", "Contrat de location", "Le loyer est payable au propriétaire. Préavis de trois mois.", "home"),
        ("poliza.pdf", "", "Seguro de hogar, póliza HX-4471, prima anual, siniestro", "insurance"),
        ("体检报告.pdf", "", "医院 医生 诊断 结果正常", "medical"),
        ("Steuerbescheid 2025.pdf", "", "Finanzamt Musterstadt, Einkommensteuer 2025", "tax"),
        ("boarding pass.pdf", "", "Flight LH 400, boarding pass, seat 14A, check-in closes", "travel"),
    ]
    for name, title, text, kind in cases:
        assert kind in rag_tags.tags_for(name, title, "generic", text, now=NOW), name


def test_one_stray_word_is_not_enough():
    assert rag_tags.tags_for("notes.md", "", "generic", "I paid the bill.", now=NOW) == []
    # but one word in the file name is
    assert rag_tags.tags_for("invoice-123.pdf", "", "generic", "", now=NOW) == ["bill"]


def test_kinds_are_capped_best_first_and_the_year_follows():
    text = "invoice receipt subtotal vat contract agreement hereby insurance premium claim tax hmrc 2025 2025 2024"
    tags = rag_tags.tags_for("doc.pdf", "", "generic", text, now=NOW)
    assert len([t for t in tags if not t.startswith("year:")]) == rag_tags.MAX_TAGS
    assert tags[0] == "bill" and tags[-1] == "year:2025"


def test_the_year_is_the_one_named_most_and_never_the_far_future():
    assert rag_tags.document_year("statement 2024, paid 2024, due 2025", NOW) == 2024
    assert rag_tags.document_year("warranty until 2031, bought 2026", NOW) == 2026
    assert rag_tags.document_year("no dates here", NOW) is None
    assert rag_tags.document_year("order 120034", NOW) is None


def test_recipes_and_invoices_keep_what_the_parser_found():
    assert rag_tags.tags_for("pancakes.md", "", "recipe", "flour eggs milk", now=NOW)[0] == "recipe"
    assert "bill" in rag_tags.tags_for("scan.pdf", "", "invoice", "", now=NOW)


def test_only_known_filters_are_accepted():
    assert rag_tags.valid(["Bill", "bill", "year:2024", "year:1800", "drop table", None]) == ["bill", "year:2024"]
    assert rag_tags.filter_sql([]) == ("", [])
    sql, params = rag_tags.filter_sql(["bill", "year:2024"])
    assert sql.count("doc_tags") == 2 and params == ["bill", "year:2024"]


def _index(tmp_path):
    conn = sqlite3.connect(tmp_path / "idx.db")
    conn.executescript(
        """CREATE TABLE indexed_files (file_id INTEGER PRIMARY KEY, file_name TEXT, doc_title TEXT, doc_type TEXT,
               modality TEXT, parse_status TEXT, visibility_tier TEXT, owner_username TEXT);
           CREATE TABLE document_chunks (file_id INTEGER, chunk_index INTEGER, chunk_level TEXT, chunk_text TEXT);"""
    )
    rag_tags.ensure_schema(conn)
    files = [
        (1, "invoice_may.pdf", "", "generic", "document", "public_share", "", "amount due 40 EUR, 2025"),
        (2, "holiday.jpg", "", "photo", "photo", "public_share", "", ""),
        (3, "lohnabrechnung.pdf", "", "generic", "document", "user_home", "dad", "Bruttolohn Nettolohn 2025"),
        (4, "notes.txt", "", "generic", "document", "public_share", "", "shopping list"),
    ]
    for fid, name, title, dt, mod, tier, owner, text in files:
        conn.execute(
            "INSERT INTO indexed_files VALUES (?, ?, ?, ?, ?, 'ok', ?, ?)", (fid, name, title, dt, mod, tier, owner)
        )
        conn.execute("INSERT INTO document_chunks VALUES (?, 0, 'child', ?)", (fid, text))
    return conn


def test_older_documents_are_tagged_from_the_index_once(tmp_path):
    conn = _index(tmp_path)
    assert rag_tags.backfill(conn) == 3  # every document but the photo
    tags = dict(conn.execute("SELECT file_id, group_concat(tag) FROM doc_tags GROUP BY file_id").fetchall())
    assert tags[1] == "bill,year:2025" and "payslip" in tags[3] and 4 not in tags
    assert rag_tags.backfill(conn) == 0  # nothing read twice, not even the untagged one
    # a file that left the index loses its tags on the next empty round
    conn.execute("DELETE FROM indexed_files WHERE file_id = 1")
    assert rag_tags.backfill(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM doc_tags WHERE file_id = 1").fetchone()[0] == 0


def test_counts_cover_only_what_the_person_may_see(tmp_path):
    conn = _index(tmp_path)
    rag_tags.backfill(conn)
    everyone = rag_tags.counts(conn, "f.visibility_tier = 'public_share'", [])
    assert everyone == {"bill": 1, "year:2025": 1}
    dad = rag_tags.counts(conn, "(f.visibility_tier = 'public_share' OR f.owner_username = ?)", ["dad"])
    assert dad["payslip"] == 1 and dad["year:2025"] == 2


def test_search_filters_and_the_api_lists_the_chips(tmp_path, monkeypatch):
    """Through the real engine: index two files, filter by a tag, count the chips."""
    from backend.services import rag_engine

    monkeypatch.setattr(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = rag_engine.RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    root = tmp_path / "docs"
    root.mkdir()
    (root / "invoice_may.txt").write_text("Invoice number 7. Amount due 40 EUR. Subtotal 33. May 2025.")
    (root / "garden.txt").write_text("Plant the tomatoes in May when the soil is warm.")
    try:
        cfg = dict(eng.get_config(), embedding_model="zett_lexical_384d", respect_standby=False)
        monkeypatch.setattr(eng, "get_config", lambda: cfg)
        for name in ("invoice_may.txt", "garden.txt"):
            p = str(root / name)
            eng._index_single_file(p, name, ".txt", os.path.getsize(p), 1, None, respect_standby=False, force_wake=True)
        found = eng.search("May", mode="documents", tags=["bill"], limit=10)
        names = {os.path.basename(r.get("path") or r.get("canonical_path") or "") for r in found["results"]}
        assert names == {"invoice_may.txt"}
        assert eng.search("", mode="documents", tags=["year:2025"], limit=10)["results"]
        assert eng.tag_counts(None).get("bill") == 1

        from backend.api import media

        monkeypatch.setattr(media, "get_rag_engine", lambda: eng)
        chips = media.get_search_tags(None)
        assert {"tag": "bill", "count": 1} in chips["kinds"] and chips["years"][0]["tag"] == "year:2025"
    finally:
        eng.close()


def test_the_engine_tags_older_documents_in_the_background(tmp_path, monkeypatch):
    from backend.services import rag_engine

    monkeypatch.setattr(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = rag_engine.RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    p = tmp_path / "invoice_june.txt"
    p.write_text("Invoice number 9. Amount due 12 EUR. Subtotal 10. June 2025.")
    try:
        cfg = dict(eng.get_config(), embedding_model="zett_lexical_384d", respect_standby=False)
        monkeypatch.setattr(eng, "get_config", lambda: cfg)
        eng._index_single_file(
            str(p), p.name, ".txt", p.stat().st_size, 1, None, respect_standby=False, force_wake=True
        )
        w = eng._get_conn(readonly=False)
        w.execute("DELETE FROM doc_tags")
        w.execute("DELETE FROM doc_tags_done")  # as if indexed before tags existed
        w.commit()
        w.close()
        assert eng.tag_counts(None) == {}
        eng._tags_backfilled = False
        eng._maybe_backfill_tags()
        assert eng.tag_counts(None).get("bill") == 1 and not eng._tags_backfilled
        eng._maybe_backfill_tags()  # nothing left: done for good
        assert eng._tags_backfilled
        eng._maybe_backfill_tags()  # and no more work
        # a failing round is tried again later; a missing table counts nothing
        eng._tags_backfilled = False
        from backend.services import rag_engine_learning as rl
        from backend.services import rag_engine_search as rs

        # the engine's sqlite3 is the database driver it connects with (db_crypto)
        monkeypatch.setattr(
            rag_tags, "backfill", lambda conn: (_ for _ in ()).throw(rl.sqlite3.OperationalError("locked"))
        )
        eng._maybe_backfill_tags()
        assert not eng._tags_backfilled
        monkeypatch.setattr(
            rag_tags, "counts", lambda *a: (_ for _ in ()).throw(rs.sqlite3.OperationalError("no table"))
        )
        assert eng.tag_counts(None) == {}
    finally:
        eng.close()
