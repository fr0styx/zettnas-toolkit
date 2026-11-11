"""SET-07, the owner's decision S22: "Clean up" never removes a stopped app unless it is asked to.

"Remove stopped containers" was ticked by default and the dialog's one button started it, with no
names and no second question. It removed every app that was not running, also one stopped on
purpose and the copy an edit keeps for going back."""

from backend.api import docker as docker_api
from backend.services import docker_cleanup

DF = {
    "Images": [],
    "Volumes": [],
    "BuildCache": [],
    "Containers": [
        {"Id": "a" * 64, "Names": ["/jellyfin"], "State": "running", "SizeRw": 10},
        {"Id": "b" * 64, "Names": ["/paperless"], "State": "exited", "SizeRw": 5},
        {"Id": "c" * 64, "Names": ["/immich_backup_1790000000"], "State": "created", "SizeRw": 0},
        {"Id": "d" * 64, "Names": [], "State": "dead", "SizeRw": 0},
    ],
}


def test_the_summary_names_the_stopped_apps(monkeypatch):
    monkeypatch.setattr(docker_cleanup, "_docker_request", lambda method, path, **k: (200, DF))
    containers = docker_cleanup.get_docker_system_df()["containers"]
    assert containers["stopped_count"] == 3
    assert containers["stopped_names"] == ["dddddddddddd", "immich_backup_1790000000", "paperless"]


def test_a_cleanup_that_says_nothing_leaves_stopped_apps_alone():
    assert docker_api.DockerPruneRequest().prune_containers is False
    assert docker_api.DockerPruneRequest(prune_containers=True).prune_containers is True
    import inspect

    for fn in (docker_cleanup.prune_docker_system, docker_cleanup.start_prune_job):
        assert inspect.signature(fn).parameters["prune_containers"].default is False


def test_the_route_removes_them_only_when_asked(client, auth_headers, monkeypatch):
    asked = []

    def start(**kw):
        asked.append(kw["prune_containers"])
        return {"id": "j1", "state": "running"}, True

    monkeypatch.setattr(docker_cleanup, "start_prune_job", start)
    assert client.post("/api/docker/system/prune/jobs", json={}, headers=auth_headers).status_code == 200
    assert client.post("/api/docker/system/prune/jobs", headers=auth_headers).status_code == 200
    r = client.post("/api/docker/system/prune/jobs", json={"prune_containers": True}, headers=auth_headers)
    assert r.status_code == 200 and asked == [False, False, True]
