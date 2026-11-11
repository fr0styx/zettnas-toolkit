"""SET-13: a zip being made is not "Transfer 2 items to /folder" in the Jobs list."""

from backend.services import fs_transfer, jobs


def test_archive_jobs_say_what_they_do(monkeypatch):
    tasks = [
        {"id": "a", "action": "archive_create", "sources": ["/p/x", "/p/y"], "destination": "/p", "status": "running"},
        {"id": "b", "action": "archive_extract", "sources": ["/p/x.zip"], "destination": "/p/out", "status": "running"},
        {"id": "c", "action": "copy", "sources": ["/p/x"], "destination": "/q", "status": "running"},
        {"id": "d", "action": "sync", "sources": ["/p/x"], "destination": "/q", "status": "running"},
    ]
    monkeypatch.setattr(fs_transfer.transfer_manager, "list_tasks", lambda: tasks)
    made, unpacked, copied, other = jobs._transfers()
    assert (made.title, made.title_id) == ("Make an archive from 2 item(s)", "jobs.t.archive_create")
    assert (unpacked.title, unpacked.title_id) == ("Unpack an archive into /p/out", "jobs.t.archive_extract")
    assert (copied.title, copied.title_id) == ("Copy 1 item(s) to /q", "jobs.t.copy")
    assert (other.title, other.title_id) == ("Transfer 1 item(s) to /q", "jobs.t.transfer")
    assert made.title_params == {"n": 2, "dest": "/p"}
