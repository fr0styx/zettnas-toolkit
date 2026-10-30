"""NREL-16: a Recycle Bin on a sleeping disk is neither read nor emptied."""

import os
import time

from backend.services import recycle_bin


def _bin_with_old_item(tmp_path):
    share = tmp_path / "share"
    (share / "doc.txt").parent.mkdir(parents=True)
    (share / "doc.txt").write_text("x")
    b = str(share / recycle_bin.BIN)
    name = recycle_bin.move_to_bin(str(share / "doc.txt"), recycle_dir=b)
    return b, name


def test_auto_empty_skips_a_sleeping_bin(tmp_path, monkeypatch):
    b, name = _bin_with_old_item(tmp_path)
    later = time.time() + 40 * 86400
    monkeypatch.setattr(recycle_bin, "asleep", lambda d: True)
    monkeypatch.setattr(recycle_bin, "items", lambda d: (_ for _ in ()).throw(AssertionError("read")))
    assert recycle_bin.auto_empty(b, now=later) == 0
    monkeypatch.undo()
    monkeypatch.setattr(recycle_bin, "asleep", lambda d: False)
    assert recycle_bin.auto_empty(b, now=later) == 1
    assert not os.path.lexists(os.path.join(b, "files", name))


def test_force_still_empties(tmp_path, monkeypatch):
    b, _name = _bin_with_old_item(tmp_path)
    monkeypatch.setattr(recycle_bin, "asleep", lambda d: True)
    assert recycle_bin.auto_empty(b, now=time.time() + 40 * 86400, force=True) == 1


def test_asleep_asks_about_the_share(monkeypatch):
    seen = []
    monkeypatch.setattr("backend.services.rag_standby.is_backing_disk_in_standby", lambda p: seen.append(p) or True)
    assert recycle_bin.asleep("/mnt/user/photos/.RecycleBin") is True
    assert seen == ["/mnt/user/photos"]

    def broken(p):
        raise OSError("no")

    monkeypatch.setattr("backend.services.rag_standby.is_backing_disk_in_standby", broken)
    assert recycle_bin.asleep("/mnt/user/photos/.RecycleBin") is False


def test_listing_names_sleeping_bins(monkeypatch):
    from backend.api.files import trash

    monkeypatch.setattr(recycle_bin, "all_bins", lambda: ["/mnt/user/a/.RecycleBin"])
    monkeypatch.setattr(recycle_bin, "asleep", lambda b: True)
    monkeypatch.setattr(recycle_bin, "known_items", lambda b: 4)
    monkeypatch.setattr(recycle_bin, "items", lambda b: (_ for _ in ()).throw(AssertionError("read")))
    out = trash._listing(object())
    assert out["items"] == [] and out["asleep"] == [{"root_path": "/mnt/user/a", "items": 4}]


def test_bin_view_counts_them(monkeypatch):
    from backend.api.files import browse, trash

    monkeypatch.setattr(trash, "bin_listing", lambda p: {"items": [], "asleep": [{"root_path": "/x", "items": 1}]})
    out = browse._bin_view("/mnt/user/.RecycleBin", object())
    assert out["recycle_bin"] is True and out["bins_asleep"] == 1


def test_known_items_reads_the_index(monkeypatch):
    monkeypatch.setattr(recycle_bin, "_index", lambda: {"bins": {"/b": {"items": 3}}})
    assert recycle_bin.known_items("/b") == 3 and recycle_bin.known_items("/c") == 0
