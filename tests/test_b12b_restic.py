"""B12b (REL-16): restic with one host name across updates, unreadable files as a warning, stale
locks cleared first, backups and restores as jobs with progress, a random-file drill compared by
checksum, and a warning for a backup on the same storage as its folders."""

import json
import os
import shutil
import threading
import time

import pytest

from backend import config
from backend.services import offsite_backup as ob
from backend.services.jobs import job_manager

FAKE_RESTIC = r"""#!/bin/sh
echo "$@" >> "$FAKE_RESTIC_LOG"
case "$1" in
  unlock)
    if [ -n "$FAKE_UNLOCK_FAIL" ]; then echo "Fatal: repository is busy" >&2; exit 1; fi ;;
  backup)
    echo '{"message_type":"status","percent_done":0.5,"total_files":4,"files_done":2}'
    echo '{"message_type":"error","error":{"message":"open /x/locked: permission denied"},"during":"archival","item":"/x/locked"}'
    echo '{"message_type":"summary","files_new":3,"files_changed":0,"data_added":10,"snapshot_id":"abcdef123456"}'
    exit "${FAKE_BACKUP_EXIT:-0}" ;;
  restore)
    echo '{"message_type":"status","percent_done":0.25,"total_files":4,"files_restored":1}'
    echo 'not json'
    echo '{"message_type":"summary","total_files":4,"files_restored":4}'
    exit "${FAKE_RESTORE_EXIT:-0}" ;;
  slow)
    exec sleep 5 ;;
esac
exit 0
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    (storage / "family").mkdir(parents=True)
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(storage)])
    monkeypatch.setattr(ob, "REPOS_FILE", str(tmp_path / "repos.json"))
    monkeypatch.setattr(ob, "KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    return storage


@pytest.fixture
def fake(env, tmp_path, monkeypatch):
    """A stand-in restic on PATH that logs its arguments and answers like restic does."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "restic"
    script.write_text(FAKE_RESTIC)
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '')}")
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_RESTIC_LOG", str(log))
    ob.save_repo("usb", "USB", str(env / "usb"), [str(env / "family")], hour=None)

    def calls():
        return [line.split() for line in log.read_text().splitlines()] if log.exists() else []

    return calls


@pytest.fixture
def jobs(monkeypatch):
    seen = {"update": [], "finish": []}
    update, finish = job_manager.update, job_manager.finish

    def _update(job_id, **fields):
        seen["update"].append(fields)
        update(job_id, **fields)

    def _finish(job_id, status="done", error=None):
        seen["finish"].append(status)
        finish(job_id, status, error)

    monkeypatch.setattr(job_manager, "update", _update)
    monkeypatch.setattr(job_manager, "finish", _finish)
    return seen


def _idle(repo_id="usb"):
    for _ in range(100):
        if repo_id not in ob._BUSY:
            return True
        time.sleep(0.05)
    return False


def test_unreadable_files_leave_a_backup_and_a_warning(fake, jobs, monkeypatch):
    monkeypatch.setenv("FAKE_BACKUP_EXIT", "3")
    res = ob.backup("usb")
    assert res["files_new"] == 3 and res["unreadable"] == 1 and res["unreadable_files"] == ["/x/locked"]
    repo = ob.get_repo("usb")
    assert repo["last_result"] == "ok" and repo["last_unreadable"] == 1
    assert {"percent": 50.0, "detail": "2 of 4 files"} in jobs["update"]
    assert {"detail": "1 files could not be read"} in jobs["update"] and jobs["finish"][-1] == "done"
    order = [c[0] for c in fake()]
    assert order.index("unlock") < order.index("backup") < order.index("forget")


def test_other_failures_still_fail(fake, monkeypatch):
    monkeypatch.setenv("FAKE_BACKUP_EXIT", "1")
    with pytest.raises(ob.ResticError):
        ob.backup("usb")
    assert ob.get_repo("usb")["last_result"].startswith("failed")


def test_backups_keep_one_host_name_and_prune_across_old_ones(fake):
    ob.backup("usb")
    backup = next(c for c in fake() if c[0] == "backup")
    assert backup[backup.index("--host") + 1] == ob.host_id()
    forget = next(c for c in fake() if c[0] == "forget")
    assert forget[forget.index("--group-by") + 1] == "paths,tags"


def test_the_host_name_survives_restarts(env, tmp_path):
    first = ob.host_id()
    assert ob._HOST.match(first) and ob.host_id() == first
    (tmp_path / "offsite_host").write_text("garbage\n")
    assert ob._HOST.match(ob.host_id()) and ob.host_id() != "garbage"


def test_a_failed_unlock_does_not_stop_the_backup(fake, monkeypatch):
    monkeypatch.setenv("FAKE_UNLOCK_FAIL", "1")
    assert ob.backup("usb")["files_new"] == 3
    assert ob.check("usb")["ok"]
    assert [c[0] for c in fake()].count("unlock") == 2


def test_a_backup_runs_as_a_job(fake, monkeypatch):
    gate, started = threading.Event(), threading.Event()

    def slow(repo_id, owner=None, job=None):
        started.set()
        gate.wait(5)
        job_manager.finish(job.id, "done")

    monkeypatch.setattr(ob, "backup", slow)
    res = ob.start_backup("usb", owner="admin")
    assert res["status"] == "started" and res["job"].startswith("job:")
    assert started.wait(5)
    with pytest.raises(ob.BusyError):
        ob.start_backup("usb")
    assert ob.run_due() == []  # the scheduler leaves a busy repository alone too
    gate.set()
    assert _idle()


def test_a_restore_runs_as_a_job_with_progress(fake, env, jobs):
    target = str(env / "restored")
    res = ob.start_restore("usb", "latest", str(env / "family" / "a.txt"), target, owner="admin")
    assert res["status"] == "started" and res["restored_to"].startswith(target)
    assert _idle()
    assert {"percent": 25.0, "detail": "1 of 4 files"} in jobs["update"] and jobs["finish"][-1] == "done"
    restore = next(c for c in fake() if c[0] == "restore")
    assert "--json" in restore and os.path.isdir(target)
    with pytest.raises(ValueError):
        ob.start_restore("usb", "latest", "/a", "/etc")


def test_a_failed_restore_job_says_so(fake, env, jobs, monkeypatch):
    monkeypatch.setenv("FAKE_RESTORE_EXIT", "1")
    ob.start_restore("usb", "latest", "/a", str(env / "restored"))
    assert _idle() and jobs["finish"][-1] == "error"


def test_a_restore_still_runs_in_place_when_asked(fake, env):
    assert ob.restore("usb", "latest", "/a", str(env / "r2"))["restored_to"].endswith("r2/a")


def test_a_hanging_run_is_stopped(fake):
    with pytest.raises(ob.ResticError, match="too long"):
        ob._run(ob.get_repo("usb"), ["slow"], timeout=1, on_line=lambda line: None)


def test_a_progress_line_it_cannot_read_is_skipped(fake):
    def bad(line):
        raise ValueError(line)

    code, out = ob._run(ob.get_repo("usb"), ["restore"], on_line=bad)
    assert code == 0 and '"summary"' in out and "percent_done" not in out


def test_a_backup_on_the_same_storage_is_flagged(env, monkeypatch):
    fam = str(env / "family")
    assert ob.same_disk(str(env / "backups" / "zettnas"), [fam])  # not made yet: its parent counts
    assert not ob.same_disk("/mnt/disks/usb/zettnas", [fam])
    assert not ob.same_disk("rclone:cloud:zettnas", [fam])
    assert ob.save_repo("local", "x", str(env / "backups"), [fam], hour=None)["same_disk"] is True
    assert {r["id"]: r for r in ob.list_repos()}["local"]["same_disk"] is True
    monkeypatch.setattr(ob, "_device", lambda p: 1 if "backups" in p else 2)
    assert not ob.same_disk(str(env / "backups"), [fam])


def test_the_drill_picks_among_all_small_files(monkeypatch):
    sizes = [10, 0, 10, 10**9, 10]
    out = "\n".join(
        [json.dumps({"struct_type": "node", "type": "file", "path": f"/f{i}", "size": s}) for i, s in enumerate(sizes)]
        + ["garbage", json.dumps({"struct_type": "node", "type": "dir", "path": "/d"})]
    )
    monkeypatch.setattr(ob.secrets, "randbelow", lambda n: 0 if n in (1, 2) else 1)
    assert ob._pick_file(out)["path"] == "/f2"
    assert ob._pick_file("") is None


def test_restic_times_are_read():
    assert ob._mtime("2026-10-27T10:00:00.123456789+01:00") == pytest.approx(1793091600.123456)
    assert ob._mtime("2026-10-27T09:00:00Z") == 1793091600.0
    assert ob._mtime("soon") is None
    assert not ob._unchanged("/no/such/file", {"mtime": "2026-10-27T09:00:00Z", "size": 1})


@pytest.mark.skipif(shutil.which("restic") is None, reason="restic is not installed")
def test_the_drill_compares_the_restored_file_by_checksum(env, monkeypatch):
    fam = env / "family"
    for name, text in (("a.txt", "alpha"), ("b.txt", "beta")):
        (fam / name).write_text(text)
    ob.save_repo("usb", "USB", str(env / "usb"), [str(fam)], hour=None)
    ob.backup("usb")
    res = ob.drill("usb")
    assert res["ok"] and res["verified"] == "sha256" and len(res["sha256"]) == 64
    assert ob.get_repo("usb")["last_drill_verified"] == "sha256"
    with monkeypatch.context() as m:
        m.setattr(ob, "_sha256", lambda p: "restored" if "zettnas-drill-" in p else "original")
        with pytest.raises(ob.ResticError, match="differs"):
            ob.drill("usb")
    for name in ("a.txt", "b.txt"):
        os.utime(fam / name, (1, 1))  # changed since the backup: only the size can be compared
    assert ob.drill("usb")["verified"] == "size"


def test_the_routes_start_jobs(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ob, "start_backup", lambda rid, owner=None: {"status": "started", "job": "job:1"})
    assert client.post("/api/offsite/repos/usb/backup", headers=auth_headers).json()["job"] == "job:1"

    def busy(*a, **k):
        raise ob.BusyError("already running")

    monkeypatch.setattr(ob, "start_backup", busy)
    assert client.post("/api/offsite/repos/usb/backup", headers=auth_headers).status_code == 409
    monkeypatch.setattr(
        ob, "start_restore", lambda rid, sid, path, target, owner=None: {"status": "started", "job": "job:2"}
    )
    body = {"path": "/mnt/user/a.txt", "target": "/mnt/user/restored"}
    res = client.post("/api/offsite/repos/usb/snapshots/latest/restore", json=body, headers=auth_headers)
    assert res.json()["job"] == "job:2"
