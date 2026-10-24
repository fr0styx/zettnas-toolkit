"""Front-panel media import: an existing file survives a failed or cancelled overwrite,
and two photos with the same name on the same day both arrive."""

import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from backend.services import copy_engine
from backend.services.copy_engine import PART_SUFFIX, build_copy_plan, copy_one_file
from backend.state import Z_STATE


@pytest.fixture
def state():
    saved = (Z_STATE.copy_abort_flag, Z_STATE.copy_paused, Z_STATE.copy_status, Z_STATE.copy_progress)
    Z_STATE.copy_abort_flag, Z_STATE.copy_paused, Z_STATE.copy_status = False, False, "copying"
    Z_STATE.copy_progress = {"copied": 0}
    yield Z_STATE
    Z_STATE.copy_abort_flag, Z_STATE.copy_paused, Z_STATE.copy_status, Z_STATE.copy_progress = saved


def _files(tmp_path, new=b"new photo " * 1000, old=b"the only other copy"):
    src, dst = tmp_path / "card.jpg", tmp_path / "pool" / "photo.jpg"
    dst.parent.mkdir()
    src.write_bytes(new)
    dst.write_bytes(old)
    return str(src), str(dst)


def test_copy_replaces_only_when_complete(tmp_path, state):
    src, dst = _files(tmp_path)
    assert asyncio.run(copy_one_file(src, dst, True)) is True
    assert Path(dst).read_bytes() == Path(src).read_bytes()
    assert not os.path.exists(dst + PART_SUFFIX) and state.copy_progress["copied"] == os.path.getsize(src)


def test_a_checksum_mismatch_keeps_the_existing_file(tmp_path, state, monkeypatch):
    src, dst = _files(tmp_path)
    calls = []
    real_sha256 = hashlib.sha256

    def sha():
        calls.append(1)
        h = real_sha256()
        if len(calls) == 2:  # the read-back sees different data
            h.update(b"corrupted")
        return h

    monkeypatch.setattr(copy_engine.hashlib, "sha256", sha)
    with pytest.raises(OSError, match="Checksum mismatch"):
        asyncio.run(copy_one_file(src, dst, True))
    assert Path(dst).read_bytes() == b"the only other copy"  # used to be deleted
    assert not os.path.exists(dst + PART_SUFFIX)


def test_a_cancel_keeps_the_existing_file(tmp_path, state):
    src, dst = _files(tmp_path)
    state.copy_abort_flag = True
    assert asyncio.run(copy_one_file(src, dst, True)) is False
    assert Path(dst).read_bytes() == b"the only other copy"
    assert not os.path.exists(dst + PART_SUFFIX)


def test_a_read_error_keeps_the_existing_file(tmp_path, state):
    _, dst = _files(tmp_path)
    with pytest.raises(OSError):
        asyncio.run(copy_one_file(str(tmp_path / "card-was-pulled.jpg"), dst, True))
    assert Path(dst).read_bytes() == b"the only other copy"


def _card(tmp_path):
    card = tmp_path / "card"
    for folder in ("DCIM/100CANON", "DCIM/101CANON"):
        (card / folder).mkdir(parents=True)
        (card / folder / "IMG_0001.JPG").write_bytes(folder.encode())
    dst = tmp_path / "photos"
    dst.mkdir()
    return str(card) + "/", str(dst) + "/"


def test_same_name_same_day_both_arrive_with_stable_names(tmp_path):
    src, dst = _card(tmp_path)
    same_day = lambda f: "2026/10/24"  # noqa: E731
    entries, collisions = build_copy_plan(src, dst, True, date_func=same_day)
    targets = [os.path.relpath(e[1], dst) for e in entries]
    assert targets == ["2026/10/24/IMG_0001.JPG", "2026/10/24/IMG_0001 (2).JPG"] and collisions == []
    # after importing, the same card again finds both as already there
    for e in entries:
        os.makedirs(os.path.dirname(e[1]), exist_ok=True)
        Path(e[1]).write_bytes(Path(e[0]).read_bytes())
    entries2, collisions2 = build_copy_plan(src, dst, True, date_func=same_day)
    assert [e[1] for e in entries2] == [e[1] for e in entries]
    assert sorted(collisions2) == ["2026/10/24/IMG_0001 (2).JPG", "2026/10/24/IMG_0001.JPG"]


def test_mirrored_tree_keeps_folders(tmp_path):
    src, dst = _card(tmp_path)
    entries, _ = build_copy_plan(src, dst, False)
    assert [os.path.relpath(e[1], dst) for e in entries] == ["DCIM/100CANON/IMG_0001.JPG", "DCIM/101CANON/IMG_0001.JPG"]
