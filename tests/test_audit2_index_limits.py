"""Reading a document's text has a memory ceiling (audit pass 2)."""

import tracemalloc
import zipfile
import zlib


def _peak_mb(fn):
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    finally:
        tracemalloc.stop()


def test_docx_with_a_huge_inner_document_is_skipped(tmp_path, monkeypatch):
    from backend.services import rag_documents

    monkeypatch.setattr(rag_documents, "MAX_EXPANDED_BYTES", 4 * 1024 * 1024)
    f = tmp_path / "big.docx"
    with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"<w:document><w:body>" + b" " * (32 * 1024 * 1024) + b"</w:body></w:document>")
    assert _peak_mb(lambda: rag_documents.extract_document_text(str(f), ".docx")) < 16


def test_pdf_streams_share_one_expansion_budget(tmp_path, monkeypatch):
    from backend.services import rag_documents

    monkeypatch.setattr(rag_documents, "MAX_EXPANDED_BYTES", 4 * 1024 * 1024)
    stream = zlib.compress(b" " * (32 * 1024 * 1024), 9)
    f = tmp_path / "big.pdf"
    f.write_bytes(b"%PDF-1.4\n1 0 obj<<>>stream\n" + stream + b"\nendstream\n%%EOF")
    assert _peak_mb(lambda: rag_documents.extract_document_text(str(f), ".pdf")) < 24


def test_normal_documents_still_read(tmp_path):
    from backend.services import rag_documents

    f = tmp_path / "ok.docx"
    with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Hello index</w:t></w:r></w:p></w:body></w:document>',
        )
    assert "Hello index" in rag_documents.extract_document_text(str(f), ".docx")
