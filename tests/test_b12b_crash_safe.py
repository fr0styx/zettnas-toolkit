"""B12b (REL-14): copies and moves can't lose files. A move to another disk flushes the copy before
deleting the original; replacing a folder builds the new one beside it and swaps it in; what an
overwrite replaces goes to the Recycle Bin. The kill-point tests stop a run at every file operation
in turn and check that every version of every file still exists somewhere."""

import errno
import os
import shutil
from types import SimpleNamespace

import pytest

from backend import config
from backend.services import fs_transfer as ft
from backend.services import recycle_bin, snapshot_service

NEW = {"album/a.jpg": "new a", "album/sub/b.jpg": "new b", "album/c.jpg": "new c"}
OLD = {"album/a.jpg": "old a", "album/old-only.jpg": "old only"}


class Crash(BaseException):
    """A power cut: not an Exception, so nothing on the way catches it as an error."""


@pytest.fixture
def root(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    pool.mkdir()
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    return pool


def _tree(base, files):
    for rel, text in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _contents(base):
    found = set()
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            if not name.endswith(".trashinfo"):
                with open(os.path.join(dirpath, name)) as f:
                    found.add(f.read())
    return found


def _faults(m, other_disk, within, kill_at=None, log=None):
    """Makes `other_disk` another filesystem (renames out of it fail with EXDEV) and, with kill_at,
    stops the run at that file operation. Only operations on paths under `within` count."""
    calls = [0]

    def wrap(name, fn):
        def run(*args, **kwargs):
            first = str(args[0]) if args else ""
            counted = name == "fsync" or first.startswith(within)
            if counted:
                calls[0] += 1
                if log is not None:
                    log.append((name, first))
                if calls[0] == kill_at:
                    raise Crash(f"{name} {first}")
            if (
                name in ("rename", "replace")
                and first.startswith(other_disk)
                and not str(args[1]).startswith(other_disk)
            ):
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return fn(*args, **kwargs)

        return run

    for name in ("rename", "replace", "unlink", "rmdir", "fsync"):
        m.setattr(os, name, wrap(name, getattr(os, name)))
    m.setattr(shutil, "rmtree", wrap("rmtree", shutil.rmtree))
    return calls


@pytest.mark.parametrize("action", ["copy", "move"])
def test_a_crash_at_any_step_of_a_folder_overwrite_loses_nothing(root, tmp_path, monkeypatch, action):
    usb = tmp_path / "usb"  # another disk
    every = set(NEW.values()) | set(OLD.values())
    for kill_at in range(1, 300):
        for d in (usb, root / "photos", root / ".RecycleBin"):
            shutil.rmtree(d, ignore_errors=True)
        _tree(usb, NEW)
        _tree(root / "photos", OLD)
        with monkeypatch.context() as m:
            _faults(m, str(usb), str(tmp_path), kill_at=kill_at)
            try:
                res = ft.execute_transfer([str(usb / "album")], str(root / "photos"), action=action, policy="overwrite")
            except Crash:
                res = None
        assert every <= _contents(usb) | _contents(root), f"a crash at step {kill_at} lost a file"
        if res is not None:  # finished before step kill_at: every step has been tried
            break
    else:
        pytest.fail("the overwrite never finished")
    assert res["status"] == "ok" and kill_at > 5
    assert _contents(root / "photos" / "album") == set(NEW.values())
    assert {"old a", "old only"} <= _contents(root / ".RecycleBin")
    assert (action == "move") != (usb / "album").exists()
    assert not [p for p in os.listdir(root / "photos") if p.startswith(".")]  # no stage left behind


@pytest.mark.parametrize("action", ["copy", "move"])
def test_a_crash_at_any_step_of_a_file_overwrite_loses_nothing(root, tmp_path, monkeypatch, action):
    usb = tmp_path / "usb"
    for kill_at in range(1, 100):
        for d in (usb, root / "docs", root / ".RecycleBin"):
            shutil.rmtree(d, ignore_errors=True)
        _tree(usb, {"a.txt": "new"})
        _tree(root / "docs", {"a.txt": "old"})
        with monkeypatch.context() as m:
            _faults(m, str(usb), str(tmp_path), kill_at=kill_at)
            try:
                res = ft.execute_transfer([str(usb / "a.txt")], str(root / "docs"), action=action, policy="overwrite")
            except Crash:
                res = None
        assert {"new", "old"} <= _contents(usb) | _contents(root), f"a crash at step {kill_at} lost a file"
        if res is not None:
            break
    assert (root / "docs" / "a.txt").read_text() == "new" and "old" in _contents(root / ".RecycleBin")


def test_a_move_to_another_disk_flushes_the_copy_before_deleting_the_original(root, tmp_path, monkeypatch):
    usb = tmp_path / "usb"
    _tree(usb, {"a.txt": "data"})
    log = []
    with monkeypatch.context() as m:
        _faults(m, str(usb), str(tmp_path), log=log)
        ft.execute_transfer([str(usb / "a.txt")], str(root), action="move")
    names = [n for n, _ in log]
    assert names.index("fsync") < log.index(("unlink", str(usb / "a.txt")))
    assert (root / "a.txt").read_text() == "data" and not (usb / "a.txt").exists()


def test_a_failed_flush_keeps_the_original(root, tmp_path, monkeypatch):
    usb = tmp_path / "usb"
    _tree(usb, {"a.txt": "data"})

    def broken(fd):
        raise OSError(errno.EIO, "I/O error")

    with monkeypatch.context() as m:
        _faults(m, str(usb), str(tmp_path))
        m.setattr(os, "fsync", broken)
        res = ft.execute_transfer([str(usb / "a.txt")], str(root), action="move")
    assert res["status"] == "partial" and (usb / "a.txt").read_text() == "data"
    assert not (root / "a.txt").exists() and os.listdir(root) == []


def test_mounts_without_fsync_still_move(root, tmp_path, monkeypatch):
    usb = tmp_path / "usb"
    _tree(usb, {"a.txt": "data"})

    def unsupported(fd):
        raise OSError(errno.EINVAL, "Invalid argument")

    with monkeypatch.context() as m:
        _faults(m, str(usb), str(tmp_path))
        m.setattr(os, "fsync", unsupported)
        assert ft.execute_transfer([str(usb / "a.txt")], str(root), action="move")["status"] == "ok"
    assert (root / "a.txt").read_text() == "data"


def test_a_replaced_file_goes_to_the_recycle_bin_with_where_it_was(root):
    _tree(root, {"src/a.txt": "new", "docs/a.txt": "old"})
    ft.execute_transfer([str(root / "src" / "a.txt")], str(root / "docs"), action="copy", policy="overwrite")
    assert (root / "docs" / "a.txt").read_text() == "new"
    [info] = os.listdir(root / ".RecycleBin" / "info")
    assert f"Path={root / 'docs' / 'a.txt'}" in (root / ".RecycleBin" / "info" / info).read_text()


def test_a_same_disk_folder_move_swaps_in_one_rename(root):
    _tree(root, {"in/album/a.jpg": "new", "photos/album/a.jpg": "old"})
    res = ft.execute_transfer([str(root / "in" / "album")], str(root / "photos"), action="move", policy="overwrite")
    assert res["transferred"] == 1 and (root / "photos" / "album" / "a.jpg").read_text() == "new"
    assert "old" in _contents(root / ".RecycleBin") and not (root / "in" / "album").exists()


def test_a_folder_that_cannot_be_moved_away_is_left_as_it_was(root, monkeypatch):
    _tree(root, {"in/album/a.jpg": "new", "photos/album/a.jpg": "old"})

    def stuck(path, delete=True):
        raise OSError(errno.EBUSY, "busy")

    monkeypatch.setattr(ft, "_set_aside", stuck)
    res = ft.execute_transfer([str(root / "in" / "album")], str(root / "photos"), action="move", policy="overwrite")
    assert res["status"] == "partial"
    assert (root / "in" / "album" / "a.jpg").read_text() == "new"
    assert (root / "photos" / "album" / "a.jpg").read_text() == "old"


def test_without_a_recycle_bin_an_overwrite_replaces_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path / "elsewhere")])
    _tree(tmp_path, {"src/album/a.jpg": "new", "dst/album/a.jpg": "old", "src/b.txt": "new b", "dst/b.txt": "old b"})
    ft.execute_transfer([str(tmp_path / "src" / "album")], str(tmp_path / "dst"), policy="overwrite")
    ft.execute_transfer([str(tmp_path / "src" / "b.txt")], str(tmp_path / "dst"), policy="overwrite")
    assert _contents(tmp_path / "dst") == {"new", "new b"} and not (tmp_path / ".RecycleBin").exists()


def test_the_recycle_bin_knows_where_it_is(root, tmp_path):
    assert recycle_bin.bin_for(str(root / "a" / "b.txt")) == str(root / ".RecycleBin")
    assert recycle_bin.bin_for(str(root / ".RecycleBin" / "files" / "x")) is None
    assert recycle_bin.bin_for(str(tmp_path / "outside")) is None
    assert recycle_bin.move_to_bin(str(tmp_path / "outside")) is None
    _tree(root, {"a.txt": "1", "b/a.txt": "2"})
    first = recycle_bin.move_to_bin(str(root / "a.txt"))
    second = recycle_bin.move_to_bin(str(root / "b" / "a.txt"))
    assert first != second and first.endswith("_a.txt") and second.endswith("_a.txt")


def test_a_bin_on_another_filesystem_is_not_copied_into(root, monkeypatch):
    _tree(root, {"a.txt": "data"})

    def exdev(a, b):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "rename", exdev)
    assert recycle_bin.move_to_bin(str(root / "a.txt"), rename_only=True) is None
    monkeypatch.undo()
    assert (root / "a.txt").exists() and os.listdir(root / ".RecycleBin" / "info") == []


def test_a_folder_flush_that_cannot_open_is_skipped(tmp_path):
    ft._fsync_dir(str(tmp_path / "missing"))  # logs and goes on


class _Pal:
    def __init__(self, snapdir, live, pool):
        self.snapdir, self.live, self.pool = snapdir, live, pool

    def list_snapshots(self, pool_id):
        return [{"name": "photos@auto-1", "path": str(self.snapdir)}]

    def list_shares(self):
        return [SimpleNamespace(name="photos", mountpoint=str(self.live))]

    def get_pool_path(self, pool_id):
        return str(self.pool)


def test_a_snapshot_restore_over_the_current_version_keeps_it_in_the_bin(root, tmp_path):
    _tree(tmp_path / "snap", {"album/a.jpg": "then", "notes.txt": "then"})
    _tree(root / "photos", {"album/a.jpg": "now", "album/extra.jpg": "now extra", "notes.txt": "now"})
    pal = _Pal(tmp_path / "snap", root / "photos", root)
    for rel in ("album", "notes.txt"):
        assert snapshot_service.restore("photos@auto-1", rel, overwrite=True, pal=pal, pool_id="tank")["overwrote"]
    assert _contents(root / "photos") == {"then"}
    assert {"now", "now extra"} <= _contents(root / ".RecycleBin")


def test_a_failed_folder_copy_leaves_the_current_version(root, tmp_path, monkeypatch):
    _tree(tmp_path / "snap", {"album/a.jpg": "then"})
    _tree(root / "photos", {"album/a.jpg": "now"})

    def boom(src, dst, symlinks=False):
        os.makedirs(dst)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(ft.shutil, "copytree", boom)
    with pytest.raises(OSError):
        ft.replace_with_copy(str(tmp_path / "snap" / "album"), str(root / "photos" / "album"))
    monkeypatch.undo()
    assert os.listdir(root / "photos") == ["album"] and (root / "photos" / "album" / "a.jpg").read_text() == "now"


def test_a_file_can_replace_a_folder(root, tmp_path):
    _tree(tmp_path / "snap", {"thing": "a file now"})
    _tree(root / "photos", {"thing/inside.txt": "was a folder"})
    ft.replace_with_copy(str(tmp_path / "snap" / "thing"), str(root / "photos" / "thing"))
    assert (root / "photos" / "thing").read_text() == "a file now"
    assert "was a folder" in _contents(root / ".RecycleBin")
