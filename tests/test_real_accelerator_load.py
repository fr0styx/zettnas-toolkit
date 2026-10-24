"""GPU and NPU load are reported as measured, never estimated from clock speed or AI activity."""

import glob
import os

from backend.hardware import host_telemetry as ht


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(str(value))


def test_gpu_load_unknown_without_rc6_even_at_full_clock(tmp_path, monkeypatch):
    sysfs = tmp_path / "sys"
    _write(str(sysfs / "class/drm/card0/gt_act_freq_mhz"), 2100)
    _write(str(sysfs / "class/drm/card0/gt_max_freq_mhz"), 2200)
    monkeypatch.setattr(ht, "HOST_SYS", str(sysfs))
    monkeypatch.setattr(ht.glob, "glob", lambda pattern, _g=glob.glob: _g(pattern) if str(sysfs) in pattern else [])
    out = ht._sample_gpu_dynamic()
    assert out["cur_freq_mhz"] == 2100
    assert out["util_pct"] is None


def test_gpu_load_comes_from_rc6_residency(tmp_path, monkeypatch):
    sysfs = tmp_path / "sys"
    rc6 = str(sysfs / "class/drm/card0/gt/gt0/rc6_residency_ms")
    _write(str(sysfs / "class/drm/card0/gt/gt0/rps_act_freq_mhz"), 2100)
    _write(rc6, 1000)
    monkeypatch.setattr(ht, "HOST_SYS", str(sysfs))
    monkeypatch.setattr(ht.glob, "glob", lambda pattern, _g=glob.glob: _g(pattern) if str(sysfs) in pattern else [])
    clock = [1000.0]
    monkeypatch.setattr(ht.time, "time", lambda: clock[0])
    monkeypatch.setitem(ht._GPU_LAST_SAMPLE, "ts", 0.0)
    monkeypatch.setitem(ht._GPU_LAST_SAMPLE, "rc6_by_path", {})
    monkeypatch.setitem(ht._GPU_LAST_SAMPLE, "util_pct", 0.0)
    ht._sample_gpu_dynamic()
    clock[0] += 1.0
    _write(rc6, 1900)  # idle 900 of 1000 ms -> 10 % busy, even though the clock is near max
    out = ht._sample_gpu_dynamic()
    assert out["util_pct"] == 10.0


def test_stats_do_not_raise_the_load_while_the_ai_runs():
    import inspect

    from backend.services import stats_collector

    src = inspect.getsource(stats_collector._build_payload)
    assert "65.0" not in src and "75.0" not in src
