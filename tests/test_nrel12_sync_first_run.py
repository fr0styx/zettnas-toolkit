"""NREL-12: a first two-way sync run lets the newer copy win on both sides before bisync --resync."""

import subprocess

from backend.services import two_way_sync as tws

PAIR = {"id": "p", "local": "/mnt/user/Docs", "remote": "gdrive:docs", "baseline": False, "max_delete": 25}


def test_a_first_run_copies_newer_files_both_ways_first():
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert tws._run(dict(PAIR), False, run)["ok"]
    assert calls[0][:4] == ["rclone", "copy", "/mnt/user/Docs", "gdrive:docs"] and "--update" in calls[0]
    assert calls[1][:4] == ["rclone", "copy", "gdrive:docs", "/mnt/user/Docs"] and "--update" in calls[1]
    assert calls[2][:2] == ["rclone", "bisync"] and "--resync" in calls[2]
    assert all("--delete" not in " ".join(c) for c in calls[:2])


def test_a_failed_copy_stops_the_run():
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "ERROR : quota exceeded")

    out = tws._run(dict(PAIR), False, run)
    assert not out["ok"] and "quota exceeded" in out["error"] and len(calls) == 1


def test_previews_and_later_runs_dont_copy_first():
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    tws._run(dict(PAIR), True, run)
    tws._run({**PAIR, "baseline": True}, False, run)
    assert [c[1] for c in calls] == ["bisync", "bisync"]
