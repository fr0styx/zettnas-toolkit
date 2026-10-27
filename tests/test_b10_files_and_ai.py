"""B10 / PERF-17, PERF-18, AI-21, AI-22."""

import io
import os
import zipfile
from unittest.mock import patch

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")


# ---- PERF-17: the Explorer zip streams while it is built, with nothing staged on disk
def test_the_zip_download_streams_without_a_temp_file(client, auth_headers, tmp_path, monkeypatch):
    import tempfile

    root = tmp_path / "pool"
    folder = root / "holiday"
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("sunny " * 1000)
    (folder / "photo.jpg").write_bytes(os.urandom(300_000))
    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", lambda *a, **k: pytest.fail("staged on disk"))
    with (
        patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)]),
        patch("backend.api.files.preview.ALLOWED_BROWSE_ROOTS", [str(root)]),
    ):
        res = client.get(f"/api/fs/download-zip?paths={folder}", headers=auth_headers)
    assert res.status_code == 200, res.text
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        info = {i.filename: i for i in z.infolist()}
        assert info["holiday/photo.jpg"].compress_type == zipfile.ZIP_STORED  # media is not re-compressed
        assert info["holiday/notes.txt"].compress_type == zipfile.ZIP_DEFLATED
        assert z.read("holiday/notes.txt").decode().startswith("sunny")


def test_zip_downloads_share_the_two_slots(client, auth_headers, tmp_path, monkeypatch):
    from backend.api.files import share_links

    monkeypatch.setattr(share_links, "_share_zip_slot", lambda: None)
    root = tmp_path / "pool"
    (root / "a").mkdir(parents=True)
    with (
        patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)]),
        patch("backend.api.files.preview.ALLOWED_BROWSE_ROOTS", [str(root)]),
    ):
        res = client.get(f"/api/fs/download-zip?paths={root / 'a'}", headers=auth_headers)
    assert res.status_code == 429


# ---- PERF-18: only the card reader is probed
def _usb_disk(sysfs, name, vid, pid):
    dev = sysfs / "devices" / "pci0" / "usb1" / f"1-{name}"
    (dev / "host0" / "target0:0:0" / "0:0:0:0" / "block" / name).mkdir(parents=True)
    (dev / "idVendor").write_text(vid + "\n")
    (dev / "idProduct").write_text(pid + "\n")
    (sysfs / "block").mkdir(exist_ok=True)
    os.symlink(dev / "host0" / "target0:0:0" / "0:0:0:0" / "block" / name, sysfs / "block" / name)


def test_other_usb_disks_are_never_probed(tmp_path, monkeypatch):
    from backend.services import copy_engine

    _usb_disk(tmp_path, "sdc", "0781", "5583")  # a USB stick (e.g. a boot flash)
    _usb_disk(tmp_path, "sdd", "05e3", "0764")  # the appliance's card reader
    copy_engine._READER_CACHE.clear()
    assert copy_engine.is_card_reader(str(tmp_path / "block" / "sdd")) is True
    assert copy_engine.is_card_reader(str(tmp_path / "block" / "sdc")) is False
    probed = []
    monkeypatch.setattr(copy_engine, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(copy_engine, "probe_media_slot_capacity", lambda dev, **k: probed.append(dev) or 0)
    monkeypatch.setattr(copy_engine, "_ensure_slot_polling", lambda *a: None)
    copy_engine.read_media_slots()
    assert probed == ["sdd"]


# ---- AI-21: real PDFs from real writers come out as text
@pytest.mark.parametrize(
    "name, words",
    [("de-macos.pdf", ["Kündigungsbestätigung", "Rückzahlung", "fällig"]), ("zh-macos.pdf", ["保险单号", "理赔"])],
)
def test_pdfs_written_by_macos_index_real_text(name, words):
    from backend.services.rag_documents import extract_document_text

    text = extract_document_text(os.path.join(FIXTURES, name), ".pdf")
    for w in words:
        assert w in text, (name, w, text[:200])


# ---- AI-22: "what's in this file?" is answered from the file
def test_a_question_about_one_file_reads_that_file(monkeypatch):
    from backend.services import chat_nas_tools

    class Rag:
        asked = []

        def file_chunks(self, path, max_chars=16000):
            return {
                "found": True,
                "file_id": 7,
                "name": "lease.pdf",
                "title": "Lease",
                "doc_type": "document",
                "complete": True,
                "chunks": [
                    {"chunk_id": 1, "text": "The landlord is Ms Rossi.", "heading": "", "line_start": 1, "line_end": 1}
                ],
            }

        def get_config(self):
            return {}

        def aggregate_folder_context(self, **kw):
            raise AssertionError("a single file has no folder manifest")

        def ask(self, **kw):
            self.asked.append(kw)
            return {"results": [], "answer": ""}

    rag = Rag()
    monkeypatch.setattr(chat_nas_tools, "_core", lambda: type("C", (), {"get_rag_engine": staticmethod(lambda: rag)}))
    for q in ("what is in it?", "Was steht drin?", "这个文件里有什么？"):
        token = chat_nas_tools.FOCUS_PATH.set("/mnt/user/docs/lease.pdf")
        try:
            out = chat_nas_tools.tool_search_nas_knowledge(q)
        finally:
            chat_nas_tools.FOCUS_PATH.reset(token)
        assert out["citations_count"] >= 1, (q, out)
        assert "Rossi" in str(out)
    assert rag.asked == []


def test_the_engine_hands_back_one_files_text_in_order(tmp_path, monkeypatch):
    from backend.services import rag_engine

    monkeypatch.setattr(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = rag_engine.RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    root = tmp_path / "docs"
    root.mkdir()
    lease = root / "lease.txt"
    lease.write_text("Tenancy agreement.\nThe landlord is Ms Rossi.\nRent is due on the first of the month.\n")
    big = root / "big.txt"
    big.write_text("\n".join(f"Line {i} of a very long manual." for i in range(4000)))
    try:
        cfg = dict(eng.get_config(), embedding_model="zett_lexical_384d", respect_standby=False)
        monkeypatch.setattr(eng, "get_config", lambda: cfg)
        for f in (lease, big):
            eng._index_single_file(
                str(f), f.name, ".txt", f.stat().st_size, 1, None, respect_standby=False, force_wake=True
            )
        got = eng.file_chunks(str(lease))
        assert got["found"] and got["complete"] and "Rossi" in " ".join(c["text"] for c in got["chunks"])
        long = eng.file_chunks(str(big), max_chars=2000)
        assert long["found"] and not long["complete"] and sum(len(c["text"]) for c in long["chunks"]) <= 2000
        assert eng.file_chunks(str(root)) == {"found": False}  # a folder is not a file
    finally:
        eng.close()


def test_a_single_file_zip_and_links_outside_are_skipped(client, auth_headers, tmp_path):
    root = tmp_path / "pool"
    (root / "a").mkdir(parents=True)
    (root / "a" / "note.txt").write_text("hello")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    os.symlink(outside, root / "a" / "link.txt")
    with (
        patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)]),
        patch("backend.api.files.preview.ALLOWED_BROWSE_ROOTS", [str(root)]),
    ):
        one = client.get(f"/api/fs/download-zip?paths={root / 'a' / 'note.txt'}", headers=auth_headers)
        folder = client.get(f"/api/fs/download-zip?paths={root / 'a'}", headers=auth_headers)
    with zipfile.ZipFile(io.BytesIO(one.content)) as z:
        assert z.namelist() == ["note.txt"]
    with zipfile.ZipFile(io.BytesIO(folder.content)) as z:
        assert "a/link.txt" not in z.namelist() and "a/note.txt" in z.namelist()
