"""Binary data is never indexed or embedded as text."""

import os
import zlib

from backend.services.rag_documents import extract_document_text
from backend.services.rag_text import binary_ratio, looks_like_binary


def test_real_text_in_any_language_is_text():
    for t in [
        "Résumé: la cigüeña voló sobre el río. Überprüfung der Größe.\n\tNext line",
        "這是一個測試文件，包含中文字符。日本語のテキストも。",
        "1\n00:00:01,000 --> 00:00:03,500\nWhere are you going?\n",
        "",
    ]:
        assert not looks_like_binary(t), t


def test_binary_read_as_text_is_caught():
    blob = os.urandom(4000)
    assert looks_like_binary(blob.decode("latin-1"))
    assert looks_like_binary(blob.decode("utf-8", errors="replace"))
    assert binary_ratio(blob.decode("latin-1")) > 0.15


def test_vobsub_style_sub_file_gives_no_text(tmp_path):
    p = tmp_path / "movie.sub"
    p.write_bytes(b"\x00\x00\x01\xba" + os.urandom(20000))
    assert extract_document_text(str(p), ".sub") == ""
    text_sub = tmp_path / "movie2.sub"
    text_sub.write_text("{1}{50}Hello there|second line\n{60}{90}Bye\n", encoding="utf-8")
    assert "Hello there" in extract_document_text(str(text_sub), ".sub")


def test_pdf_fallback_keeps_text_and_drops_binary_strings(tmp_path, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "pypdf", None)  # force the built-in stream parser
    junk = bytes(b for b in os.urandom(3000) if b not in b"()\\")
    page = b"BT (Hello world from the manual) Tj ET (" + junk[:200] + b") Tj"
    font = b"(" + junk[200:400] + b")"
    pdf = b"%PDF-1.4\n"
    for body in (page, font):
        pdf += b"1 0 obj\n<< /Filter /FlateDecode >>\nstream\n" + zlib.compress(body) + b"\nendstream\nendobj\n"
    p = tmp_path / "doc.pdf"
    p.write_bytes(pdf)
    text = extract_document_text(str(p), ".pdf")
    assert "Hello world from the manual" in text
    assert not looks_like_binary(text) and binary_ratio(text) < 0.01


def test_subtitles_are_embedded_without_cue_numbers_and_timings():
    from backend.services.rag_text import text_for_embedding

    srt = "[Folder: Season 4 | Doc: 00:00:00,665 --> 00:00:02,350]\n741\n00:45:25,808 --> 00:45:29,478\nBajar a la Zona Cero,\nfuneral por la tarde.\n\n742\n00:45:29,562 --> 00:45:32,150 X1:0\nY luego 3 cervezas."
    out = text_for_embedding(".srt", srt)
    assert "-->" not in out and "741" not in out and "00:45" not in out
    assert "Bajar a la Zona Cero" in out and "3 cervezas" in out and "Season 4" in out
    assert text_for_embedding(".sub", "{1}{50}Hello|there\n{60}{90}Bye") == "Hello|there\n Bye"
    plain = "Invoice 741\n00:45 meeting"
    assert text_for_embedding(".txt", plain) == plain
