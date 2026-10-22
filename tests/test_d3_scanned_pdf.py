"""D3: scanned PDFs (page images, no text layer) become searchable through the vision queue."""

import io
import os

from PIL import Image

from backend.services import vision_queue as vq
from backend.services.rag_engine import RagSearchEngine


def _scanned_pdf(path):
    buf = io.BytesIO()
    Image.effect_noise((900, 1200), 80).convert("RGB").save(buf, format="JPEG", quality=90)
    jpg = buf.getvalue()
    head = (
        f"<< /Type /XObject /Subtype /Image /Width 900 /Height 1200 /ColorSpace /DeviceRGB "
        f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpg)} >>"
    ).encode()
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4\n1 0 obj\n" + head + b"\nstream\n" + jpg + b"\nendstream\nendobj\ntrailer << >>\n%%EOF\n")
    return jpg


def test_page_images_are_found(tmp_path):
    p = tmp_path / "scan.pdf"
    jpg = _scanned_pdf(p)
    assert vq.extract_pdf_jpegs(str(p)) == [jpg]


def test_scanned_pdf_text_reaches_the_index(tmp_path, monkeypatch):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    cfg = dict(engine.get_config())
    cfg.update({"respect_standby": False, "vision_captions": "auto"})
    monkeypatch.setattr(engine, "get_config", lambda: cfg)
    pdf = tmp_path / "Rechnung.pdf"
    _scanned_pdf(pdf)
    st = os.stat(pdf)
    engine._index_single_file(
        str(pdf), pdf.name, ".pdf", st.st_size, st.st_mtime_ns, None, respect_standby=False, force_wake=True
    )
    q = vq.VisionQueue(engine, idle=lambda: True, host=lambda: "http://ollama", model_picker=lambda c, h: "gemma3:4b")
    calls = []
    q.ocr = lambda data, model, host: calls.append(len(data)) or "RECHNUNG Nr. 4711\nBaumarkt Schmidt\nSumme 12,99 EUR"
    assert q.process_one() == "done" and len(calls) == 1
    assert q.process_one() == "empty"  # done once per file version
    conn = engine._get_conn()
    try:
        text = " ".join(r[0] for r in conn.execute("SELECT chunk_text FROM document_chunks"))
    finally:
        conn.close()
    assert "4711" in text and "Baumarkt" in text
