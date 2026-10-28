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
    assert values == {
        "restarted": False,
        "viewers": 0,
        "processes": 1,
        "idle-cpu": 1.0,
        "wakeups": 600,
        "spawns": 0.0,
        "backend-memory": 180.0,
        "ai-memory": 3072.0,
    }
    ok = hb.verdicts(values)
    assert ok == {"idle-cpu": True, "wakeups": True, "spawns": True, "backend-memory": True, "ai-memory": False}

    monkeypatch.setattr(hb, "measure", lambda seconds, **k: values)
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


def test_idle_budgets_are_skipped_while_someone_uses_the_app(tmp_path, capsys, monkeypatch):
    _proc(tmp_path, 1, "python3 -m backend.main", 0, 0, 1024)
    (tmp_path / "1" / "net").mkdir()
    header = "  sl  local_address rem_address   st\n"
    (tmp_path / "1" / "net" / "tcp").write_text(
        header + "   0: 00000000:1F92 0A00000A:C350 01 0\n   1: 00000000:1F92 00000000:0000 0A 0\n"
    )
    (tmp_path / "1" / "net" / "tcp6").write_text(header)
    assert hb.viewers("1", str(tmp_path)) == 1  # one established, one listening
    ok = hb.verdicts({"viewers": 1, "idle-cpu": 9.0, "wakeups": 99999, "backend-memory": 100.0, "ai-memory": 10.0})
    assert ok == {"idle-cpu": None, "wakeups": None, "backend-memory": True, "ai-memory": True}
    monkeypatch.setattr(
        hb,
        "measure",
        lambda seconds, **k: {
            "viewers": 1,
            "idle-cpu": 9.0,
            "wakeups": 99999,
            "backend-memory": 100.0,
            "ai-memory": 10.0,
        },
    )
    assert hb.main(["--seconds", "1", "--results", str(tmp_path / "r"), "--strict"]) == 0
    assert "SKIP idle-cpu" in capsys.readouterr().out


def test_the_backend_is_the_largest_backend_process(tmp_path):
    _proc(tmp_path, 5, "sh -c python3 -m backend.main", 0, 0, 2 * 1024)
    _proc(tmp_path, 6, "python3 -m backend.main", 0, 0, 200 * 1024)
    _proc(tmp_path, 7, "python3 -m backend.main --helper", 0, 0, 27 * 1024)
    assert hb.backend_pid(hb.processes(str(tmp_path)), str(tmp_path)) == "6"


def test_a_restart_during_the_soak_skips_the_backend_budgets(tmp_path, capsys, monkeypatch):
    import shutil

    _proc(tmp_path, 1, "python3 -m backend.main", 500, 9000, 180 * 1024)

    def restart(s):  # a deploy: the old process is gone, a new one starts
        shutil.rmtree(tmp_path / "1")
        _proc(tmp_path, 2, "python3 -m backend.main", 5, 10, 150 * 1024)

    monkeypatch.setattr(hb.os, "sysconf", lambda name: 100)
    state = {"t": 0.0}

    def sleep(s):
        if state["t"] == 0.0:
            restart(s)
        state["t"] += s

    values = hb.measure(60, proc=str(tmp_path), sleep=sleep, clock=lambda: state["t"])
    assert values["restarted"] is True
    assert hb.verdicts(values) == {
        "idle-cpu": None,
        "wakeups": None,
        "spawns": None,
        "backend-memory": None,
        "ai-memory": True,
    }
    monkeypatch.setattr(hb, "measure", lambda seconds, **k: values)
    assert hb.main(["--seconds", "1", "--results", str(tmp_path / "r"), "--strict"]) == 0
    assert "SKIP backend-memory (the backend restarted during the soak)" in capsys.readouterr().out


def _cg(root, pid, text):
    (root / str(pid) / "cgroup").write_text(text + "\n")


def _set(root, pid, ticks, switches, start="5", ppid="1"):
    fields = ["S", ppid] + ["0"] * 9 + [str(ticks), "0"] + ["0"] * 6 + [start] + ["0"] * 23
    (root / str(pid) / "stat").write_text(f"{pid} (python3) " + " ".join(fields))
    (root / str(pid) / "task" / str(pid) / "status").write_text(
        f"voluntary_ctxt_switches:\t{switches}\nnonvoluntary_ctxt_switches:\t999\n"
    )


def test_the_whole_container_counts_and_new_processes_are_spawns(tmp_path, monkeypatch):
    import shutil

    _proc(tmp_path, 10, "python3 -m backend.main", 0, 0, 100 * 1024)
    _proc(tmp_path, 11, "python3 helper", 0, 0, 1024)
    _proc(tmp_path, 20, "/usr/bin/other-container", 0, 0, 1024)
    for pid in (10, 11):
        _cg(tmp_path, pid, "0::/docker/app")
        _set(tmp_path, pid, 100, 1000)
    _cg(tmp_path, 20, "0::/docker/else")
    _set(tmp_path, 20, 100, 1000)
    state = {"t": 0.0}

    def sleep(s):
        state["t"] += s
        n = int(state["t"])
        _set(tmp_path, 10, 100 + n, 1000 + 10 * n)
        _set(tmp_path, 20, 100 + 50 * n, 1000 + 500 * n)  # another container: never counted
        if n == 10:  # a tool the app starts lives for a few seconds
            _proc(tmp_path, 30, "smartctl -n standby", 0, 0, 1024)
            _cg(tmp_path, 30, "0::/docker/app")
        if 10 <= n < 13:
            _set(tmp_path, 30, 2 * (n - 9), 5 * (n - 9), start="900")
        if n == 13:
            shutil.rmtree(tmp_path / "30")

    monkeypatch.setattr(hb.os, "sysconf", lambda name: 100)
    v = hb.measure(60, proc=str(tmp_path), sleep=sleep, clock=lambda: state["t"])
    assert v["spawns"] == 1.0
    assert v["processes"] == 3
    assert v["idle-cpu"] == round(100 * (60 + 6) / 100 / 60, 2)  # backend + the tool, not the neighbour
    assert v["wakeups"] == 600 + 15  # voluntary only
    assert v["restarted"] is False


def test_tree_scope_follows_children_only(tmp_path, monkeypatch):
    _proc(tmp_path, 40, "python3 -m backend.main", 0, 0, 1024)
    _proc(tmp_path, 41, "child", 0, 0, 1024)
    _proc(tmp_path, 42, "runner", 0, 0, 1024)
    _set(tmp_path, 40, 0, 0, start="1", ppid="1")
    _set(tmp_path, 41, 0, 0, start="2", ppid="40")
    _set(tmp_path, 42, 0, 0, start="3", ppid="1")
    state = {"t": 0.0}

    def sleep(s):
        state["t"] += s
        _set(tmp_path, 41, int(state["t"]), 0, start="2", ppid="40")
        _set(tmp_path, 42, 100 * int(state["t"]), 0, start="3", ppid="1")

    monkeypatch.setattr(hb.os, "sysconf", lambda name: 100)
    v = hb.measure(10, proc=str(tmp_path), sleep=sleep, clock=lambda: state["t"], pid="40", scope="tree")
    assert v["processes"] == 2 and v["idle-cpu"] == 1.0  # the child: 10 ticks in 10 s; not the runner


def test_loopback_connections_are_not_viewers(tmp_path):
    net = tmp_path / "7" / "net"
    net.mkdir(parents=True)
    head = "  sl  local_address rem_address   st\n"
    (net / "tcp").write_text(
        head
        + "   0: 0100007F:1F92 0100007F:A000 01\n"  # the healthcheck
        + "   1: 040011AC:1F92 0A00000A:B000 01\n"  # a browser on the LAN
    )
    (net / "tcp6").write_text(
        head + "   0: 00000000000000000000000000000000:1F92 00000000000000000000000001000000:C000 01\n"
    )
    assert hb.viewers("7", proc=str(tmp_path), port=8082) == 1


def test_strict_can_name_the_budgets_that_gate(monkeypatch, tmp_path, capsys):
    values = {
        "restarted": False,
        "viewers": 0,
        "processes": 3,
        "idle-cpu": 5.0,
        "wakeups": 9000,
        "spawns": 2.0,
        "backend-memory": 1.0,
        "ai-memory": 0.0,
    }
    monkeypatch.setattr(hb, "measure", lambda seconds, **k: values)
    args = ["--seconds", "1", "--results", str(tmp_path), "--only", "spawns,wakeups,idle-cpu"]
    assert hb.main(args + ["--strict", "spawns"]) == 0  # the over-budget wakeups only warn
    assert hb.main(args + ["--strict"]) == 1
    out = capsys.readouterr().out
    assert "9000" not in out and "PASS spawns" in out and "FAIL wakeups" in out
    assert hb.main(args + ["--show"]) == 0
    assert "(9000 / " in capsys.readouterr().out
