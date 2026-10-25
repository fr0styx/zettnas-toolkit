"""PERF-10: the hardware budget script, against a fake /proc."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import hardware_budgets as hb  # noqa: E402


def _proc(root, pid, cmd, ticks, switches, rss_kb):
    d = root / str(pid)
    (d / "task" / str(pid)).mkdir(parents=True)
    (d / "cmdline").write_bytes(cmd.replace(" ", "\0").encode())
    fields = ["S"] + ["0"] * 10 + [str(ticks), "0"] + ["0"] * 30
    (d / "stat").write_text(f"{pid} (python3) " + " ".join(fields))
    (d / "status").write_text(f"VmRSS:\t{rss_kb} kB\n")
    (d / "task" / str(pid) / "status").write_text(
        f"voluntary_ctxt_switches:\t{switches}\nnonvoluntary_ctxt_switches:\t0\n"
    )


def test_measures_and_judges(tmp_path, monkeypatch, capsys):
    _proc(tmp_path, 1, "python3 -m backend.main", 100, 1000, 180 * 1024)
    _proc(tmp_path, 2, "python3 -m backend.fan_watchdog", 0, 0, 10 * 1024)
    _proc(tmp_path, 3, "/ovms/bin/ovms --port 8000", 0, 0, 3 * 1024 * 1024)
    (tmp_path / "self").mkdir()  # not a pid
    state = {"t": 0.0}

    def sleep(s):
        state["t"] += s
        _proc_update = tmp_path / "1"
        fields = ["S"] + ["0"] * 10 + ["160", "0"] + ["0"] * 30  # +60 ticks over 60 s = 1% of a core at 100 Hz
        (_proc_update / "stat").write_text("1 (python3) " + " ".join(fields))
        (_proc_update / "task" / "1" / "status").write_text(
            "voluntary_ctxt_switches:\t1600\nnonvoluntary_ctxt_switches:\t0\n"
        )

    monkeypatch.setattr(hb.os, "sysconf", lambda name: 100)
    values = hb.measure(60, proc=str(tmp_path), sleep=sleep, clock=lambda: state["t"])
    assert values == {"idle-cpu": 1.0, "wakeups": 600, "backend-memory": 180.0, "ai-memory": 3072.0}
    ok = hb.verdicts(values)
    assert ok == {"idle-cpu": True, "wakeups": True, "backend-memory": True, "ai-memory": False}

    monkeypatch.setattr(hb, "measure", lambda seconds: values)
    out_dir = tmp_path / "results"
    assert hb.main(["--seconds", "1", "--results", str(out_dir)]) == 0  # warnings, not a red run
    assert hb.main(["--seconds", "1", "--results", str(out_dir), "--strict"]) == 1
    printed = capsys.readouterr().out
    assert "FAIL ai-memory" in printed and "PASS idle-cpu" in printed
    assert "3072" not in printed  # numbers stay on the machine
    saved = json.loads(next(out_dir.iterdir()).read_text())
    assert saved["values"]["ai-memory"] == 3072.0


def test_no_backend_is_reported(tmp_path):
    import pytest

    _proc(tmp_path, 7, "sleep 100", 0, 0, 100)
    with pytest.raises(SystemExit, match="not running"):
        hb.measure(0, proc=str(tmp_path), sleep=lambda s: None)
    assert hb.cpu_ticks("99", str(tmp_path)) == 0 and hb.context_switches("99", str(tmp_path)) == 0
    assert hb.rss_mb("99", str(tmp_path)) == 0.0
