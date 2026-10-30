"""NPERF-1: every process the backend starts is counted, by who started it."""

import asyncio
import subprocess
import sys

from backend import proc, spawns


def test_runs_popen_and_asyncio_are_all_counted(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", spawns.CountedPopen)
    before = spawns.counts().get(__name__, 0)
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    proc.run_bounded([sys.executable, "-c", "pass"], timeout=30)
    with subprocess.Popen([sys.executable, "-c", "pass"]) as p:
        p.wait()

    async def go():
        p = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        await p.wait()

    asyncio.run(go())
    assert spawns.counts()[__name__] - before == 4
    assert spawns.total() >= 4
    text = spawns.prometheus()
    assert "# TYPE zettnas_process_spawns_total counter" in text
    assert f'zettnas_process_spawns_total{{caller="{__name__}"}}' in text


def test_install_wraps_popen(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", spawns._ORIGINAL)
    spawns.install()
    spawns.install()
    assert subprocess.Popen is spawns.CountedPopen
    assert issubclass(spawns.CountedPopen, spawns._ORIGINAL)


def test_metrics_show_them(client, auth_headers):
    spawns.note("backend.hardware.example")
    r = client.get("/api/metrics", headers=auth_headers)
    assert 'zettnas_process_spawns_total{caller="backend.hardware.example"}' in r.text


def test_the_app_installs_it():
    import inspect

    from backend import main

    assert "spawns.install()" in inspect.getsource(main.lifespan)


# --- the hardware budget check uses them ---------------------------------------------------------

import os  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import hardware_budgets as hb  # noqa: E402


def test_the_counter_is_read_from_metrics():
    text = 'zettnas_process_spawns_total{caller="a"} 3\nzettnas_process_spawns_total{caller="b"} 4.0\nother 9\n'
    assert hb.counted_spawns("http://x/api/metrics", "t", fetch=lambda u, t: text) == 7
    assert hb.counted_spawns("http://x", "t", fetch=lambda u, t: "nothing\n") is None
    assert hb.counted_spawns("", "t") is None

    def down(u, t):
        raise OSError("refused")

    assert hb.counted_spawns("http://x", "t", fetch=down) is None


def test_child_cpu_counts(tmp_path):
    d = tmp_path / "7"
    d.mkdir()
    fields = ["S"] + ["0"] * 10 + ["10", "5", "30", "15"] + ["0"] * 30
    (d / "stat").write_text("7 (python3) " + " ".join(fields))
    assert hb.cpu_ticks("7", str(tmp_path)) == 60


def test_measure_prefers_the_counter(tmp_path, monkeypatch):
    d = tmp_path / "1"
    (d / "task" / "1").mkdir(parents=True)
    (d / "cmdline").write_bytes(b"python3\0-m\0backend.main")
    (d / "stat").write_text("1 (python3) " + " ".join(["S"] + ["0"] * 40))
    (d / "status").write_text("VmRSS:\t1024 kB\n")
    (d / "task" / "1" / "status").write_text("voluntary_ctxt_switches:\t0\n")
    monkeypatch.setattr(hb.os, "sysconf", lambda name: 100)
    state = {"t": 0.0}
    seq = iter([100, 112])
    values = hb.measure(
        60,
        proc=str(tmp_path),
        sleep=lambda s: state.__setitem__("t", state["t"] + s),
        clock=lambda: state["t"],
        spawn_count=lambda: next(seq),
    )
    assert values["spawns"] == 12.0 and values["spawns_counted"] is True
    values = hb.measure(
        60,
        proc=str(tmp_path),
        sleep=lambda s: state.__setitem__("t", state["t"] + s),
        clock=lambda: state["t"],
        spawn_count=lambda: None,
    )
    assert values["spawns"] == 0.0 and values["spawns_counted"] is False
