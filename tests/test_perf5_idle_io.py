"""PERF-5: idle loops leave the data folder alone (on a FUSE mount every look blocks)."""

import json
import os
import types

import pytest


def test_settings_written_by_the_app_are_seen_at_once_outside_edits_later(monkeypatch, tmp_path):
    from backend import fsutil

    path = str(tmp_path / "led_state.json")
    fsutil.atomic_write_json(path, {"night_mode": False})
    stats = []
    real_stat = os.stat
    monkeypatch.setattr(fsutil.os, "stat", lambda p, *a, **k: stats.append(p) or real_stat(p, *a, **k))
    for _ in range(5):
        assert fsutil.read_json_cached(path, {}, max_age=fsutil.SETTINGS_RECHECK_SECS) == {"night_mode": False}
    assert stats == []  # the app's own write filled the cache: no look at the file
    fsutil.atomic_write_json(path, {"night_mode": True})
    assert fsutil.read_json_cached(path, {}, max_age=fsutil.SETTINGS_RECHECK_SECS) == {"night_mode": True}
    fsutil.clear_json_cache()
    assert fsutil.read_json_cached(path, {}, max_age=fsutil.SETTINGS_RECHECK_SECS) == {"night_mode": True}
    assert fsutil.SETTINGS_RECHECK_SECS >= 30


def test_screen_state_is_read_from_disk_every_30_seconds(monkeypatch, tmp_path):
    from backend.hardware import screen

    path = tmp_path / "screen_state.json"
    path.write_text(json.dumps({"brightness": 40}))
    monkeypatch.setattr(screen, "SCREEN_STATE_FILE", str(path))
    clock = {"t": 1000.0}
    monkeypatch.setattr(screen.time, "monotonic", lambda: clock["t"])
    assert screen.get_screen_state()["brightness"] == 40
    path.write_text(json.dumps({"brightness": 70}))  # an edit outside the app
    os.utime(path, (2_000_000_000, 2_000_000_000))
    clock["t"] += 10
    assert screen.get_screen_state()["brightness"] == 40  # not looked at yet
    clock["t"] += 25
    assert screen.get_screen_state()["brightness"] == 70  # seen within 30 s


def test_saving_screen_state_updates_the_copy_at_once(monkeypatch, tmp_path):
    from backend.hardware import screen

    monkeypatch.setattr(screen, "SCREEN_STATE_FILE", str(tmp_path / "screen_state.json"))
    monkeypatch.setattr(screen, "set_screen_brightness", lambda *a, **k: True)
    screen.save_screen_state({"brightness": 55})
    assert screen.get_screen_state()["brightness"] == 55


def test_the_ups_settings_come_from_the_cached_copy(monkeypatch, tmp_path):
    from backend import fsutil
    from backend.hardware import ups

    path = str(tmp_path / "ups_config.json")
    monkeypatch.setattr(ups, "UPS_CONFIG_FILE", path)
    fsutil.atomic_write_json(path, {"mode": "nut", "host": "nut.local"})
    opened = []
    monkeypatch.setattr(fsutil, "read_json", lambda p, d=None: opened.append(p) or d)
    first = ups.load_ups_config()
    first["host"] = "changed by a caller"
    assert ups.load_ups_config()["host"] == "nut.local"  # callers get their own copy
    assert opened == []


def test_the_first_time_password_file_is_looked_for_every_30_seconds(monkeypatch):
    import backend.config as cfg

    looks = []
    monkeypatch.setattr(cfg, "verify_password", lambda pw, h: False)
    monkeypatch.setattr(cfg.os.path, "exists", lambda p: looks.append(p) or True)
    clock = {"t": 50.0}
    monkeypatch.setattr(cfg.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(
        cfg, "_default_pw_cache", {"hash": None, "value": False, "file": False, "file_at": float("-inf")}
    )
    assert cfg.is_using_default_password() is True
    clock["t"] += 5
    assert cfg.is_using_default_password() is True
    assert len(looks) == 1
    clock["t"] += 30
    cfg.is_using_default_password()
    assert len(looks) == 2
    monkeypatch.setattr(cfg, "STORED_PASSWORD_HASH", "a new hash")  # a password change looks at once
    cfg.is_using_default_password()
    assert len(looks) == 3


def test_an_idle_reindex_status_is_reused_for_a_few_seconds(monkeypatch, tmp_path):
    from backend.services import rag_reindex_status as rs

    rs._REINDEX_CACHE = {"status": "complete"}
    rs._REINDEX_CACHE_TIME = 1000.0
    rs._REINDEX_KEY = repr(sorted(rs.REINDEX_STATUS.items(), key=lambda kv: str(kv[0])))
    monkeypatch.setattr("time.time", lambda: 1005.0)
    monkeypatch.setattr(rs.os.path, "exists", lambda p: (_ for _ in ()).throw(AssertionError("looked at disk")))
    assert rs.get_reindex_status()["status"] == "complete"
    assert rs.IDLE_RECHECK_SECS <= 30
    # a change to the in-process status (a run failed) is seen at once, not after 15 s
    monkeypatch.setitem(rs.REINDEX_STATUS, "error", "a failure only this test reports")
    with pytest.raises(AssertionError, match="looked at disk"):
        rs.get_reindex_status()


def test_lsblk_runs_again_only_when_the_disks_change(monkeypatch):
    from backend.hardware import hal

    H = hal.DiskDiscoveryHAL
    runs = []
    clock = {"t": 0.0}
    signature = {"v": (("sda",), ("ata-x",))}

    def fake_run(cmd, **kw):
        if cmd[:2] == ["lsblk", "-J"]:
            runs.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"blockdevices": []}))

    monkeypatch.setattr(hal.subprocess, "run", fake_run)
    monkeypatch.setattr(hal.time, "time", lambda: clock["t"])
    monkeypatch.setattr(H, "_block_signature", classmethod(lambda cls: signature["v"]))
    monkeypatch.setattr(H, "_read_by_id_links", classmethod(lambda cls: {}))
    H.discover_physical_disks()
    n = len(runs)
    assert n == 1
    clock["t"] = 25.0
    H.discover_physical_disks()  # past the 10 s cache, same disks: no lsblk
    assert len(runs) == n
    signature["v"] = (("sda", "sdb"), ("ata-x", "ata-y"))  # a disk was plugged in
    H.discover_physical_disks()
    assert len(runs) == 2 * n
    clock["t"] = 25.0 + H._SAME_DISKS_TTL + 1
    H.discover_physical_disks()  # once a minute anyway
    assert len(runs) == 3 * n


def test_the_block_signature_reads_two_folders(monkeypatch, tmp_path):
    from backend.hardware import hal

    (tmp_path / "block").mkdir()
    (tmp_path / "block" / "sda").mkdir()
    monkeypatch.setattr(hal.DiskDiscoveryHAL, "_resolve_sys_root", classmethod(lambda cls: str(tmp_path)))
    monkeypatch.setattr(hal.DiskDiscoveryHAL, "_resolve_dev_root", classmethod(lambda cls: str(tmp_path / "none")))
    assert hal.DiskDiscoveryHAL._block_signature() == (("sda",), ())


def test_the_appliance_check_is_kept_for_five_minutes(monkeypatch):
    from backend.hardware import fans

    calls = []
    monkeypatch.delenv("FORCE_ZETTLAB_MMIO", raising=False)
    monkeypatch.setattr(fans, "_detect_zettlab_appliance", lambda: calls.append(1) or True)
    clock = {"t": 0.0}
    monkeypatch.setattr(fans.time, "monotonic", lambda: clock["t"])
    assert fans.is_zettlab_appliance() and fans.is_zettlab_appliance()
    assert len(calls) == 1
    clock["t"] = fans.APPLIANCE_RECHECK_SECS + 1
    fans.is_zettlab_appliance()
    assert len(calls) == 2
    monkeypatch.setenv("FORCE_ZETTLAB_MMIO", "0")
    assert fans.is_zettlab_appliance() is False


class _FakeRag:
    def __init__(self):
        from backend.services.rag_engine_learning import RagLearningMixin

        self.calls = []
        self.sig = ("sleeping", "cfg", False, "idle")
        self._watch_tick = types.MethodType(RagLearningMixin._watch_tick, self)

    def _watch_signature(self):
        return self.sig

    def sync_watched_deferred_queue(self):
        self.calls.append("sync")

    def check_and_trigger_spinup_auto_learn(self, background=True):
        self.calls.append("check")

    def _maybe_reembed_fallback_files(self):
        self.calls.append("fallback")


def test_the_index_watcher_skips_the_database_while_nothing_changed(monkeypatch):
    from backend.services import rag_engine_learning as rl

    clock = {"t": 0.0}
    monkeypatch.setattr(rl.time, "monotonic", lambda: clock["t"])
    rag = _FakeRag()
    last: dict = {}
    assert rag._watch_tick(last) is True
    assert rag.calls == ["sync", "check", "fallback"]
    rag.calls.clear()
    clock["t"] += rl.SPINUP_WATCH_SECS
    assert rag._watch_tick(last) is False  # same disks, settings and state
    assert rag.calls == ["fallback"]
    rag.sig = ("a disk woke", "cfg", False, "idle")
    assert rag._watch_tick(last) is True
    clock["t"] += rl.WATCH_FULL_EVERY_SECS
    assert rag._watch_tick(last) is True  # every five minutes anyway
    rag.calls.clear()
    rag.sig = ("a disk woke", None, False, "idle")  # no settings file: nothing to reconcile
    rag._watch_tick(last)
    assert rag.calls == ["check", "fallback"]


def test_the_watch_signature_needs_no_database(monkeypatch, tmp_path):
    from backend.services import rag_engine_learning as rl

    cfg = tmp_path / "rag_config.json"
    cfg.write_text("{}")
    monkeypatch.setattr(rl, "_core", lambda: types.SimpleNamespace(RAG_CONFIG_PATH=str(cfg)))
    monkeypatch.setattr(rl.rag_standby, "get_sleeping_disks_list", lambda: ["sdb"])
    fake = types.SimpleNamespace(_is_indexing=False, _sync_state="idle")
    sig = rl.RagLearningMixin._watch_signature(fake)
    assert sig[0] == ("sdb",) and sig[1] is not None and sig[2:] == (False, "idle")
    cfg.unlink()
    assert rl.RagLearningMixin._watch_signature(fake)[1] is None
