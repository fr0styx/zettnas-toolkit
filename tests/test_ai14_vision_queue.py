"""AI-14: photos get captions and OCR text from a local vision model, only when idle."""

import os

from PIL import Image

from backend.services import vision_queue as vq
from backend.services.rag_engine import RagSearchEngine


def _engine_with_photo(tmp_path, monkeypatch):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    cfg = dict(engine.get_config())
    cfg.update({"respect_standby": False, "vision_captions": "auto"})
    monkeypatch.setattr(engine, "get_config", lambda: cfg)
    img = tmp_path / "IMG_0001.jpg"
    Image.new("RGB", (64, 48), (200, 30, 30)).save(img)
    st = os.stat(img)
    engine._index_single_file(
        str(img), img.name, ".jpg", st.st_size, st.st_mtime_ns, None, respect_standby=False, force_wake=True
    )
    return engine, cfg, str(img)


def _queue(engine, calls, idle=True):
    def describe(path, model, host):
        calls.append((path, model))
        return "Two children building a sandcastle on a beach", "BAUHAUS receipt 12.99"

    return vq.VisionQueue(
        engine,
        describe=describe,
        idle=lambda: idle,
        host=lambda: "http://ollama",
        model_picker=lambda cfg, host: "gemma3:4b",
    )


def _photo_row(engine):
    conn = engine._get_conn()
    try:
        return conn.execute("SELECT caption_text, ocr_text FROM photo_assets").fetchone()
    finally:
        conn.close()


def test_caption_and_text_reach_photo_search(tmp_path, monkeypatch):
    engine, cfg, img = _engine_with_photo(tmp_path, monkeypatch)
    calls = []
    q = _queue(engine, calls)
    assert q.process_one() == "done"
    assert q.process_one() == "empty"
    assert calls == [(img, "gemma3:4b")]
    row = _photo_row(engine)
    assert row["caption_text"].startswith("Two children building a sandcastle")
    assert "BAUHAUS receipt" in row["ocr_text"]
    conn = engine._get_conn()
    try:
        hits = conn.execute("SELECT rowid FROM rag_photos_fts WHERE rag_photos_fts MATCH 'sandcastle'").fetchall()
    finally:
        conn.close()
    assert len(hits) == 1
    st = q.status()
    assert st["captioned"] == 1 and st["photos"] == 1


def test_reindex_keeps_the_caption_without_asking_the_model_again(tmp_path, monkeypatch):
    engine, cfg, img = _engine_with_photo(tmp_path, monkeypatch)
    calls = []
    q = _queue(engine, calls)
    q.process_one()
    conn = engine._get_conn()
    conn.execute("UPDATE photo_assets SET caption_text = 'red photo'")  # what a re-index writes
    conn.commit()
    conn.close()
    assert q.process_one() == "empty"
    assert len(calls) == 1
    assert "sandcastle" in _photo_row(engine)["caption_text"]


def test_waits_when_busy_off_or_without_a_model(tmp_path, monkeypatch):
    engine, cfg, img = _engine_with_photo(tmp_path, monkeypatch)
    calls = []
    assert _queue(engine, calls, idle=False).process_one() == "busy"
    cfg["vision_captions"] = "off"
    assert _queue(engine, calls).process_one() == "disabled"
    cfg["vision_captions"] = "auto"
    q = _queue(engine, calls)
    q.model_picker = lambda cfg, host: None
    assert q.process_one() == "no-model"
    assert calls == []


def test_model_detection_and_reply_parsing():
    vq._MODEL_CACHE.clear()

    def fetch(url, body=None, timeout=10):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen2.5:3b"}, {"name": "gemma3:4b"}]}
        return {"capabilities": ["completion", "vision"] if body["model"] == "gemma3:4b" else ["completion"]}

    assert vq.pick_model({}, "http://h", fetch) == "gemma3:4b"
    assert vq.pick_model({"vision_model": "llava"}, "http://h", fetch) == "llava"
    assert vq.parse_reply('{"caption": "A cat", "text": ""}') == ("A cat", "")
    assert vq.parse_reply("A dog on a sofa") == ("A dog on a sofa", "")
