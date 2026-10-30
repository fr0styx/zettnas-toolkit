"""B23's error paths: what an update would cut off, pauses and power-cut lists that can't be
written, a stalled-service check that fails (NREL-10, NREL-14, NREL-17, NREL-18)."""

import threading

import pytest

from backend.services import app_backup, protection_jobs, ups_watchdog


def test_busy_work_lists_jobs_and_open_folders(monkeypatch):
    monkeypatch.undo()  # conftest stubs it for the update tests
    from backend.api import system
    from backend.services import encrypted_folders
    from backend.services.jobs import job_manager

    monkeypatch.setattr(job_manager, "list", lambda everyone=False: {"active": [{"title": "Backup"}, {"kind": "copy"}]})
    monkeypatch.setattr(
        encrypted_folders,
        "listing",
        lambda: [
            {"name": "tax", "unlocked": True, "unlock_at_start": False},
            {"name": "auto", "unlocked": True, "unlock_at_start": True},
            {"name": "shut", "unlocked": False, "unlock_at_start": False},
        ],
    )
    assert system.busy_work() == ["Backup", "copy", "the encrypted folder tax (it will be locked)"]

    def broken():
        raise OSError("no mounts")

    monkeypatch.setattr(encrypted_folders, "listing", broken)
    assert system.busy_work() == ["Backup", "copy"]


def _locked_fails(*a, **k):
    raise OSError("read-only")


def test_a_pause_that_cant_be_written_still_pauses(monkeypatch):
    monkeypatch.setattr("backend.fsutil.locked_json", _locked_fails)
    assert app_backup._mark_paused("containers", "c1") is True
    app_backup._unmark_paused("containers", "c1")  # logs, doesn't raise


def test_resume_goes_on_past_failures(tmp_path, monkeypatch):
    import json

    path = tmp_path / "paused.json"
    path.write_text(json.dumps({"containers": ["c1"], "vms": ["vm1"]}))
    monkeypatch.setattr(app_backup, "_paused_file", lambda: str(path))

    def no_docker(cid):
        raise RuntimeError("docker down")

    def no_vm(vm):
        raise OSError("no libvirt")

    monkeypatch.setattr(app_backup, "_unpause_container", no_docker)
    monkeypatch.setattr(app_backup, "_resume_vm", no_vm)
    assert app_backup.resume_left_paused() == []


def test_power_cut_list_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(ups_watchdog, "_stopped_file", lambda: str(tmp_path / "x" / "stopped.json"))

    def unwritable(*a, **k):
        raise OSError("full")

    monkeypatch.setattr("backend.fsutil.atomic_write_json", unwritable)
    ups_watchdog._remember_stopped(["immich"])  # logs, doesn't raise
    ups_watchdog._remember_stopped([])
    monkeypatch.undo()

    import json

    path = tmp_path / "stopped.json"
    path.write_text(json.dumps({"apps": ["immich", "gone"]}))
    monkeypatch.setattr(ups_watchdog, "_stopped_file", lambda: str(path))

    def action(name, what):
        if name == "gone":
            raise RuntimeError("no such container")
        return {"success": True}

    monkeypatch.setattr("backend.hardware.docker_stats.container_action", action)
    monkeypatch.setattr(ups_watchdog, "add_event", lambda *a: None)
    real_remove = ups_watchdog.os.remove

    def remove(p):
        real_remove(p)
        raise OSError("already gone")

    monkeypatch.setattr(ups_watchdog.os, "remove", remove)
    assert ups_watchdog.restart_stopped_apps() == ["immich"]


class _Once(threading.Event):
    def wait(self, timeout=None):
        return True


def test_the_watch_loop_survives_a_failing_stalled_check(monkeypatch):
    from backend.services import backup_watch

    calls = []
    monkeypatch.setattr(backup_watch, "check_and_alert", lambda now: calls.append("backup"))
    monkeypatch.setattr(protection_jobs, "check_and_alert", lambda now: calls.append("protection"))

    def broken(now):
        calls.append("stalled")
        raise ValueError("bad status")

    monkeypatch.setattr(protection_jobs, "alert_stalled", broken)
    protection_jobs.watch_daemon(stop=_Once(), tick=0)
    assert calls == ["backup", "protection", "stalled"]


def test_stalled_alerts_use_the_notifier(monkeypatch):
    sent = []
    monkeypatch.setattr("backend.services.supervisor.stalled", lambda: ["Scheduler"])
    monkeypatch.setattr("backend.services.notifications.send_notification", lambda *a, **k: sent.append(k["dedup_key"]))
    assert protection_jobs.alert_stalled(1793500000.0) == ["Scheduler"]
    assert sent and sent[0].startswith("stalled-Scheduler-")


@pytest.mark.parametrize("names", [[]])
def test_nothing_stalled(monkeypatch, names):
    monkeypatch.setattr("backend.services.supervisor.stalled", lambda: names)
    assert protection_jobs.alert_stalled() == []
