"""NJOB-2: more background work in the Jobs centre: Docker clean-up, AI model and VM installer
downloads, app installs, drive self-tests, parity checks and the mover, storage checks,
replication, and the idle-time photo captions and photo search vectors."""

import pytest

from backend.services import jobs, jobs_more
from backend.services.jobs import PassReport, follow, job_manager

NEW = ("prune", "model", "iso", "smart", "storage")


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "HISTORY_FILE", str(tmp_path / "jobs_history.json"))
    monkeypatch.setattr(job_manager, "_history", [])
    monkeypatch.setattr(job_manager, "_history_loaded", True)
    monkeypatch.setattr(job_manager, "_jobs", {})
    monkeypatch.setattr(jobs, "SOURCES", {k: v for k, v in jobs.SOURCES.items() if k in NEW})
    # what other tests left behind in the engines these sources read
    from backend.services import docker_cleanup, model_installer, vm_store
    from backend.state import Z_STATE

    monkeypatch.setattr(docker_cleanup, "_PRUNE_JOBS", {})
    monkeypatch.setattr(model_installer, "_JOBS", {})
    monkeypatch.setattr(vm_store, "_DOWNLOAD_TASKS", {})
    monkeypatch.setattr(Z_STATE.smart, "active_tests", {})
    # nothing from the machine the tests run on: each test turns on what it is about
    from backend.hardware import pal_storage
    from backend.hardware.pal.base import PlatformType

    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: _Adapter(PlatformType.GENERIC_LINUX))


def _active(kind):
    return [j for j in job_manager.list(everyone=True)["active"] if j["kind"] == kind]


def test_the_api_adds_the_sources_and_sends_the_title_key():
    from backend.api import jobs as api

    assert all(k in jobs.SOURCES for k in NEW)
    fields = api.JobOut.model_fields
    assert "title_id" in fields and "title_params" in fields  # the page translates the title (NUX-3)


def test_docker_cleanup_shows_with_progress_and_cancels(monkeypatch):
    from backend.services import docker_cleanup

    job = {
        "id": "abc",
        "state": "running",
        "percent": 40,
        "message": "Removing image 3 of 9",
        "freed_human": "1.2 GB",
        "errors": [],
        "started_at": 1.0,
        "finished_at": None,
        "_cancel": False,
        "steps": [],
    }
    monkeypatch.setattr(docker_cleanup, "_PRUNE_JOBS", {"abc": job})
    (j,) = _active("docker_cleanup")
    assert j["id"] == "prune:abc" and j["percent"] == 40 and j["can_cancel"]
    assert j["detail"] == "Removing image 3 of 9 · 1.2 GB freed" and j["title_id"] == "jobs.t.docker_cleanup"
    assert job_manager.cancel("prune:abc", everyone=True) and job["_cancel"]
    job.update(state="done_with_errors", errors=["x"], percent=100, finished_at=2.0, message="Finished")
    done = job_manager.list(everyone=True)
    assert not done["active"] and done["history"][0]["detail"] == "Finished · 1.2 GB freed · 1 could not be removed"


def test_an_ai_model_download_shows_for_who_asked(monkeypatch):
    from backend.services import model_installer

    monkeypatch.setattr(
        model_installer,
        "_JOBS",
        {
            "m1": {
                "id": "m1",
                "model": "qwen3:4b",
                "state": "downloading",
                "status": "pulling",
                "percent": 25.0,
                "completed_bytes": 500_000_000,
                "total_bytes": 2_000_000_000,
                "error": "",
                "requested_by": "ana",
                "started_at": 1.0,
                "finished_at": None,
            },
        },
    )
    cancelled = []
    monkeypatch.setattr(model_installer, "cancel_job", lambda i: cancelled.append(i) or True)
    (j,) = job_manager.list(owner="ana")["active"]
    assert j["kind"] == "model_download" and j["title_params"] == {"model": "qwen3:4b"}
    assert j["detail"] == "pulling · 0.5 of 2.0 GB" and j["percent"] == 25.0
    assert job_manager.list(owner="ben")["active"] == []
    assert job_manager.cancel("model:m1", owner="ana") and cancelled == ["m1"]
    model_installer._JOBS["m1"].update(state="failed", error="no space", finished_at=2.0)
    assert job_manager.list(everyone=True)["history"][0]["error"] == "no space"


def test_a_vm_installer_download_shows_and_cancels(monkeypatch):
    from backend.services import vm_store

    task = {
        "task_id": "dl-x",
        "name": "Debian 13",
        "status": "downloading",
        "progress_pct": 12,
        "speed_mb_s": 31.5,
        "started_at": 1.0,
    }
    monkeypatch.setattr(vm_store, "_DOWNLOAD_TASKS", {"dl-x": task})
    monkeypatch.setattr(vm_store, "_ABORT_DOWNLOAD_TASKS", set())
    (j,) = _active("vm_download")
    assert j["title_params"] == {"name": "Debian 13"} and j["detail"] == "31.5 MB/s" and j["can_cancel"]
    assert job_manager.cancel("iso:dl-x", everyone=True) and "dl-x" in vm_store._ABORT_DOWNLOAD_TASKS
    task.update(status="checksum_mismatch", error="SHA-256 mismatch")
    assert not jobs_more._cancel_iso("dl-x")
    (h,) = job_manager.list(everyone=True)["history"]
    assert h["status"] == "error" and h["finished_at"]


def test_a_drive_self_test_shows_how_far_it_is():
    from backend.state import Z_STATE

    Z_STATE.smart.start_test(
        "sdb",
        {
            "dev": "sdb",
            "test_type": "long",
            "start_time": 5.0,
            "model": "WDC WD200",
            "expected_minutes": 1440,
            "last_pct": 30,
        },
    )
    try:
        (j,) = _active("smart_test")
        assert j["id"] == "smart:sdb" and j["percent"] == 30 and j["detail"] == "About 1440 minutes in all"
        assert j["title_params"] == {"test": "long", "disk": "WDC WD200 (sdb)"} and not j["can_cancel"]
    finally:
        Z_STATE.smart.end_test("sdb")
    assert _active("smart_test") == []


class _Adapter:
    def __init__(self, kind, busy=False):
        self.kind, self.busy = kind, busy

    def get_platform_type(self):
        return self.kind

    def is_storage_busy(self):
        return self.busy


def test_unraid_parity_check_and_mover(monkeypatch):
    from backend.hardware import pal_storage, unraid
    from backend.hardware.pal.base import PlatformType

    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: _Adapter(PlatformType.UNRAID))
    status = {
        "parity_check": {"active": False, "paused": True, "progress_pct": 41.5, "errors": 2},
        "mover": {"active": True, "total_files": 200, "remain_files": 50},
    }
    monkeypatch.setattr(unraid, "read_unraid_status", lambda force=False: status)
    parity, mover = _active("storage_check") + _active("mover")
    parity, mover = jobs.Job(**parity), jobs.Job(**mover)
    assert (parity.status, parity.percent, parity.detail) == ("paused", 41.5, "2 errors found so far")
    assert (mover.kind, mover.percent, mover.detail) == ("mover", 75.0, "50 files left")
    status["parity_check"] = {"active": False, "paused": False}
    status["mover"] = {"active": False}
    assert jobs_more._storage_checks() == []


def test_a_scrub_elsewhere(monkeypatch):
    from backend.hardware import pal_storage
    from backend.hardware.pal.base import PlatformType

    assert _active("storage_check") == []  # the fixture's platform: nothing running
    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: _Adapter(PlatformType.GENERIC_LINUX, busy=True))
    (j,) = _active("storage_check")
    assert j["id"] == "storage:check" and j["title_id"] == "jobs.t.scrub" and j["percent"] is None


def test_follow_mirrors_an_install(monkeypatch):
    seen = []
    events = [
        {"step": "pull", "percent": 30, "message": "Pulling", "done": False},
        {"step": "done", "percent": 100, "done": True},
    ]
    for _ev in follow(iter(events), "app_install", "Installing Immich", "jobs.t.app_install", {"name": "Immich"}):
        seen.append([(j["percent"], j["detail"]) for j in _active("app_install")])
    assert seen == [[(30, "Pulling")], [(30, "Pulling")]]
    (h,) = job_manager.list(everyone=True)["history"]
    assert h["status"] == "done" and h["title_params"] == {"name": "Immich"}


def test_follow_marks_a_failed_or_abandoned_install():
    bad = [{"step": "error", "percent": 0, "message": "Pull failed", "done": True}]
    list(follow(iter(bad), "app_install", "Installing X"))
    stream = follow(iter([{"step": "pull", "percent": 10, "done": False}] * 3), "app_install", "Installing Y")
    next(stream)
    stream.close()  # the install window was closed
    first, second = job_manager.list(everyone=True)["history"]
    assert (first["status"], first["error"]) == ("cancelled", None) and first["title"] == "Installing Y"
    assert (second["status"], second["error"]) == ("error", "Pull failed")


def test_a_pass_report_shows_work_pauses_and_finishes(monkeypatch):
    calls = []

    def progress():
        calls.append(1)
        return "3 of 10 photos described", 30.0

    r = PassReport("photo_captions", "Describing photos for search", "jobs.t.captions")
    r.note("busy", progress)
    r.note("empty", progress)
    assert job_manager.list(everyone=True) == {"active": [], "history": []}  # nothing done, nothing shown
    r.note("done", progress)
    r.note("done", progress)
    (j,) = _active("photo_captions")
    assert (j["status"], j["detail"], j["percent"]) == ("running", "3 of 10 photos described", 30.0)
    assert len(calls) == 1  # counted at most once a minute
    r.note("standby", progress)
    assert _active("photo_captions")[0]["status"] == "paused"
    assert _active("photo_captions")[0]["detail"] == "Waiting for a sleeping disk"
    r.note("empty", progress)
    (h,) = job_manager.list(everyone=True)["history"]
    assert h["status"] == "done" and h["detail"] == "3 of 10 photos described" and r.job_id is None


class _Stop(Exception):
    pass


def _run_once(queue):
    def sleep(_s):
        raise _Stop

    with pytest.raises(_Stop):
        queue.run_forever(sleep=sleep)


def test_the_caption_and_photo_search_passes_report(monkeypatch):
    from backend.services import photo_vectors, vision_queue

    vq = vision_queue.VisionQueue.__new__(vision_queue.VisionQueue)
    vq.last_state, vq.last_error = "starting", ""
    vq.report = PassReport("photo_captions", "Describing photos for search", "jobs.t.captions")
    vq.process_one = lambda: "done"
    vq.status = lambda: {"photos": 8, "captioned": 2}
    _run_once(vq)
    (j,) = _active("photo_captions")
    assert j["detail"] == "2 of 8 photos described" and j["percent"] == 25.0

    photo_vectors.PhotoVectorQueue(engine=None, idle=lambda: True).report.note("done", lambda: ("", None))  # no-op
    report = PassReport("photo_vectors", "Preparing photos for search by meaning", "jobs.t.photo_vectors")
    pv = photo_vectors.PhotoVectorQueue(engine=None, idle=lambda: True, report=report)
    pv.process_batch = lambda: "error"
    pv.status = lambda: {"photos": 4, "done": 1}
    _run_once(pv)
    assert _active("photo_vectors") == []  # a failed try is no work done
    pv.process_batch = lambda: "done"
    _run_once(pv)
    (j,) = _active("photo_vectors")
    assert j["detail"] == "1 of 4 photos ready" and j["percent"] == 25.0


def test_a_replication_run_is_a_job(monkeypatch, tmp_path):
    from backend.services import replication_engine as re_

    monkeypatch.setattr(re_, "REPLICATION_JOBS_FILE", str(tmp_path / "r.json"))
    monkeypatch.setattr(re_, "REPLICATION_HISTORY_FILE", str(tmp_path / "rh.json"))
    monkeypatch.setattr(re_, "_notify", lambda *a: None)
    seen = []

    def replicate(job):
        seen.append([j["title_params"] for j in _active("replication")])
        if job["name"] == "Bad":
            raise RuntimeError("target gone")
        return {"bytes": 10, "snapshot": "s1"}

    monkeypatch.setattr(re_, "replicate", replicate)
    eng = re_.ReplicationEngine()
    eng._execute({"id": "a", "name": "Photos"})
    eng._execute({"id": "b", "name": "Bad"})
    assert seen == [[{"name": "Photos"}], [{"name": "Bad"}]]
    bad, good = job_manager.list(everyone=True)["history"]
    assert (good["status"], bad["status"], bad["error"]) == ("done", "error", "target gone")
