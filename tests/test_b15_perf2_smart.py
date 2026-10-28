"""B15 PERF-2: idle-adaptive SMART by default, NVMe every 60 s, one pool for SMART reads."""

import threading
import time

from backend.hardware import disks
from backend.settings import load_settings
from backend.state import Z_STATE


def test_the_new_defaults():
    s, _ = load_settings({})
    assert s.smart_idle_adaptive is True
    assert s.smart_poll_nvme == 60
    old, _ = load_settings({"SMART_IDLE_ADAPTIVE": "0", "SMART_POLL_NVME": "15"})
    assert old.smart_idle_adaptive is False and old.smart_poll_nvme == 15  # the old behaviour on request


def test_rounds_share_one_pool_and_a_running_read_is_not_queued_twice(monkeypatch):
    monkeypatch.setattr(
        disks, "_discover_disks", lambda: [{"dev": "sdq", "role": "data"}, {"dev": "sdr", "role": "data"}]
    )
    release = threading.Event()
    started = []

    def slow(dev, is_nv):
        started.append(dev)
        if dev == "sdq":
            release.wait(5)

    monkeypatch.setattr(disks, "poll_disk_smart", slow)
    monkeypatch.setattr(disks.concurrent.futures, "wait", lambda fs, timeout=None: None)  # don't wait for sdq
    try:
        disks.poll_all_disks_smart(force=True)
        pool = disks._smart_pool()
        deadline = time.time() + 5
        while "sdr" in disks._SMART_IN_FLIGHT and time.time() < deadline:
            time.sleep(0.01)
        disks.poll_all_disks_smart(force=True)  # sdq is still being read
        deadline = time.time() + 5
        while started.count("sdr") < 2 and time.time() < deadline:
            time.sleep(0.01)
        assert started.count("sdq") == 1 and started.count("sdr") == 2
        assert disks._smart_pool() is pool
    finally:
        release.set()
        deadline = time.time() + 5
        while disks._SMART_IN_FLIGHT and time.time() < deadline:
            time.sleep(0.01)
        for dev in ("sdq", "sdr"):
            Z_STATE.cached_smart_data.pop(dev, None)
            Z_STATE.last_smart_scan.pop(dev, None)
