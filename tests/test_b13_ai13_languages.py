"""B13 (AI-13): questions in German, French, Spanish and Chinese are read like English ones; CJK
text is found by keyword; photo captions come in the household language and reach the photo's
vector; the cross-language set has 200+ queries."""

import os
import sqlite3

import pytest
from PIL import Image

from backend.services import rag_cjk, rag_lang
from backend.services import vision_queue as vq
from backend.services.rag_embeddings import TASK_PREFIX_QA, classify_query_task_intent
from backend.services.rag_engine import RagSearchEngine
from backend.services.rag_text import build_safe_fts5_query, parse_multimodal_query

# ranking and indexing, not permissions: a search without a principal sees every file
pytestmark = pytest.mark.usefixtures("search_as_system")


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Zeig mir die Rechnungen von dem Handwerker", "de"),
        ("montre-moi les factures de la maison", "fr"),
        ("muéstrame las facturas de la casa", "es"),
        ("把去年的发票找出来给我看一下", "zh"),
        ("show me the invoices from the plumber", "en"),
        ("Rechnungen 2024", "en"),  # too short to tell: English rules, nothing lost
    ],
)
def test_the_language_of_a_question(text, lang):
    assert rag_lang.detect(text) == lang


def test_stop_words_follow_the_question_language():
    q = build_safe_fts5_query("Zeig mir die Rechnungen von dem Handwerker")
    assert '"rechnungen"' in q and '"handwerker"' in q
    assert '"die"' not in q and '"dem"' not in q and '"zeig"' not in q
    # "war" and "hat" are German stop words, not English ones
    assert '"war"' in build_safe_fts5_query("war photos from the hat museum")
    assert '"son"' in build_safe_fts5_query("son school report")


@pytest.mark.parametrize(
    ("query", "kind", "question_prompt"),
    [
        # a question in another language gets the embedder's question prompt, and keeps the score
        # weights of a search (the eval shows they suit the lexical vectors of those languages)
        ("wie entkalke ich die Kaffeemaschine", "search", True),
        ("comment remettre la pression de la chaudière", "search", True),
        ("dónde está la garantía de la lavadora", "search", True),
        ("空调怎么清洗", "search", True),
        ("滤网多久洗一次？", "search", True),
        ("¿cómo cambio el filtro de la lavadora?", "qa", True),  # a question mark, as before
        ("how do I bleed a radiator", "qa", True),
        ("liste alle Rechnungen von 2024", "classification", False),
        ("列出所有的发票", "classification", False),
        ("lister tous les contrats", "classification", False),
        ("boiler pressure", "search", False),
    ],
)
def test_what_a_question_asks_in_five_languages(query, kind, question_prompt):
    got_kind, prefix = classify_query_task_intent(query)
    assert got_kind == kind
    assert (prefix == TASK_PREFIX_QA) is question_prompt


def test_colours_scenes_and_kinds_of_file_in_five_languages():
    p = parse_multimodal_query("rote Blumen im Garten")
    assert p["auto_colors"] == ["red"] and "outdoor" in p["auto_scenes"] and p["modality_hint"] == "photos"
    p = parse_multimodal_query("Fotos vom Strand")
    assert p["modality_hint"] == "photos" and "beach" in p["auto_scenes"]
    p = parse_multimodal_query("海边的照片")
    assert p["modality_hint"] == "photos" and "beach" in p["auto_scenes"]
    assert parse_multimodal_query("recette de la quiche")["modality_hint"] == "recipes"
    assert parse_multimodal_query("mis facturas de la luz")["modality_hint"] == "documents"
    # 红 inside 红烧肉 is a dish, not a colour
    assert parse_multimodal_query("红烧肉的做法")["auto_colors"] == []
    assert parse_multimodal_query("chat history")["auto_scenes"] == []  # "chat" is French for cat


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "红烧肉.md").write_text(
        "# 妈妈的红烧肉\n\n五花肉五百克切块，冷水下锅焯水，小火炖一个小时，最后大火收汁。", encoding="utf-8"
    )
    (root / "空调保养.txt").write_text(
        "格力空调保养记录。每年五月请师傅清洗一次，滤网每个月自己冲洗。", encoding="utf-8"
    )
    (root / "boiler.txt").write_text("Boiler service notes. Pressure between 1.0 and 1.5 bar.", encoding="utf-8")
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    yield engine, root, tmp_path
    engine.close()


def _cjk_rows(tmp_path):
    conn = sqlite3.connect(tmp_path / "rag.db")
    try:
        return conn.execute(f"SELECT count(*) FROM {rag_cjk.TABLE}").fetchone()[0]
    finally:
        conn.close()


def test_cjk_text_gets_keyword_rows_and_loses_them_with_its_file(library):
    engine, root, tmp = library
    assert rag_cjk.grams("妈妈的红烧肉") == "妈妈 妈的 的红 红烧 烧肉"
    assert rag_cjk.grams("boiler") == "" and rag_cjk.match_query("boiler pressure") == ""
    assert rag_cjk.match_query("红烧肉") == '"红烧" OR "烧肉"'
    before = _cjk_rows(tmp)
    assert before >= 2  # the two Chinese files, not the English one
    (root / "红烧肉.md").unlink()
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    assert 0 < _cjk_rows(tmp) < before


def _keyword_hits(engine, query):
    conn = engine._get_conn(readonly=True)
    try:
        items = engine._search_documents_ro(
            conn=conn, raw_query=query, fts_query=build_safe_fts5_query(query), query_vec=[], req_scenes=[],
            only_recipes=False, path_prefix=None, limit=10, principal=None,
        )  # fmt: skip
    finally:
        conn.close()
    return [os.path.basename(i.get("path") or i.get("file_path") or "") for i in items]


def test_a_chinese_question_finds_its_file_by_keyword(library):
    engine, _root, _tmp = library
    assert "红烧肉.md" in _keyword_hits(engine, "红烧肉怎么做")
    assert "空调保养.txt" in _keyword_hits(engine, "空调滤网清洗")


def test_older_chunks_are_added_once(library):
    _engine, _root, tmp = library
    conn = sqlite3.connect(tmp / "rag.db")
    try:
        conn.execute(f"DELETE FROM {rag_cjk.TABLE}")
        conn.execute("DELETE FROM rag_meta WHERE key = 'cjk_fts_v1'")
        conn.commit()
        assert rag_cjk.backfill(conn) >= 2
        assert rag_cjk.backfill(conn) == 0  # only once
    finally:
        conn.close()


def test_the_household_language_is_what_the_documents_are_written_in(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY, chunk_level TEXT, chunk_text TEXT)")
    texts = ["Die Rechnung für die Heizung ist da und wir zahlen sie bis Ende des Monats."] * 25
    texts += ["The boiler was serviced in October and the pressure is fine."] * 5
    conn.executemany("INSERT INTO document_chunks (chunk_level, chunk_text) VALUES ('child', ?)", [(t,) for t in texts])
    assert rag_lang.household_language(conn, "db-a") == "de"
    assert rag_lang.caption_language({"caption_language": "auto"}, conn, "db-a") == "de"
    assert rag_lang.caption_language({"caption_language": "fr"}, conn, "db-a") == "fr"
    few = sqlite3.connect(":memory:")
    few.execute("CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY, chunk_level TEXT, chunk_text TEXT)")
    assert rag_lang.household_language(few, "db-b") == "en"  # too few to tell
    assert rag_lang.caption_language({}, None) == "en"


def test_the_caption_prompt_asks_for_the_household_language():
    assert vq.caption_prompt("en") == vq.PROMPT
    assert "Write the caption in German" in vq.caption_prompt("de")
    assert vq.caption_prompt("xx") == vq.PROMPT
    sent = {}

    def post(url, body, timeout):
        sent.update(body)
        return {"message": {"content": '{"caption": "Zwei Kinder am Strand", "text": ""}'}}

    token = vq._CAPTION_LANG.set("de")
    try:
        img = Image.new("RGB", (8, 8))
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".jpg") as fh:
            img.save(fh.name)
            assert vq.describe_image(fh.name, "gemma3:4b", "http://x", post=post)[0] == "Zwei Kinder am Strand"
    finally:
        vq._CAPTION_LANG.reset(token)
    assert "German" in sent["messages"][0]["content"]


def test_a_caption_reaches_the_photo_vector(tmp_path, monkeypatch):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    try:
        cfg = dict(engine.get_config())
        cfg.update({"respect_standby": False, "vision_captions": "auto", "caption_language": "de"})
        monkeypatch.setattr(engine, "get_config", lambda: cfg)
        img = tmp_path / "IMG_0001.jpg"
        Image.new("RGB", (64, 48), (200, 30, 30)).save(img)
        st = os.stat(img)
        engine._index_single_file(
            str(img), img.name, ".jpg", st.st_size, st.st_mtime_ns, None, respect_standby=False, force_wake=True
        )
        conn = engine._get_conn()
        before = conn.execute("SELECT vision_embedding_f32 FROM photo_assets").fetchone()[0]
        conn.close()
        langs = []

        def describe(path, model, host):
            langs.append(vq._CAPTION_LANG.get())
            return "Zwei Kinder bauen eine Sandburg am Strand", ""

        q = vq.VisionQueue(
            engine, describe=describe, idle=lambda: True, host=lambda: "http://o", model_picker=lambda c, h: "gemma3:4b"
        )
        assert q.process_one() == "done"
        assert langs == ["de"]
        conn = engine._get_conn()
        row = conn.execute("SELECT caption_text, vision_embedding_f32 FROM photo_assets").fetchone()
        conn.close()
        assert row[0].startswith("Zwei Kinder") and row[1] != before
    finally:
        engine.close()


def test_the_caption_language_setting(tmp_path):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    try:
        assert engine.get_config()["caption_language"] == "auto"
        assert engine.update_config({"caption_language": "es"})["caption_language"] == "es"
        assert engine.update_config({"caption_language": "klingon"})["caption_language"] == "auto"
    finally:
        engine.close()
