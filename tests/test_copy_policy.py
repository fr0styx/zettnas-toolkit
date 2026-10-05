"""Media-ingest copy planning: EXIF date folders, collisions, policy, destination guard."""

import os

import pytest

from backend.services.copy_engine import (
    build_copy_plan,
    resolve_copy_destination,
    select_files_to_copy,
)


@pytest.fixture
def card(tmp_path):
    src = tmp_path / "card"
    (src / "DCIM" / "100CANON").mkdir(parents=True)
    (src / "DCIM" / "100CANON" / "IMG_0001.JPG").write_bytes(b"a" * 100)
    (src / "DCIM" / "100CANON" / "IMG_0002.JPG").write_bytes(b"b" * 50)
    (src / "MISC").mkdir()
    (src / "MISC" / "empty.txt").write_bytes(b"")
    os.symlink("/etc/passwd", src / "MISC" / "link")
    dst = tmp_path / "dest"
    dst.mkdir()
    return str(src) + "/", str(dst) + "/"


def fixed_date(_path):
    return "2026/10/05"


def test_mirror_mode_keeps_tree(card):
    src, dst = card
    entries, collisions = build_copy_plan(src, dst, use_exif=False)
    dsts = sorted(os.path.relpath(e[1], dst) for e in entries)
    assert dsts == ["DCIM/100CANON/IMG_0001.JPG", "DCIM/100CANON/IMG_0002.JPG", "MISC/empty.txt"]
    assert collisions == []


def test_symlinks_on_card_are_skipped(card):
    src, dst = card
    entries, _ = build_copy_plan(src, dst, use_exif=False)
    assert not any(e[0].endswith("/link") for e in entries)


def test_exif_mode_groups_by_date(card):
    src, dst = card
    entries, _ = build_copy_plan(src, dst, use_exif=True, date_func=fixed_date)
    dsts = sorted(os.path.relpath(e[1], dst) for e in entries)
    assert dsts == ["2026/10/05/IMG_0001.JPG", "2026/10/05/IMG_0002.JPG", "2026/10/05/empty.txt"]


def test_exif_mode_falls_back_to_tree_when_no_date(card):
    src, dst = card
    entries, _ = build_copy_plan(src, dst, use_exif=True, date_func=lambda p: None)
    assert any(e[1].endswith("DCIM/100CANON/IMG_0001.JPG") for e in entries)


def test_sizes_are_recorded(card):
    src, dst = card
    entries, _ = build_copy_plan(src, dst, use_exif=False)
    sizes = {os.path.basename(e[0]): e[2] for e in entries}
    assert sizes == {"IMG_0001.JPG": 100, "IMG_0002.JPG": 50, "empty.txt": 0}


def test_collisions_detected(card):
    src, dst = card
    os.makedirs(os.path.join(dst, "DCIM", "100CANON"))
    open(os.path.join(dst, "DCIM", "100CANON", "IMG_0001.JPG"), "w").close()
    entries, collisions = build_copy_plan(src, dst, use_exif=False)
    assert collisions == ["DCIM/100CANON/IMG_0001.JPG"]
    assert sum(1 for e in entries if e[3]) == 1


def test_skip_policy_drops_existing_files(card):
    src, dst = card
    os.makedirs(os.path.join(dst, "DCIM", "100CANON"))
    open(os.path.join(dst, "DCIM", "100CANON", "IMG_0001.JPG"), "w").close()
    entries, _ = build_copy_plan(src, dst, use_exif=False)
    files, total = select_files_to_copy(entries, skip_existing=True)
    assert len(files) == 2 and total == 50


def test_overwrite_policy_keeps_everything(card):
    src, dst = card
    os.makedirs(os.path.join(dst, "DCIM", "100CANON"))
    open(os.path.join(dst, "DCIM", "100CANON", "IMG_0001.JPG"), "w").close()
    entries, _ = build_copy_plan(src, dst, use_exif=False)
    files, total = select_files_to_copy(entries, skip_existing=False)
    assert len(files) == 3 and total == 150


def test_zero_byte_files_are_copied(card):
    src, dst = card
    entries, _ = build_copy_plan(src, dst, use_exif=False)
    files, _ = select_files_to_copy(entries, skip_existing=False)
    assert any(f[0].endswith("empty.txt") for f in files)


def test_destination_inside_root_is_accepted(pool_tree):
    assert resolve_copy_destination(os.path.join(pool_tree, "media")) == os.path.realpath(
        os.path.join(pool_tree, "media")
    )


@pytest.mark.parametrize("bad", ["/etc", "", None, "/nonexistent/path"])
def test_destination_outside_root_is_rejected(pool_tree, bad):
    assert resolve_copy_destination(bad) is None


def test_destination_symlink_escape_is_rejected(pool_tree):
    assert resolve_copy_destination(os.path.join(pool_tree, "escape")) is None


def test_destination_must_be_directory(pool_tree):
    assert resolve_copy_destination(os.path.join(pool_tree, "media", "readme.txt")) is None
