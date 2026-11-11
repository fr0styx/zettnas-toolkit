"""SET-14: removing an app. A copy that was asked for and could not be made stops the delete, and
"stop it first" is a stop, not a kill."""

from unittest.mock import patch

import pytest

from backend.services import docker_cleanup as dc

INSPECT = {
    "Name": "/plex",
    "Id": "a" * 64,
    "Image": "sha256:1",
    "Config": {"Image": "plex:latest"},
    "State": {"Running": True},
}


def _docker(calls, inspect=INSPECT):
    def request(method, path, timeout=20.0, **_k):
        calls.append((method, path.split("?")[0], path))
        if method == "GET":
            return 200, inspect
        return 204, {}

    return request


def test_a_failed_copy_keeps_the_app(monkeypatch):
    calls = []
    monkeypatch.setattr(dc, "_docker_request", _docker(calls))
    monkeypatch.setattr(dc, "is_self_container", lambda *_a: False)
    with patch("backend.services.app_backup.create_app_backup", side_effect=OSError("disk full")):
        with pytest.raises(dc.CopyFailed) as err:
            dc.destroy_container("plex", force=True, archive_data=True)
    assert "was not removed" in str(err.value) and "disk full" in str(err.value)
    assert [c[0] for c in calls] == ["GET"]  # it was removed all the same, and nobody was told


def test_stop_it_first_stops_before_it_removes(monkeypatch):
    calls = []
    monkeypatch.setattr(dc, "_docker_request", _docker(calls))
    monkeypatch.setattr(dc, "is_self_container", lambda *_a: False)
    monkeypatch.setattr(dc, "add_event", lambda *a, **k: None)
    res = dc.destroy_container("plex", force=True, archive_data=False, remove_volumes=False)
    assert res["removed"] is True and res["archived"] is False
    assert [(c[0], c[1]) for c in calls] == [
        ("GET", "/containers/plex/json"),
        ("POST", "/containers/plex/stop"),
        ("DELETE", "/containers/plex"),
    ]
    assert "t=10" in calls[1][2]

    # an app that is not running is removed without a stop
    calls.clear()
    monkeypatch.setattr(dc, "_docker_request", _docker(calls, {**INSPECT, "State": {"Running": False}}))
    dc.destroy_container("plex", force=True, archive_data=False)
    assert [c[0] for c in calls] == ["GET", "DELETE"]


def test_the_route_says_that_nothing_was_removed(client, auth_headers, monkeypatch):
    def refuse(*_a, **_k):
        raise dc.CopyFailed("The copy of plex's set-up could not be made, so plex was not removed: disk full.")

    monkeypatch.setattr(dc, "destroy_container", refuse)
    token = client.post(
        "/api/confirmations", json={"action": "docker.container.delete", "target": "plex"}, headers=auth_headers
    ).json()["token"]
    r = client.delete("/api/docker/containers/plex", headers={**auth_headers, "X-Confirm-Token": token})
    assert r.status_code == 409 and "was not removed" in r.text
