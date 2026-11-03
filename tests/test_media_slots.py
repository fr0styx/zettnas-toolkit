"""The card slots module: kernel polling of the slots and the slot's size (ARC-22)."""

import subprocess
from types import SimpleNamespace

from backend.hardware import media_slots
from backend.hardware.pal import generic_linux


def _poll_file(tmp_path, value):
    block = tmp_path / "sdb"
    block.mkdir()
    (block / "events_poll_msecs").write_text(value)
    return block


def test_stopped_polling_is_turned_back_on(tmp_path):
    for value in ("-1\n", "0\n", ""):
        block = tmp_path / f"b{len(value)}"
        block.mkdir()
        (block / "events_poll_msecs").write_text(value)
        media_slots._ensure_slot_polling(str(block), "sdb", is_empty=False)
        assert (block / "events_poll_msecs").read_text() == "2000\n"


def test_running_polling_is_left_alone(tmp_path):
    block = _poll_file(tmp_path, "500\n")
    media_slots._ensure_slot_polling(str(block), "sdb", is_empty=False)
    assert (block / "events_poll_msecs").read_text() == "500\n"


def test_an_empty_slot_is_opened_once_per_three_seconds(tmp_path, monkeypatch):
    block = _poll_file(tmp_path, "2000\n")
    opened = []
    monkeypatch.setattr(media_slots.os.path, "exists", lambda p: p == "/dev/sdb" or p.endswith("events_poll_msecs"))
    monkeypatch.setattr(media_slots.os, "open", lambda p, flags: opened.append(p) or 7)
    monkeypatch.setattr(media_slots.os, "close", lambda fd: None)
    monkeypatch.setattr(media_slots, "_LAST_MEDIA_PROBE", 0.0)
    clock = iter([100.0, 101.0, 104.5])
    monkeypatch.setattr(media_slots.time, "time", lambda: next(clock))
    for _ in range(3):
        media_slots._ensure_slot_polling(str(block), "sdb", is_empty=True)
    assert opened == ["/dev/sdb", "/dev/sdb"]


def test_a_slot_that_cannot_be_opened_is_skipped(tmp_path, monkeypatch):
    block = _poll_file(tmp_path, "2000\n")
    monkeypatch.setattr(media_slots.os.path, "exists", lambda p: True)

    def refuse(p, flags):
        raise OSError("no medium")

    monkeypatch.setattr(media_slots.os, "open", refuse)
    monkeypatch.setattr(media_slots, "_LAST_MEDIA_PROBE", 0.0)
    media_slots._ensure_slot_polling(str(block), "sdb", is_empty=True)  # no error


def test_an_unwritable_poll_file_is_skipped(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(media_slots.os.path, "exists", lambda p: p.endswith("events_poll_msecs"))
    monkeypatch.setattr(media_slots, "open", refuse, raising=False)
    media_slots._ensure_slot_polling(str(tmp_path), "sdb", is_empty=False)  # no error


def _run_returning(code, out):
    return lambda *a, **k: SimpleNamespace(returncode=code, stdout=out)


def test_capacity_comes_from_read_capacity(monkeypatch):
    monkeypatch.setattr(media_slots.os.path, "exists", lambda p: p == "/dev/sdb")
    monkeypatch.setattr(
        media_slots.subprocess,
        "run",
        _run_returning(0, "Read Capacity results:\n   Device size: 31914983424 bytes, 30436.5 MiB\n"),
    )
    assert media_slots.probe_media_slot_capacity("sdb") == 31914983424


def test_a_slot_that_is_not_ready_has_no_card(monkeypatch):
    monkeypatch.setattr(media_slots.os.path, "exists", lambda p: p == "/dev/sdb")
    monkeypatch.setattr(media_slots.subprocess, "run", _run_returning(2, "Device not ready\n"))
    assert media_slots.probe_media_slot_capacity("sdb") == 0


def test_without_read_capacity_the_kernel_size_is_used(tmp_path, monkeypatch):
    size = tmp_path / "size"
    size.write_text("1024\n")

    def missing(*a, **k):
        raise FileNotFoundError("sg_readcap")

    real_exists = media_slots.os.path.exists
    monkeypatch.setattr(media_slots.os.path, "exists", lambda p: p == "/dev/sdb" or real_exists(p))
    monkeypatch.setattr(media_slots.subprocess, "run", missing)
    assert media_slots.probe_media_slot_capacity("sdb", str(size)) == 1024 * 512


def test_a_timed_out_probe_with_a_bad_kernel_size_is_zero(tmp_path, monkeypatch):
    size = tmp_path / "size"
    size.write_text("garbage")

    def slow(*a, **k):
        raise subprocess.TimeoutExpired("sg_readcap", 1.5)

    real_exists = media_slots.os.path.exists
    monkeypatch.setattr(media_slots.os.path, "exists", lambda p: p == "/dev/sdb" or real_exists(p))
    monkeypatch.setattr(media_slots.subprocess, "run", slow)
    assert media_slots.probe_media_slot_capacity("sdb", str(size)) == 0
    assert media_slots.probe_media_slot_capacity("sdb") == 0


def test_tree_bytes_skips_files_that_vanish(tmp_path, monkeypatch):
    (tmp_path / "a").write_bytes(b"x" * 10)
    (tmp_path / "b").write_bytes(b"y" * 5)
    assert generic_linux._tree_bytes(str(tmp_path)) == 15
    real = generic_linux.os.lstat

    def flaky(p):
        if p.endswith("b"):
            raise FileNotFoundError(p)
        return real(p)

    monkeypatch.setattr(generic_linux.os, "lstat", flaky)
    assert generic_linux._tree_bytes(str(tmp_path)) == 10


def test_a_folder_on_another_filesystem_cannot_convert(tmp_path, monkeypatch):
    monkeypatch.setattr(generic_linux, "fs_of", lambda p, mounts="/proc/mounts": "ext4")
    a = generic_linux.GenericLinuxStorageAdapter.__new__(generic_linux.GenericLinuxStorageAdapter)
    assert a.can_convert(str(tmp_path)) is False
