"""SET-07: "Replace" on install took the old app away before the new one was downloaded. A failed
download, create or start left no app at all."""

from unittest.mock import patch

import pytest

from backend.services import app_catalog

NAME = "uptime-kuma"
ASIDE = NAME + app_catalog.ASIDE_SUFFIX


class Docker:
    """A stand-in that remembers what was asked, in order."""

    def __init__(self, image_present=True, create=201, start=204, runs=True, rename=204):
        self.calls = []
        self.image_present, self.create, self.start, self.runs, self.rename = image_present, create, start, runs, rename

    def __call__(self, method, path, *args, **kwargs):
        self.calls.append(f"{method} {path}")
        if path.startswith(f"/containers/{ASIDE}/json"):
            return 404, {}
        if path.startswith(f"/containers/{NAME}/json"):
            return 200, {"Id": "old123456789", "State": {"Running": True}}
        if path.startswith("/images/"):
            return (200, {}) if self.image_present else (404, {})
        if "/rename" in path:
            return self.rename, {}
        if path.startswith("/containers/create"):
            return self.create, ({"Id": "new123456789abc"} if self.create == 201 else {"message": "no space"})
        if path.endswith("/start"):
            return (self.start, {}) if "new123456789abc" in path else (204, {})
        if path.startswith("/containers/new123456789abc/json"):
            return 200, {"State": {"Running": self.runs}}
        return 204, {}

    def asked(self, text):
        return [c for c in self.calls if text in c]


def _install(docker, tmp_path, **kw):
    with (
        patch.object(app_catalog, "_docker_request", side_effect=docker),
        patch.object(app_catalog, "check_port_available_detailed", return_value=(False, f"container '{NAME}'")),
        patch.object(app_catalog.time, "sleep"),
    ):
        return list(
            app_catalog.stream_deploy_catalog_app(
                NAME, host_port=3001, storage_root=str(tmp_path), container_name=NAME, replace_existing=True, **kw
            )
        )


def test_a_download_that_fails_leaves_the_old_app_untouched(tmp_path):
    docker = Docker(image_present=False)
    with patch.object(app_catalog.os.path, "exists", side_effect=lambda p: not str(p).endswith("docker.sock")):
        events = _install(docker, tmp_path)
    assert events[-1]["step"] == "error"
    assert not docker.asked("DELETE"), docker.calls
    assert not docker.asked("/stop"), docker.calls
    assert not docker.asked("/rename"), docker.calls


def test_the_old_app_is_set_aside_after_the_download_and_removed_once_the_new_one_runs(tmp_path):
    docker = Docker()
    events = _install(docker, tmp_path)
    assert events[-1]["step"] == "success", events[-1]
    order = docker.calls
    image, rename = order.index(docker.asked("/images/")[0]), order.index(docker.asked("/rename")[0])
    create, gone = (
        order.index(docker.asked("/containers/create")[0]),
        order.index(docker.asked(f"DELETE /containers/{ASIDE}")[0]),
    )
    start = order.index("POST /containers/new123456789abc/start")
    assert image < rename < create < start < gone, order
    assert not docker.asked(f"DELETE /containers/{NAME}?"), order


@pytest.mark.parametrize("fault", [{"create": 500}, {"start": 500}, {"runs": False}])
def test_the_old_app_comes_back_when_the_new_one_does_not_start(tmp_path, fault):
    docker = Docker(**fault)
    events = _install(docker, tmp_path)
    assert events[-1]["step"] == "error"
    assert "previous app is back" in events[-1]["message"]
    assert f"POST /containers/{ASIDE}/rename?name={NAME}" in docker.calls
    assert docker.calls[-1] == f"POST /containers/{NAME}/start"
    assert not docker.asked(f"DELETE /containers/{ASIDE}"), docker.calls
    if "create" not in fault:
        assert docker.asked("DELETE /containers/new123456789abc"), docker.calls


def test_an_app_docker_will_not_rename_is_started_again_and_nothing_is_created(tmp_path):
    docker = Docker(rename=409)
    events = _install(docker, tmp_path)
    assert events[-1]["step"] == "error"
    assert not docker.asked("/containers/create"), docker.calls
    assert docker.calls[-1] == f"POST /containers/{NAME}/start"


def test_closing_the_window_between_create_and_start_brings_the_old_app_back(tmp_path):
    docker = Docker()
    with (
        patch.object(app_catalog, "_docker_request", side_effect=docker),
        patch.object(app_catalog, "check_port_available_detailed", return_value=(False, f"container '{NAME}'")),
        patch.object(app_catalog.time, "sleep"),
    ):
        stream = app_catalog.stream_deploy_catalog_app(
            NAME, host_port=3001, storage_root=str(tmp_path), container_name=NAME, replace_existing=True
        )
        for ev in stream:
            if ev.get("step") == "create" and ev.get("percent") == 88:
                break
        stream.close()
    assert docker.asked("DELETE /containers/new123456789abc"), docker.calls
    assert f"POST /containers/{ASIDE}/rename?name={NAME}" in docker.calls
    assert not docker.asked(f"DELETE /containers/{ASIDE}"), docker.calls
