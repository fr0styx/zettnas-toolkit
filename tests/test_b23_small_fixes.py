"""NSEC-8: a restore goes back only inside the share its Recycle Bin belongs to."""

import os
from types import SimpleNamespace

import pytest

from backend.api.files import trash


@pytest.fixture
def bin_with(tmp_path, monkeypatch):
    share = tmp_path / "Family"
    b = share / ".RecycleBin"
    (b / "files").mkdir(parents=True)
    (b / "info").mkdir()
    (b / "files" / "1700000000_note.txt").write_text("hi")
    other = tmp_path / "Other"
    other.mkdir()

    def write_info(path):
        (b / "info" / "1700000000_note.txt.trashinfo").write_text(f"[Trash Info]\nPath={path}\n")

    monkeypatch.setattr(trash.recycle_bin, "locate", lambda item: (str(b), "1700000000_note.txt"))
    monkeypatch.setattr(trash, "_is_files_admin", lambda p: True)
    monkeypatch.setattr(trash, "_contained", lambda p, must_exist=False: p)
    monkeypatch.setattr(trash, "check_user_path_access", lambda *a, **k: None)
    return SimpleNamespace(share=share, other=other, write_info=write_info)


def test_a_forged_trashinfo_cant_send_a_file_elsewhere(bin_with):
    bin_with.write_info(str(bin_with.other / "planted.txt"))
    out = trash._restore(SimpleNamespace(item_id="x", target_path=""), SimpleNamespace())
    assert os.path.dirname(out["path"]) == str(bin_with.share)
    assert not (bin_with.other / "planted.txt").exists()


def test_a_real_trashinfo_restores_in_place(bin_with):
    (bin_with.share / "docs").mkdir()
    bin_with.write_info(str(bin_with.share / "docs" / "note.txt"))
    out = trash._restore(SimpleNamespace(item_id="x", target_path=""), SimpleNamespace())
    assert out["path"] == str(bin_with.share / "docs" / "note.txt")


def test_the_code_step_checks_the_account_lockout(client, monkeypatch):
    """NSEC-14: the 2FA code step refuses while the account is locked, like the password step."""
    from backend.api import auth

    monkeypatch.setattr(auth, "verify_mfa_token", lambda t: {"u": "mia", "uid": "u1"})
    monkeypatch.setattr(auth, "_lockout_remaining", lambda key: 300 if key == "account:mia" else 0)
    r = client.post("/api/auth/mfa/challenge", json={"mfa_token": "mfa_x", "mfa_code": "123456"})
    assert r.status_code == 429


def test_snapshot_names_are_utc():
    """NREL-15: one name per moment, whatever the clock change or the server\x27s zone."""
    from backend.services import snapshot_service as ss

    t = 1793500000.0
    assert ss.snapshot_name("Family", t) == "Family@auto-" + __import__("time").strftime(
        "%Y%m%d-%H%M", __import__("time").gmtime(t)
    )


def test_a_stalled_service_is_alerted_once_a_day(monkeypatch):
    """NREL-18: a stuck background service sends an alert, not only an Overview line."""
    from backend.services import protection_jobs

    sent = []
    monkeypatch.setattr("backend.services.supervisor.stalled", lambda: ["TaskScheduler"])
    names = protection_jobs.alert_stalled(1793500000.0, send=lambda *a, **k: sent.append((a[0], k["dedup_key"])))
    assert names == ["TaskScheduler"] and "TaskScheduler" in sent[0][0]
    assert sent[0][1].startswith("stalled-TaskScheduler-")  # one a day: the dedup key carries the date
    monkeypatch.setattr("backend.services.supervisor.stalled", lambda: [])
    assert protection_jobs.alert_stalled(1793500000.0, send=lambda *a, **k: sent.append(a)) == []


def test_apps_stopped_for_a_power_cut_come_back(tmp_path, monkeypatch):
    """NREL-10: what ZettNAS stopped for the UPS is started again, once."""
    from backend.services import ups_watchdog

    monkeypatch.setattr(ups_watchdog, "_stopped_file", lambda: str(tmp_path / "ups_stopped_apps.json"))
    started = []
    monkeypatch.setattr(
        "backend.hardware.docker_stats.container_action",
        lambda name, act: started.append((name, act)) or {"success": True},
    )
    monkeypatch.setattr(ups_watchdog, "add_event", lambda *a, **k: None)
    ups_watchdog._remember_stopped(["immich", "paperless", "immich"])
    assert ups_watchdog.restart_stopped_apps() == ["immich", "paperless"]
    assert started == [("immich", "start"), ("paperless", "start")]
    assert ups_watchdog.restart_stopped_apps() == []  # once


def test_what_a_backup_paused_is_resumed_after_a_restart(tmp_path, monkeypatch):
    """NREL-17: a restart in the middle of an app or VM backup doesn\x27t leave it frozen."""
    from backend.services import app_backup

    monkeypatch.setattr(app_backup, "_paused_file", lambda: str(tmp_path / "paused.json"))
    calls = []
    monkeypatch.setattr(app_backup, "_docker_request", lambda m, p, **k: calls.append(p) or (204, {}))
    monkeypatch.setattr(app_backup, "_resume_vm", lambda vm: calls.append(f"vm:{vm}"))
    app_backup._mark_paused("containers", "c1")
    app_backup._mark_paused("vms", "vm1")
    assert app_backup.resume_left_paused() == ["c1", "vm1"]
    assert calls == ["/containers/c1/unpause", "vm:vm1"]
    calls.clear()
    assert app_backup.resume_left_paused() == ["vm1"]  # the fake resume doesn\x27t clear; the real one does


def test_an_update_waits_for_running_work(client, auth_headers, monkeypatch):
    """NREL-14: an update says what it would cut off, and goes on only when asked to anyway."""
    from backend.api import system

    monkeypatch.setattr(system, "busy_work", lambda: ["Offsite backup: Photos"])
    r = client.post("/api/system/updates/apply", headers={**auth_headers, "X-Confirm": "1"}, json={"channel": "stable"})
    assert r.status_code in (409, 428)
    if r.status_code == 409:
        assert r.json()["error"] == "busy_jobs" and "Offsite backup: Photos" in r.json()["detail"]
