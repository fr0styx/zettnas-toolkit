"""NAI-11: black-and-white scans (fax, JBIG2 or 1-bit page images) are read by drawing each page."""

import contextlib
import io
import os

from PIL import Image, ImageDraw

from backend.services import rag_documents
from backend.services import vision_queue as vq
from backend.services.rag_engine import RagSearchEngine


def _bw_pdf(path, pages=1):
    """A 1-bit scan as a scanner writes it: no JPEG anywhere in the file."""
    ims = []
    for n in range(pages):
        im = Image.new("1", (1700, 2200), 1)
        ImageDraw.Draw(im).rectangle((200, 200 + n * 300, 1500, 400 + n * 300), fill=0)
        ims.append(im)
    ims[0].save(path, format="PDF", resolution=200, save_all=True, append_images=ims[1:])


def test_a_bw_scan_has_no_jpeg_but_its_pages_are_drawn(tmp_path):
    p = tmp_path / "scan.pdf"
    _bw_pdf(p)
    assert vq.extract_pdf_jpegs(str(p)) == []
    pages = vq.pdf_page_images(str(p))
    assert len(pages) == 1
    with Image.open(io.BytesIO(pages[0])) as im:
        assert im.format == "JPEG" and im.mode == "L"
        assert max(im.size) == vq.RENDER_LONG_SIDE
        assert im.getextrema()[0] < 50  # the black bar is on the page


def test_pages_stop_at_the_cap(tmp_path):
    p = tmp_path / "long.pdf"
    _bw_pdf(p, pages=3)
    assert len(vq.render_pdf_pages(str(p), max_pages=2)) == 2


def test_a_file_pdfium_cannot_open_falls_back_to_its_jpegs(tmp_path, monkeypatch):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"not a pdf")
    assert vq.render_pdf_pages(str(p)) == []
    monkeypatch.setattr(vq, "render_pdf_pages", lambda path: [])
    monkeypatch.setattr(vq, "extract_pdf_jpegs", lambda path: [b"jpeg"])
    assert vq.pdf_page_images(str(p)) == [b"jpeg"]


def test_text_reading_and_drawing_share_one_pdfium_lock(tmp_path, monkeypatch):
    held = []

    @contextlib.contextmanager
    def lock():
        held.append(True)
        yield

    monkeypatch.setattr(rag_documents, "PDFIUM_LOCK", lock())
    p = tmp_path / "scan.pdf"
    _bw_pdf(p)
    assert rag_documents.pdf_text(str(p)) == ""
    monkeypatch.setattr(rag_documents, "PDFIUM_LOCK", lock())
    assert len(vq.render_pdf_pages(str(p))) == 1
    assert held == [True, True]


def test_a_scan_skipped_before_is_read_now(tmp_path, monkeypatch):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    cfg = dict(engine.get_config())
    cfg.update({"respect_standby": False, "vision_captions": "auto"})
    monkeypatch.setattr(engine, "get_config", lambda: cfg)
    pdf = tmp_path / "Mietvertrag.pdf"
    _bw_pdf(pdf, pages=2)
    st = os.stat(pdf)
    engine._index_single_file(
        str(pdf), pdf.name, ".pdf", st.st_size, st.st_mtime_ns, None, respect_standby=False, force_wake=True
    )
    q = vq.VisionQueue(engine, idle=lambda: True, host=lambda: "http://ollama", model_picker=lambda c, h: "gemma3:4b")
    conn = q._conn()
    try:  # what the queue wrote for this file before pages were drawn
        conn.execute(
            "INSERT INTO pdf_ocr (path, mtime_ns, pages, text, status, updated_at) VALUES (?, ?, 0, '', 'no-images', 0)",
            (str(pdf), st.st_mtime_ns),
        )
        conn.commit()
    finally:
        conn.close()
    calls = []
    q.ocr = lambda data, model, host: calls.append(len(data)) or "MIETVERTRAG Wohnung 3. OG Kaltmiete 840 EUR"
    assert q.process_one() == "done" and len(calls) == 2
    assert q.process_one() == "empty"  # read once per file version
    conn = engine._get_conn()
    try:
        text = " ".join(r[0] for r in conn.execute("SELECT chunk_text FROM document_chunks"))
        status = conn.execute("SELECT status, pages FROM pdf_ocr").fetchall()
    finally:
        conn.close()
    assert "Kaltmiete" in text
    assert [tuple(r) for r in status] == [("done", 2)]


def test_a_file_with_no_pages_is_not_tried_again(tmp_path, monkeypatch):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    cfg = dict(engine.get_config())
    cfg.update({"respect_standby": False, "vision_captions": "auto"})
    monkeypatch.setattr(engine, "get_config", lambda: cfg)
    pdf = tmp_path / "empty.pdf"
    _bw_pdf(pdf)
    st = os.stat(pdf)
    engine._index_single_file(
        str(pdf), pdf.name, ".pdf", st.st_size, st.st_mtime_ns, None, respect_standby=False, force_wake=True
    )
    monkeypatch.setattr(vq, "pdf_page_images", lambda path: [])
    q = vq.VisionQueue(engine, idle=lambda: True, host=lambda: "http://ollama", model_picker=lambda c, h: "gemma3:4b")
    assert q.process_one() == "empty"
    assert q.process_one() == "empty"
    conn = engine._get_conn()
    try:
        assert [tuple(r) for r in conn.execute("SELECT status, pages FROM pdf_ocr")] == [("no-pages", 0)]
    finally:
        conn.close()
