"""AI-22 end to end: a PDF, a Word file and a photo are indexed for real, and a question about each
one, in focus, hands the model that file's own text with a source for it, in any language.

Everything runs as in the app (the index, the extractors, the photo analyzer and the chat tool that
builds the model's context); only the engine's location is a temporary folder.
"""

import os
import shutil
import zipfile

import pytest
from PIL import Image

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(path, paragraphs):
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        z.writestr(
            "word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
        )


def _photo(path, description):
    exif = Image.Exif()
    exif[0x010E] = description  # ImageDescription, which the photo analyzer reads as the photo's text
    Image.new("RGB", (320, 240), (200, 160, 90)).save(path, exif=exif)


@pytest.fixture()
def indexed(tmp_path, monkeypatch):
    from backend.services import chat_nas_tools, rag_engine

    monkeypatch.setattr(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = rag_engine.RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    cfg = dict(eng.get_config(), embedding_model="zett_lexical_384d", respect_standby=False)
    monkeypatch.setattr(eng, "get_config", lambda: cfg)
    root = tmp_path / "pool"
    root.mkdir()
    pdf = root / "kuendigung.pdf"
    shutil.copy(os.path.join(FIXTURES, "de-macos.pdf"), pdf)
    lease = root / "lease.docx"
    _docx(lease, ["Tenancy agreement", "The landlord is Ms Rossi.", "Rent is due on the first of the month."])
    receipt = root / "receipt.jpg"
    _photo(receipt, "Receipt from the corner bakery: three croissants and a rye loaf")
    for f in (pdf, lease, receipt):
        eng._index_single_file(
            str(f), f.name, f.suffix, f.stat().st_size, 1, None, respect_standby=False, force_wake=True
        )
    monkeypatch.setattr(chat_nas_tools, "_core", lambda: type("C", (), {"get_rag_engine": staticmethod(lambda: eng)}))
    try:
        yield {"pdf": str(pdf), "docx": str(lease), "photo": str(receipt)}
    finally:
        eng.close()


def _ask(path, question):
    from backend.services import chat_nas_tools

    token = chat_nas_tools.FOCUS_PATH.set(path)
    try:
        return chat_nas_tools.tool_search_nas_knowledge(question)
    finally:
        chat_nas_tools.FOCUS_PATH.reset(token)


@pytest.mark.parametrize(
    "kind, words",
    [
        ("pdf", ["Kündigungsbestätigung", "Rückzahlung"]),
        ("docx", ["Ms Rossi", "first of the month"]),
        ("photo", ["bakery", "croissants"]),
    ],
)
@pytest.mark.parametrize("question", ["What is in this file?", "Was steht drin?", "这个文件里有什么？"])
def test_a_question_about_a_file_in_focus_gets_that_files_text(indexed, kind, words, question):
    out = _ask(indexed[kind], question)
    text = str(out)
    for w in words:
        assert w in text, (kind, question, w)
    assert out["citations_count"] >= 1
    assert all(c.get("path") == indexed[kind] for c in out.get("citations", []) if c.get("path"))
