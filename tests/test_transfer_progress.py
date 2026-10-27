"""Background copy/move/merge: progress, pause/cancel and safety (backend/services/fs_transfer.py)."""

import os
import time
from unittest.mock import patch

import pytest

from backend.services import fs_transfer as ft


class Recorder(ft.TransferProgress):
    def __init__(self, cancel_after_bytes: int | None = None):
        self.bytes = 0
        self.files = 0
        self.cancel_after = cancel_after_bytes

    def checkpoint(self):
        if self.cancel_after is not None and self.bytes >= self.cancel_after:
            raise ft.TransferCancelled()

    def add_bytes(self, n):
        self.bytes += n

    def file_done(self):
        self.files += 1

    def done_totals(self, files, nbytes):
        self.files += files
        self.bytes += nbytes

    def skip_tree(self, path):
        self.done_totals(*ft.tree_totals(path))


def make_tree(root, files):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def no_part_files(root):
    return not [p for p in root.rglob("*") if p.name.endswith(".zettnas-part")]


def wait(task_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        info = ft.transfer_manager.get_task(task_id)
        if info and info["status"] in ("completed", "failed", "cancelled"):
            return info
        time.sleep(0.02)
    raise AssertionError("task did not finish")


def test_copy_reports_every_byte_and_file(tmp_path):
    src = tmp_path / "src" / "Album"
    make_tree(src, {"a.jpg": b"a" * 5000, "sub/b.jpg": b"b" * 3000, "sub/deeper/c.txt": b"c"})
    dst = tmp_path / "dst"
    dst.mkdir()
    rec = Recorder()
    res = ft.execute_transfer([str(src)], str(dst), "copy", "merge", progress=rec)
    assert res["errors"] == []
    assert rec.bytes == 8001 and rec.files == 3
    assert (dst / "Album" / "sub" / "deeper" / "c.txt").read_bytes() == b"c"
    assert ft.tree_totals(str(src)) == (3, 8001)
    assert no_part_files(tmp_path)


def test_merging_two_folders_keeps_both_sides(tmp_path):
    make_tree(tmp_path / "a" / "Photos", {"one.jpg": b"1", "same.jpg": b"new"})
    make_tree(tmp_path / "b" / "Photos", {"two.jpg": b"2", "same.jpg": b"old"})
    rec = Recorder()
    res = ft.execute_transfer([str(tmp_path / "a" / "Photos")], str(tmp_path / "b"), "copy", "merge", progress=rec)
    merged = tmp_path / "b" / "Photos"
    assert sorted(p.name for p in merged.iterdir()) == ["one.jpg", "same.jpg", "two.jpg"]
    assert (merged / "same.jpg").read_bytes() == b"new"
    assert res["merged_dirs"] == 1


def test_move_with_skip_keeps_the_skipped_files(tmp_path):
    """The old background worker deleted the whole source folder after a move, skipped files included."""
    make_tree(tmp_path / "src" / "Docs", {"keep.txt": b"source version", "moved.txt": b"m"})
    make_tree(tmp_path / "dst" / "Docs", {"keep.txt": b"dest version"})
    task = ft.transfer_manager.submit_transfer(
        [str(tmp_path / "src" / "Docs")], str(tmp_path / "dst"), action="move", collision_policy="skip"
    )
    info = wait(task.id)
    # SKIP skips the whole folder when it already exists at the destination
    assert info["status"] == "completed"
    assert (tmp_path / "src" / "Docs" / "keep.txt").read_bytes() == b"source version"
    assert (tmp_path / "dst" / "Docs" / "keep.txt").read_bytes() == b"dest version"

    task = ft.transfer_manager.submit_transfer(
        [str(tmp_path / "src" / "Docs")], str(tmp_path / "dst"), action="move", collision_policy="merge"
    )
    info = wait(task.id)
    assert info["status"] == "completed" and info["percent"] == 100.0
    assert (tmp_path / "dst" / "Docs" / "moved.txt").exists()
    assert not (tmp_path / "src" / "Docs").exists()


def test_move_on_the_same_disk_is_a_rename_and_still_counts(tmp_path):
    make_tree(tmp_path / "src" / "Big", {"x.bin": b"x" * 4096, "y.bin": b"y" * 1024})
    rec = Recorder()
    with patch.object(ft, "_stream_copy", side_effect=AssertionError("should rename, not copy")):
        ft.execute_transfer([str(tmp_path / "src" / "Big")], str(tmp_path / "dst"), "move", "merge", progress=rec)
    assert (rec.files, rec.bytes) == (2, 5120)
    assert (tmp_path / "dst" / "Big" / "x.bin").exists()


def test_cross_device_move_falls_back_to_copy(tmp_path):
    make_tree(tmp_path / "src", {"f.bin": b"z" * 2048})
    rec = Recorder()
    real_replace = os.replace

    def fake_replace(a, b):
        if str(a).endswith("f.bin") and not str(a).endswith(".zettnas-part"):
            raise OSError(18, "Invalid cross-device link")
        return real_replace(a, b)

    with (
        patch.object(ft.os, "replace", side_effect=fake_replace),
        patch.object(ft.os, "rename", side_effect=OSError(18, "x")),
    ):
        ft.execute_transfer([str(tmp_path / "src" / "f.bin")], str(tmp_path / "dst"), "move", "merge", progress=rec)
    assert (tmp_path / "dst" / "f.bin").read_bytes() == b"z" * 2048
    assert not (tmp_path / "src" / "f.bin").exists()
    assert rec.bytes == 2048 and no_part_files(tmp_path)


def test_cancel_leaves_no_partial_file_and_keeps_the_old_one(tmp_path):
    make_tree(tmp_path / "src", {"big.bin": os.urandom(3 * 1024 * 1024)})
    make_tree(tmp_path / "dst", {"big.bin": b"previous"})
    rec = Recorder(cancel_after_bytes=1)
    with patch.object(ft, "_COPY_STEP", 512 * 1024), pytest.raises(ft.TransferCancelled):
        ft.execute_transfer(
            [str(tmp_path / "src" / "big.bin")], str(tmp_path / "dst"), "copy", "overwrite", progress=rec
        )
    assert (tmp_path / "dst" / "big.bin").read_bytes() == b"previous"
    assert no_part_files(tmp_path)


def test_cancelled_task_reports_cancelled(tmp_path):
    make_tree(tmp_path / "src", {"big.bin": b"x" * 1024})
    started = []

    def slow_copy(src, dst, progress, durable=False):
        open(dst, "wb").close()
        started.append(dst)
        while True:  # a copy that only ends when cancelled
            progress.checkpoint()
            time.sleep(0.01)

    with patch.object(ft, "_stream_copy", side_effect=slow_copy):
        task = ft.transfer_manager.submit_transfer([str(tmp_path / "src" / "big.bin")], str(tmp_path / "dst"))
        for _ in range(200):
            if started:
                break
            time.sleep(0.01)
        assert ft.transfer_manager.get_task(task.id)["status"] == "running"
        ft.transfer_manager.pause_task(task.id)
        time.sleep(0.05)
        assert ft.transfer_manager.get_task(task.id)["status"] == "paused"
        ft.transfer_manager.cancel_task(task.id)
        info = wait(task.id)
        for _ in range(200):  # the worker cleans up after the status changes
            if task.id not in ft.transfer_manager._tasks:
                break
            time.sleep(0.01)
    assert info["status"] == "cancelled"
    assert no_part_files(tmp_path) and not (tmp_path / "dst" / "big.bin").exists()


def test_folder_into_itself_is_refused(tmp_path):
    make_tree(tmp_path / "A", {"f.txt": b"1", "B/g.txt": b"2"})
    res = ft.execute_transfer([str(tmp_path / "A")], str(tmp_path / "A" / "B"), "move", "merge")
    assert res["errors"] and "into itself" in res["errors"][0]["error"]
    assert (tmp_path / "A" / "f.txt").exists()


def test_duplicate_uses_the_new_name_next_to_the_original(tmp_path):
    make_tree(tmp_path, {"Report.pdf": b"pdf", "Report copy.pdf": b"older copy"})
    task = ft.transfer_manager.submit_transfer(
        [str(tmp_path / "Report.pdf")],
        str(tmp_path),
        action="copy",
        collision_policy="keep_both",
        target_names=["Report copy.pdf"],
        kind="duplicate",
    )
    info = wait(task.id)
    assert info["status"] == "completed" and info["kind"] == "duplicate"
    assert (tmp_path / "Report copy (1).pdf").read_bytes() == b"pdf"
    assert (tmp_path / "Report copy.pdf").read_bytes() == b"older copy"


def test_task_fails_only_when_nothing_was_done(tmp_path):
    task = ft.transfer_manager.submit_transfer([str(tmp_path / "missing")], str(tmp_path / "dst"))
    info = wait(task.id)
    assert info["status"] == "failed" and "not found" in info["error"]

    make_tree(tmp_path / "src", {"ok.txt": b"1"})
    task = ft.transfer_manager.submit_transfer(
        [str(tmp_path / "src" / "ok.txt"), str(tmp_path / "missing")], str(tmp_path / "dst")
    )
    info = wait(task.id)
    assert info["status"] == "completed" and info["error"].startswith("1 item(s) failed")
    assert info["result"]["transferred"] == 1


def test_async_endpoint_checks_target_names(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    make_tree(root, {"a.txt": b"1"})
    with patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)]):
        base = {"sources": [str(root / "a.txt")], "destination_dir": str(root), "action": "copy"}
        for bad in (["../x"], ["a/b"], [".."], ["x", "y"]):
            res = client.post("/api/fs/transfer/async", json={**base, "target_names": bad}, headers=auth_headers)
            assert res.status_code == 400, bad
        res = client.post(
            "/api/fs/transfer/async",
            json={**base, "target_names": ["a copy.txt"], "kind": "duplicate", "collision_policy": "keep_both"},
            headers=auth_headers,
        )
        assert res.status_code == 200
        info = wait(res.json()["task_id"])
        assert info["status"] == "completed"
        assert (root / "a copy.txt").read_bytes() == b"1"
