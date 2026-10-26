"""The hardware runner's read-only checks: spin-down (PERF-2) and the AI eval on real servers (AI-16)."""

import hashlib
import os

from scripts import hardware_ai_eval as ai
from scripts import hardware_spindown as sd


def _proc(tmp_path, diskstats, backend_io=None):
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    (proc / "diskstats").write_text(diskstats)
    if backend_io is not None:
        p = proc / "123"
        p.mkdir(exist_ok=True)
        (p / "cmdline").write_bytes(b"python3\0-m\0backend.main\0")
        (p / "io").write_text(f"rchar: 9\nread_bytes: {backend_io}\nwrite_bytes: 0\n")
    return str(proc)


def test_only_whole_spinning_disks_count(tmp_path):
    for name, rot in (("sda", "1"), ("sdb", "1"), ("sdc", "0"), ("nvme0n1", "1"), ("loop0", "1"), ("md1", "1")):
        q = tmp_path / "block" / name / "queue"
        q.mkdir(parents=True)
        (q / "rotational").write_text(rot + "\n")
    assert sd.rotational_disks(str(tmp_path)) == ["sda", "sdb"]


def test_reads_the_kernel_counters(tmp_path):
    line = "   8       0 sda 10 0 400 5 20 0 600 7 0 9 12\n   8      16 sdb 1 0 8 0 0 0 0 0 0 0 0\n"
    proc = _proc(tmp_path, line, backend_io=4096)
    assert sd.disk_sectors(proc) == {"sda": 1000, "sdb": 8}
    pid = sd.backend_pid(proc)
    assert pid == "123" and sd.backend_io(pid, proc) == 4096
    assert sd.backend_io(None, proc) is None


def test_a_wake_needs_a_long_idle_stretch_and_backend_io():
    m = 60.0
    samples = [
        (0 * m, {"sda": 0, "sdb": 0}, 100),
        (5 * m, {"sda": 0, "sdb": 0}, 100),
        (11 * m, {"sda": 0, "sdb": 0}, 100),  # both idle 11 minutes
        (12 * m, {"sda": 50, "sdb": 0}, 200),  # sda wakes while the backend did storage I/O
        (13 * m, {"sda": 60, "sdb": 0}, 200),  # busy again, but not after a long idle stretch
        (25 * m, {"sda": 60, "sdb": 9}, 200),  # sdb wakes, the backend did nothing: not counted
    ]
    report = sd.analyse(samples, ["sda", "sdb"], 60, 10 * m)
    assert report["sda"] == {"longest_idle_min": 12.0, "busy_intervals": 2, "wakes": 1}
    assert report["sdb"] == {"longest_idle_min": 13.0, "busy_intervals": 1, "wakes": 0}


def test_spindown_reports_pass_fail_or_skip_only(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sd, "measure", lambda minutes, interval: ([], "1", []))
    assert sd.main(["--minutes", "0", "--results", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "SKIP spindown (no spinning disks visible)"
    samples = [(0.0, {"sda": 0}, 1), (700.0, {"sda": 0}, 1), (760.0, {"sda": 5}, 2)]
    monkeypatch.setattr(sd, "measure", lambda minutes, interval: (["sda"], "1", samples))
    sd.main(["--minutes", "0", "--results", str(tmp_path)])
    out = capsys.readouterr().out
    assert out.startswith("FAIL spindown") and "sda" not in out  # numbers and disk names stay in the file
    assert os.listdir(tmp_path / "spindown")


def test_the_ai_check_runs_only_on_the_packages_of_this_lock(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("fastapi==1\n")
    rec = tmp_path / "lock.sha256"
    rec.write_text(hashlib.sha256(b"fastapi==1\n").hexdigest() + "\n")
    assert ai.lock_matches(str(lock), str(rec))
    lock.write_text("fastapi==2\n")
    assert not ai.lock_matches(str(lock), str(rec))
    assert not ai.lock_matches(str(lock), str(tmp_path / "missing"))


def test_the_ai_check_records_then_compares():
    now = {
        "model": "embeddinggemma-2-ov",
        "overall": {"recall@1": 0.8, "recall@5": 0.9, "mrr@10": 0.85},
        "answers": {"model": "Qwen3-4B", "accuracy": 0.8},
    }
    assert ai.verdict(now, None, "Qwen3-4B", 0.03) == ("RECORDED", [])
    other = {**now, "answers": {"model": "llama3.2", "accuracy": 0.9}}
    assert ai.verdict(now, other, "Qwen3-4B", 0.03)[0] == "RECORDED"  # another chat model: a new baseline
    assert ai.verdict(now, now, "Qwen3-4B", 0.03) == ("PASS", [])
    better_base = {**now, "overall": {"recall@1": 0.9, "recall@5": 0.95, "mrr@10": 0.9}}
    state, reasons = ai.verdict(now, better_base, "Qwen3-4B", 0.03)
    assert state == "FAIL" and reasons
    assert "wrong" not in ai.scores({**now, "answers": {**now["answers"], "wrong": [1]}})["answers"]


def test_the_ai_check_skips_when_the_image_is_behind(monkeypatch, capsys):
    monkeypatch.setattr(ai, "lock_matches", lambda path: False)
    assert ai.main([]) == 0
    assert capsys.readouterr().out.startswith("SKIP ai-eval")


def test_spindown_watches_the_largest_backend_process(tmp_path):
    proc = tmp_path / "proc"
    for pid, rss in (("10", 2000), ("11", 200000), ("12", 27000)):
        d = proc / pid
        d.mkdir(parents=True)
        (d / "cmdline").write_bytes(b"python3\0-m\0backend.main\0")
        (d / "status").write_text(f"VmRSS:\t{rss} kB\n")
    assert sd.backend_pid(str(proc)) == "11"
