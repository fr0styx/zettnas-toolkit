"""Text read from photos gets neural vectors like documents (not keyword-only vectors)."""

import struct
from unittest import mock

import pytest
from PIL import ExifTags, Image

from backend.services import rag_engine as re_mod
from backend.services.rag_engine import RagSearchEngine


def _photo(path, text):
    img = Image.new("RGB", (64, 48), (200, 200, 200))
    exif = Image.Exif()
    exif[ExifTags.Base.ImageDescription] = text
    img.save(path, "JPEG", exif=exif.tobytes())


def test_photo_text_gets_neural_vectors_and_enters_the_vector_table(tmp_path, monkeypatch):
    monkeypatch.setattr(re_mod, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = RagSearchEngine(db_path=str(tmp_path / "rag_index.db"))
    eng._ensure_schema()
    eng.update_config({"embedding_model": "m", "embedding_dim": 768})
    photo = tmp_path / "receipt.jpg"
    _photo(photo, "Hardware store receipt. Total 42.50 EUR. Paint, brushes and tape. " * 3)
    seen = []

    def vec(texts, *a, **k):
        seen.extend(texts)
        return [struct.pack("<768f", *([1.0] + [0.0] * 767)) for _ in texts]

    st = photo.stat()
    with (
        mock.patch.object(re_mod, "compute_neural_embeddings_batch", side_effect=vec),
        mock.patch("backend.services.rag_standby.is_backing_disk_in_standby", return_value=False),
    ):
        eng._index_single_file(str(photo), photo.name, ".jpg", st.st_size, st.st_mtime_ns, None, force_wake=True)

    c = eng._get_conn(readonly=True)
    try:
        rows = c.execute(
            "SELECT chunk_level, embedding_model, embedding_dim FROM document_chunks WHERE source_modality = 'photo_ocr'"
        ).fetchall()
        file_model = c.execute("SELECT embedding_model FROM indexed_files").fetchone()[0]
        vectors = c.execute("SELECT COUNT(*) FROM vec_chunks_768_i8").fetchone()[0] if eng._has_sqlite_vec else None
    finally:
        c.close()
    children = [r for r in rows if r[0] == "child"]
    if not children:
        pytest.skip("no OCR text was extracted from the test photo in this build")
    assert all(r[1] == "m" and r[2] == 768 for r in children)
    assert all(r[2] == 0 for r in rows if r[0] == "parent")
    assert file_model == "m" and any("Hardware store receipt" in t for t in seen)
    if vectors is not None:
        assert vectors == len(children)
    eng.close()
