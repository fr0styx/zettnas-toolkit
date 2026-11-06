"""One job list for long-running work, with history and cancel (ARCH-4, ARCH-5)."""

import pytest

from backend.services import jobs


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "HISTORY_FILE", str(tmp_path / "jobs_history.json"))
    monkeypatch.setattr(jobs, "CLEARED_FILE", str(tmp_path / "jobs_cleared.json"))
    monkeypatch.setattr(jobs, "SOURCES", {})
    return jobs.JobManager()


def test_registered_jobs_progress_finish_and_are_remembered(manager, tmp_path):
    cancelled = []
    job = manager.register("thumbnails", "Making thumbnails", owner="eve", cancel=lambda: cancelled.append(1))
    manager.update(job.id, percent=40.0, detail="photo_12.jpg")
    active = manager.list(owner="eve")["active"]
    assert active[0]["percent"] == 40.0 and active[0]["can_cancel"]
    assert manager.list(owner="mallory")["active"] == []  # other people don't see it
    assert manager.cancel(job.id, owner="mallory") is False
    assert manager.cancel(job.id, owner="eve") is True and cancelled == [1]
    manager.finish(job.id, "cancelled")
    fresh = jobs.JobManager()  # history survives a restart
    hist = fresh.list(owner="eve")["history"]
    assert hist[0]["id"] == job.id and hist[0]["status"] == "cancelled"


def test_sources_are_listed_and_cancelled_through_their_engine(manager, monkeypatch):
    calls = []
    running = [jobs.Job(id="transfer:t1", kind="transfer", title="Copy 2 item(s)", owner="eve", can_cancel=True)]
    monkeypatch.setitem(jobs.SOURCES, "transfer", (lambda: running, lambda tid: calls.append(tid) or True))
    monkeypatch.setitem(
        jobs.SOURCES, "reindex", (lambda: [jobs.Job(id="reindex:ai", kind="ai_reindex", title="x")], None)
    )
    eve = manager.list(owner="eve")["active"]
    assert [j["id"] for j in eve] == ["transfer:t1"]  # the system job is for admins
    assert {j["id"] for j in manager.list(everyone=True)["active"]} == {"transfer:t1", "reindex:ai"}
    assert manager.cancel("transfer:t1", owner="eve") and calls == ["t1"]
    assert manager.cancel("reindex:ai", everyone=True) is False  # not cancellable


def test_api_lists_and_cancels(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "HISTORY_FILE", str(tmp_path / "h.json"))
    monkeypatch.setattr(jobs, "SOURCES", {})
    job = jobs.job_manager.register("demo", "Demo job", owner=None, cancel=lambda: None)
    try:
        body = client.get("/api/jobs", headers=auth_headers).json()
        assert any(j["id"] == job.id for j in body["active"])
        assert client.post(f"/api/jobs/{job.id}/cancel", headers=auth_headers).status_code == 200
        assert client.post("/api/jobs/job:nope/cancel", headers=auth_headers).status_code == 404
    finally:
        jobs.job_manager.finish(job.id, "cancelled")


def test_every_real_source_adapter_runs():
    for name, (lister, _cancel) in jobs.SOURCES.items():
        assert isinstance(lister(), list), name


def test_finished_jobs_can_be_cleared_and_stay_cleared(manager, monkeypatch):
    for who in ("eve", "bob"):
        job = manager.register("thumbnails", "Making thumbnails", owner=who)
        manager.finish(job.id)
    done = [jobs.Job(id="thumbs:pass", kind="thumbnails", title="Thumbnails", status="done", owner="eve")]
    monkeypatch.setitem(jobs.SOURCES, "thumbs", (lambda: done, None))
    running = manager.register("transfer", "Copy", owner="eve")
    assert len(manager.list(owner="eve")["history"]) == 2
    assert manager.clear_history(owner="eve") == 2
    assert manager.list(owner="eve")["history"] == []  # the source's finished pass doesn't come back
    assert [j["id"] for j in manager.list(owner="eve")["active"]] == [running.id]  # running jobs stay
    assert len(manager.list(owner="bob")["history"]) == 1  # someone else's is theirs to clear
    assert manager.clear_history(owner="eve") == 0
    assert manager.clear_history(everyone=True) == 1 and manager.list(everyone=True)["history"] == []
    assert jobs.JobManager().list(everyone=True)["history"] == []  # cleared on disk, and after a restart


def test_api_clears_the_history(client, auth_headers, tmp_path, monkeypatch):
    m = jobs.JobManager()
    monkeypatch.setattr(jobs, "HISTORY_FILE", str(tmp_path / "h.json"))
    monkeypatch.setattr(jobs, "CLEARED_FILE", str(tmp_path / "c.json"))
    monkeypatch.setattr(jobs, "SOURCES", {})  # only this test's job
    from backend.api import jobs as jobs_api

    monkeypatch.setattr(jobs_api, "job_manager", m)
    m.finish(m.register("backup", "Backup", owner="admin").id)
    r = client.post("/api/jobs/history/clear", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"cleared": 1}
    assert client.get("/api/jobs", headers=auth_headers).json()["history"] == []
