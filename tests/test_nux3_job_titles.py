"""NUX-3: jobs carry their title's message key and values."""

from backend.services.jobs import JobManager


def test_a_registered_job_keeps_its_title_id():
    jm = JobManager()
    job = jm.register("restore", "Restore a from b", title_id="jobs.t.restore", title_params={"name": "a", "repo": "b"})
    d = job.to_dict()
    assert (
        d["title"] == "Restore a from b"
        and d["title_id"] == "jobs.t.restore"
        and d["title_params"] == {"name": "a", "repo": "b"}
    )
    plain = jm.register("backup", "Backup: x").to_dict()
    assert plain["title_id"] == "" and plain["title_params"] == {}
