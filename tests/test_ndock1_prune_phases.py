"""NDOCK-1: after the last image, the cleanup says what it is doing (Docker's sweep of the layers,
then measuring what was freed) instead of sitting at 99% on "Removing image 10 of 10", and the
space Docker reports for the sweep shows at once."""

import threading
from unittest.mock import patch

from backend.services import docker_cleanup as dc
from tests.test_prune_progress import FakeDocker, _wait


class SlowSweep(FakeDocker):
    def __init__(self):
        super().__init__()
        self.sweeping = threading.Event()
        self.release = threading.Event()

    def __call__(self, method, path, *a, **k):
        if method == "POST" and path.startswith("/images/prune"):
            self.sweeping.set()
            self.release.wait(10)
            return 200, {"ImagesDeleted": [{"Deleted": "sha256:layer"}], "SpaceReclaimed": 700}
        return super().__call__(method, path, *a, **k)


def test_the_sweep_and_the_measurement_show_after_the_last_image():
    fake = SlowSweep()
    with patch.object(dc, "_docker_request", fake), patch.object(dc, "add_event"):
        job, _ = dc.start_prune_job(prune_containers=False, all_images=True, prune_volumes=False)
        assert fake.sweeping.wait(10)
        during = _wait(job["id"], until=lambda j: j.get("images_phase") == "sweep")
        assert during["images_done"] == during["images_total"]
        assert during["percent"] < 99
        fake.release.set()
        done = _wait(job["id"])
    assert done["state"] == "done" and done["percent"] == 100
    # the images step counts the measured space (before minus after), not the sweep's figure on top
    images = next(s for s in done["steps"] if s["key"] == "images")
    others = sum(s["freed_bytes"] for s in done["steps"] if s["key"] != "images")
    assert images["freed_bytes"] == 1800 - 900 and done["freed_bytes"] == images["freed_bytes"] + others


def test_the_sweeps_figure_counts_while_measuring_is_not_possible():
    fake = SlowSweep()
    fake.release.set()
    real = fake.__call__

    def no_df(method, path, *a, **k):
        if path.startswith("/system/df"):
            return 500, {"message": "busy"}
        return real(method, path, *a, **k)

    with patch.object(dc, "_docker_request", no_df), patch.object(dc, "add_event"):
        job, _ = dc.start_prune_job(prune_containers=False, all_images=True, prune_volumes=False)
        done = _wait(job["id"])
    assert next(s for s in done["steps"] if s["key"] == "images")["freed_bytes"] == 700
