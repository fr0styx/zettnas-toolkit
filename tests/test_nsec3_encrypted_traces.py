"""NSEC-3: an encrypted folder's pictures and file names stay inside it."""

import os

from backend.services import file_activity, thumbs


def test_thumbnails_inside_are_not_cached(monkeypatch):
    rendered, stored = [], []
    monkeypatch.setattr(thumbs, "render", lambda p, limit: rendered.append(p) or b"webp")
    monkeypatch.setattr(thumbs, "_store", lambda target, data: stored.append(target))
    monkeypatch.setattr(os.path, "realpath", lambda p: p)
    assert thumbs.get("/mnt/encrypted/Taxes/scan.jpg", 256) == b"webp"
    assert rendered == ["/mnt/encrypted/Taxes/scan.jpg"] and stored == []


def test_the_activity_log_keeps_only_the_folder():
    p, t, d = file_activity._outside_encryption("/mnt/encrypted/Taxes/2021/return.pdf", "", "")
    assert p == "/mnt/encrypted/Taxes" and d == "inside an encrypted folder"
    p, t, d = file_activity._outside_encryption("/mnt/user/Family/a.txt", "/mnt/encrypted/Taxes/b.txt", "moved")
    assert p == "/mnt/user/Family/a.txt" and t == "/mnt/encrypted/Taxes" and d == "inside an encrypted folder"
    assert file_activity._outside_encryption("/mnt/user/x", "/mnt/user/y", "renamed") == (
        "/mnt/user/x",
        "/mnt/user/y",
        "renamed",
    )


def test_the_index_never_walks_into_one():
    import inspect

    from backend.services import rag_engine_indexing

    assert rag_engine_indexing.in_encrypted("/mnt/encrypted/Taxes/a.pdf")
    assert not rag_engine_indexing.in_encrypted("/mnt/user/Family/a.pdf")
    assert "or in_encrypted(child_path)" in inspect.getsource(rag_engine_indexing)
