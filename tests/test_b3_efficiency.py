"""Batch 3 of the v1.10 audit: efficiency."""

import os
import threading

import pytest


@pytest.mark.skipif(not os.path.isdir("/proc/self/task"), reason="Linux only")
def test_threads_show_their_names_to_the_os():
    from backend.services.supervisor import install_os_thread_names

    assert install_os_thread_names()
    seen = {}

    def work():
        tid = threading.get_native_id()
        with open(f"/proc/self/task/{tid}/comm") as f:
            seen["comm"] = f.read().strip()

    t = threading.Thread(target=work, name="ZnTestThread")
    t.start()
    t.join()
    assert seen["comm"] == "ZnTestThread"


def test_chat_models_unload_after_the_idle_setting(monkeypatch):
    from backend.services import chat_llm_runtime, rag_engine

    monkeypatch.setattr(rag_engine.get_rag_engine(), "get_config", lambda: {"idle_unload_minutes": 15})
    assert chat_llm_runtime._keep_alive() == "15m"
    monkeypatch.setattr(rag_engine.get_rag_engine(), "get_config", lambda: {"idle_unload_minutes": 0})
    assert chat_llm_runtime._keep_alive() == "-1"


def test_captions_wait_while_someone_chats(monkeypatch):
    from backend.services import chat_llm_runtime, vision_queue

    chat_llm_runtime.mark_chat_activity()
    assert vision_queue.system_idle() is False
    chat_llm_runtime._LAST_CHAT["at"] = 0.0


def test_the_pool_list_is_read_at_most_every_30_seconds(monkeypatch):
    from backend.hardware import storage

    calls = []

    class _Adapter:
        def list_pools(self):
            calls.append(1)
            return []

    a = _Adapter()
    storage._POOLS_CACHE.update(at=0.0, pools=None, adapter=None)
    storage._cached_pools(a)
    storage._cached_pools(a)
    assert len(calls) == 1


def test_nothing_is_serialised_while_nobody_listens(monkeypatch):
    from unittest.mock import MagicMock

    from backend.services import broadcaster as bmod

    b = bmod.StatsBroadcaster()
    b._loop = MagicMock(is_running=lambda: True)
    called = []
    monkeypatch.setattr(bmod, "fast_dumps", lambda d: called.append(d) or "{}")
    b.broadcast({"cpu": 1}, full_data={"cpu": 1})
    assert called == [] and b._latest_full_data == {"cpu": 1}


def test_idle_spinning_disks_are_read_less_often_when_enabled(monkeypatch, tmp_path):
    from backend import config
    from backend.hardware import disks

    stats = tmp_path / "diskstats"
    stats.write_text("   8      16 sdb 100 0 0 0 50 0 0 0 0 0 0 0 0 0\n")
    monkeypatch.setattr(disks, "HOST_PROC", str(tmp_path))
    disks._IO_SEEN.clear()
    monkeypatch.setattr(config, "SMART_IDLE_ADAPTIVE", True)
    monkeypatch.setattr(config, "SMART_IDLE_POLL", 1800)
    assert disks._hdd_interval("sdb", 1000.0) == disks.SMART_POLL_INTERVAL_HDD  # first sight: busy
    assert disks._hdd_interval("sdb", 1000.0 + 700) == 1800  # no I/O for 700 s
    stats.write_text("   8      16 sdb 101 0 0 0 50 0 0 0 0 0 0 0 0 0\n")
    assert disks._hdd_interval("sdb", 2000.0) == disks.SMART_POLL_INTERVAL_HDD  # active again
    monkeypatch.setattr(config, "SMART_IDLE_ADAPTIVE", False)
    assert disks._hdd_interval("sdb", 9000.0) == disks.SMART_POLL_INTERVAL_HDD  # off by default


def test_unreadable_diskstats_count_as_busy(monkeypatch, tmp_path):
    """No /proc/diskstats (or a garbled one): the disk is treated as active, never as idle."""
    from backend.hardware import disks

    monkeypatch.setattr(disks, "HOST_PROC", str(tmp_path / "missing"))
    assert disks._idle_for("sda", 1000.0) == 0.0
    (tmp_path / "diskstats").write_text("   8       0 sda x y z a b c d e f g h\n")
    monkeypatch.setattr(disks, "HOST_PROC", str(tmp_path))
    assert disks._idle_for("sda", 1000.0) == 0.0


def _fake_sys(tmp_path, disks):
    """A sysfs tree: /sys/dev/block/8:1 -> devices/.../sda/sda1, plus md0 over two members."""
    import os

    base = tmp_path / "sys"
    for name, rot in disks.items():
        q = base / "devices" / "pci" / "block" / name / "queue"
        q.mkdir(parents=True)
        (q / "rotational").write_text(f"{rot}\n")
        (base / "block").mkdir(exist_ok=True)
        os.symlink(q.parent, base / "block" / name)
    part = base / "devices" / "pci" / "block" / "sda" / "sda1"
    part.mkdir()
    (part / "partition").write_text("1\n")
    (base / "dev" / "block").mkdir(parents=True)
    os.symlink(part, base / "dev" / "block" / "8:1")
    os.symlink(base / "devices" / "pci" / "block" / "nvme0n1", base / "dev" / "block" / "259:0")
    return base


def test_the_data_folder_on_a_spinning_disk_is_reported(tmp_path, monkeypatch):
    import os

    from backend.services import data_health
    from backend.state import Z_STATE

    base = _fake_sys(tmp_path, {"sda": 1, "nvme0n1": 0})
    assert data_health.data_disk("/x", str(base), st_dev=os.makedev(8, 1)) == ("sda", True)
    assert data_health.data_disk("/x", str(base), st_dev=os.makedev(259, 0)) == ("nvme0n1", False)
    assert data_health.data_disk("/x", str(base), st_dev=os.makedev(0, 51)) == ("", None)  # FUSE / overlay
    before = len(Z_STATE.events) if hasattr(Z_STATE, "events") else 0
    assert data_health.warn_if_on_spinning_disk("/x", str(base), st_dev=os.makedev(8, 1)) is True
    assert data_health.warn_if_on_spinning_disk("/x", str(base), st_dev=os.makedev(259, 0)) is False
    if hasattr(Z_STATE, "events"):
        assert len(Z_STATE.events) == before + 1


def test_raid_devices_answer_for_their_member_disks(tmp_path):
    import os

    from backend.services import data_health

    base = _fake_sys(tmp_path, {"sda": 1, "nvme0n1": 0, "md0": 0, "sdb": 0})
    (base / "block" / "md0" / "slaves").mkdir()
    os.symlink(base / "block" / "sda", base / "block" / "md0" / "slaves" / "sda")
    assert data_health._spinning("md0", str(base)) is True
    assert data_health._spinning("missing", str(base)) is None


def test_raid_over_partitions_and_unknown_devices(tmp_path):
    """md over sda1 answers for sda; a device number sysfs doesn't know, or a missing folder, is unknown."""
    import os

    from backend.services import data_health

    base = _fake_sys(tmp_path, {"sda": 1, "nvme0n1": 0, "md1": 0})
    (base / "class" / "block").mkdir(parents=True)
    os.symlink(base / "devices" / "pci" / "block" / "sda" / "sda1", base / "class" / "block" / "sda1")
    (base / "block" / "md1" / "slaves").mkdir()
    os.symlink(base / "class" / "block" / "sda1", base / "block" / "md1" / "slaves" / "sda1")
    assert data_health._spinning("md1", str(base)) is True
    assert data_health._parent("nvme0n1", str(base)) == "nvme0n1"
    assert data_health.data_disk("/x", str(base), st_dev=os.makedev(8, 9)) == ("", None)
    assert data_health.data_disk(str(tmp_path / "missing"), str(base)) == ("", None)


def test_the_data_guard_checks_the_disk_once_at_start(monkeypatch, tmp_path):
    from backend.services import data_health

    seen = []
    monkeypatch.setattr(data_health, "warn_if_on_spinning_disk", lambda folder: seen.append(folder) or 1 / 0)
    monkeypatch.setattr(data_health, "take_daily_snapshot_if_due", lambda folder: None)

    def stop(_):
        raise KeyboardInterrupt

    try:
        data_health.data_guard_daemon(str(tmp_path), sleep=stop)
    except KeyboardInterrupt:
        pass
    assert seen == [str(tmp_path)]  # a failing check never stops the snapshots
