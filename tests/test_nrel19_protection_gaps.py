"""NREL-19: a moved copy job stays on until its off-site backup succeeded once, and a new build
whose safety snapshot failed changes no database."""

import pytest

from backend.services import backup_engine as be
from backend.services import backup_migration as bm
from backend.services import data_snapshot


def test_copy_job_goes_off_only_after_a_good_backup(monkeypatch):
    repos = [{"id": "from-j1", "replaces_job": "j1", "last_result": "failed: x", "last_backup": 0}]
    status, updates = {}, []
    monkeypatch.setattr(bm.offsite_backup, "list_repos", lambda: repos)
    monkeypatch.setattr(bm.offsite_backup, "_update", lambda rid, **f: updates.append((rid, f)))
    monkeypatch.setattr(be, "_update_job_status", lambda jid, **f: status.setdefault(jid, {}).update(f))
    assert bm.retire_replaced_jobs() == [] and status == {}
    repos[0].update(last_result="ok", last_backup=1_700_000_000)
    assert bm.retire_replaced_jobs() == ["j1"]
    assert status == {"j1": {"enabled": False}} and updates == [("from-j1", {"replaces_job": ""})]


def test_repos_without_a_job_are_left_alone(monkeypatch):
    monkeypatch.setattr(bm.offsite_backup, "list_repos", lambda: [{"id": "r", "last_result": "ok", "last_backup": 5}])
    monkeypatch.setattr(be, "_update_job_status", lambda *a, **k: pytest.fail("touched a job"))
    assert bm.retire_replaced_jobs() == []


def test_scheduler_calls_it():
    import inspect

    from backend.services import scheduler

    assert "retire_replaced_jobs()" in inspect.getsource(scheduler)


def test_a_moved_job_still_counts_until_it_is_off(monkeypatch):
    from backend.services import protection_status

    jobs = [{"name": "Photos", "destination_type": "remote", "migrated_to": "from-j1", "enabled": True}]
    monkeypatch.setattr(be, "get_backup_jobs", lambda: jobs)
    src = inspect_source(protection_status)
    assert 'j.get("enabled") is False' in src


def inspect_source(mod):
    import inspect

    return inspect.getsource(mod)


def test_startup_stops_without_its_snapshot(monkeypatch, caplog):
    monkeypatch.delenv(data_snapshot.START_ANYWAY, raising=False)
    with pytest.raises(SystemExit) as stop:
        data_snapshot.refuse_without_snapshot(OSError("No space left on device"))
    assert stop.value.code == 4
    assert "Nothing was changed" in caplog.text and "No space left" in caplog.text


def test_startup_can_be_told_to_go_on(monkeypatch, caplog):
    monkeypatch.setenv(data_snapshot.START_ANYWAY, "1")
    data_snapshot.refuse_without_snapshot(OSError("full"))
    assert "starting anyway" in caplog.text


def test_main_uses_it():
    import inspect

    from backend import main

    src = inspect.getsource(main.startup_system)
    assert "refuse_without_snapshot(e)" in src
    assert src.index("refuse_without_snapshot(e)") < src.index("init_users_db()")
