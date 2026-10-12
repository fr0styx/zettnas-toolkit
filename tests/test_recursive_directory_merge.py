"""
Tests for recursive directory merge, collision policies, and resilient file transfer.
"""

import os
from backend.services.fs_transfer import (
    CollisionPolicy,
    check_transfer_conflicts,
    execute_transfer,
    merge_directory_tree,
)


def test_merge_directory_tree_non_destructive(tmp_path):
    # Setup source directory
    src = tmp_path / "src_folder"
    src.mkdir()
    (src / "file1.txt").write_text("file 1 from source")
    (src / "sub").mkdir()
    (src / "sub" / "file2.txt").write_text("file 2 from source")

    # Setup destination directory with existing file
    dst = tmp_path / "dst_folder"
    dst.mkdir()
    (dst / "existing.txt").write_text("pre-existing file in destination")
    (dst / "file1.txt").write_text("old file 1 in destination")

    # Perform recursive merge
    stats = merge_directory_tree(
        str(src),
        str(dst),
        action="copy",
        policy=CollisionPolicy.MERGE,
    )

    assert stats["merged_dirs"] >= 1
    assert stats["transferred"] >= 2
    # Verify pre-existing file remained intact
    assert (dst / "existing.txt").read_text() == "pre-existing file in destination"
    # Verify sub file was created
    assert (dst / "sub" / "file2.txt").read_text() == "file 2 from source"


def test_collision_policy_skip(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "data.txt").write_text("new content")

    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "data.txt").write_text("original content")

    res = execute_transfer(
        [str(src / "data.txt")],
        str(dst),
        action="copy",
        policy="skip",
    )

    assert res["skipped"] == 1
    assert (dst / "data.txt").read_text() == "original content"


def test_collision_policy_keep_both(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "report.pdf").write_text("new report")

    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "report.pdf").write_text("original report")

    res = execute_transfer(
        [str(src / "report.pdf")],
        str(dst),
        action="copy",
        policy="keep_both",
    )

    assert res["transferred"] == 1
    assert (dst / "report.pdf").read_text() == "original report"
    assert (dst / "report (1).pdf").exists()
    assert (dst / "report (1).pdf").read_text() == "new report"


def test_check_transfer_conflicts(tmp_path):
    src1 = tmp_path / "a.txt"
    src1.write_text("hello")
    src2 = tmp_path / "b.txt"
    src2.write_text("world")

    dst = tmp_path / "target"
    dst.mkdir()
    (dst / "a.txt").write_text("already here")

    conflicts = check_transfer_conflicts([str(src1), str(src2)], str(dst))
    assert conflicts["has_conflict"] is True
    assert conflicts["conflict_count"] == 1
    assert conflicts["conflicts"][0]["name"] == "a.txt"
