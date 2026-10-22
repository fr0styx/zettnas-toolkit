"""Docker cleanup with a progress bar: a background job that removes unused images one at a time."""

import threading
import time
from unittest.mock import patch

from backend.services import docker_cleanup as dc


class FakeDocker:
    def __init__(self, slow=0.0):
        self.images = [
            {"Id": "sha256:app", "RepoTags": ["ghcr.io/fr0styx/zettnas-toolkit:sha-new"], "Created": 50, "Size": 900},
            {
                "Id": "sha256:rollback",
                "RepoTags": ["ghcr.io/fr0styx/zettnas-toolkit:sha-old"],
                "Created": 40,
                "Size": 900,
            },
            {"Id": "sha256:old1", "RepoTags": ["immich:1.0"], "Created": 30, "Size": 500},
            {"Id": "sha256:multi", "RepoTags": ["a:1", "a:latest"], "Created": 20, "Size": 300},
            {"Id": "sha256:dangling", "RepoTags": [], "Created": 10, "Size": 100},
        ]
        self.containers = [
            {"Image": "ghcr.io/fr0styx/zettnas-toolkit:sha-new", "ImageID": "sha256:app", "State": "running"},
            {"Image": "ghcr.io/fr0styx/zettnas-toolkit:sha-old", "ImageID": "sha256:rollback", "State": "exited"},
        ]
        self.deleted = []
        self.slow = slow
        self.gate = threading.Event()
        self.gate.set()

    def layers(self):
        return sum(i["Size"] for i in self.images)

    def __call__(self, method, path, *a, **k):
        if method == "GET" and path.startswith("/images/json"):
            return 200, [dict(i) for i in self.images]
        if method == "GET" and path.startswith("/containers/json"):
            return 200, self.containers
        if method == "GET" and path.startswith("/system/df"):
            return 200, {"LayersSize": self.layers()}
        if method == "DELETE" and path.startswith("/images/"):
            self.gate.wait(5)
            time.sleep(self.slow)
            ref = path[len("/images/") :].replace("%3A", ":").replace("%2F", "/")
            self.deleted.append(ref)
            for img in list(self.images):
                if img["Id"] == ref:
                    self.images.remove(img)
                elif ref in img["RepoTags"]:
                    img["RepoTags"].remove(ref)
                    if not img["RepoTags"]:
                        self.images.remove(img)
            return 200, [{"Deleted": ref}]
        if method == "POST" and path.startswith("/images/prune"):
            return 200, {"ImagesDeleted": [], "SpaceReclaimed": 0}
        if method == "POST" and path == "/containers/prune":
            return 200, {"ContainersDeleted": ["c1"], "SpaceReclaimed": 40}
        if method == "POST" and path == "/volumes/prune":
            return 200, {"VolumesDeleted": ["v1", "v2"], "SpaceReclaimed": 60}
        if method == "POST" and path == "/networks/prune":
            return 200, {"NetworksDeleted": ["n1"]}
        if method == "POST" and path.startswith("/build/prune"):
            return 200, {"CachesDeleted": ["b1"], "SpaceReclaimed": 7}
        return 404, {"message": "unexpected " + path}


def _wait(job_id, until=lambda j: j["state"] != "running", timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        job = dc.get_prune_job(job_id)
        if until(job):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job stuck: {dc.get_prune_job(job_id)}")


def test_all_unused_images_keeps_images_of_stopped_containers():
    fake = FakeDocker()
    with patch.object(dc, "_docker_request", fake), patch.object(dc, "add_event"):
        job, started = dc.start_prune_job(prune_containers=True, all_images=True, prune_volumes=True)
        assert started
        job = _wait(job["id"])
    assert job["state"] == "done" and job["percent"] == 100
    assert "sha256:app" not in fake.deleted and "sha256:rollback" not in fake.deleted  # rollback image kept
    assert {"sha256:old1", "sha256:dangling", "a:1", "a:latest"} <= set(fake.deleted)
    assert job["images_total"] == 3 and job["counts"]["images"] == 3
    images = next(s for s in job["steps"] if s["key"] == "images")
    assert images["freed_bytes"] == 900  # measured from the layer size before and after
    assert job["freed_bytes"] == 40 + 900 + 60 + 7
    assert [s["state"] for s in job["steps"]] == ["done"] * 5


def test_progress_moves_and_a_second_start_returns_the_running_job():
    fake = FakeDocker()
    fake.gate.clear()
    with patch.object(dc, "_docker_request", fake), patch.object(dc, "add_event"):
        job, _ = dc.start_prune_job(
            all_images=True, prune_containers=True, prune_networks=False, prune_build_cache=False
        )
        running = _wait(job["id"], until=lambda j: j["step"] == "images" and j["images_total"] == 3)
        assert 0 < running["percent"] < 100
        again, started = dc.start_prune_job()
        assert not started and again["id"] == job["id"]
        fake.gate.set()
        done = _wait(job["id"])
    assert done["percent"] == 100


def test_stop_halts_between_images():
    fake = FakeDocker(slow=0.15)
    with patch.object(dc, "_docker_request", fake), patch.object(dc, "add_event"):
        job, _ = dc.start_prune_job(all_images=True, prune_containers=False, prune_volumes=True)
        _wait(job["id"], until=lambda j: j["images_done"] >= 1)
        assert dc.cancel_prune_job(job["id"])
        job = _wait(job["id"])
    assert job["state"] == "cancelled"
    assert len(fake.deleted) < 4
    assert next(s for s in job["steps"] if s["key"] == "volumes")["state"] == "skipped"


def test_job_endpoints(client, auth_headers):
    fake = FakeDocker()
    with patch.object(dc, "_docker_request", fake), patch.object(dc, "add_event"):
        r = client.post("/api/docker/system/prune/jobs", json={"all_images": True}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["started"]
        job_id = r.json()["job"]["id"]
        _wait(job_id)
        r = client.get(f"/api/docker/system/prune/jobs/{job_id}", headers=auth_headers)
        assert r.json()["job"]["state"] == "done"
        assert client.get("/api/docker/system/prune/jobs/current", headers=auth_headers).json()["job"]["id"] == job_id
        assert client.post(f"/api/docker/system/prune/jobs/{job_id}/cancel", headers=auth_headers).status_code == 409
        assert client.get("/api/docker/system/prune/jobs/nope", headers=auth_headers).status_code == 404


def test_reclaimable_estimate_counts_shared_layers_once():
    df = {
        "LayersSize": 1000,
        "Images": [
            {"Size": 600, "SharedSize": 200, "Containers": 1},  # in use: 400 of its own
            {"Size": 500, "SharedSize": 200, "Containers": 0},
            {"Size": 300, "SharedSize": 0, "Containers": 0},
        ],
        "Containers": [],
        "Volumes": [],
        "BuildCache": [],
    }
    with patch.object(dc, "_docker_request", return_value=(200, df)):
        out = dc.get_docker_system_df()
    assert out["images"]["reclaimable_bytes"] == 600  # not 800 (the sum of unused image sizes)
