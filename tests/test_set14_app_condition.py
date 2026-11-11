"""SET-14: the list of apps says what state an app is really in, and whether the list itself
can be trusted."""

import json
from unittest.mock import MagicMock, patch

import pytest

from backend import config
from backend.hardware import docker_condition as dc
from backend.hardware import docker_stats as ds


@pytest.fixture
def stops(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(dc, "_stopped", None)
    yield tmp_path
    monkeypatch.setattr(dc, "_stopped", None)


@pytest.mark.parametrize(
    "state, status, by_kiboto, inspect, condition, look",
    [
        ("running", "Up 2 days", False, None, "running", False),
        ("running", "Up 2 days (healthy)", False, None, "running", False),
        ("running", "Up 2 days (unhealthy)", False, None, "unhealthy", True),  # it was green
        ("running", "Up 5 seconds (health: starting)", False, None, "starting", False),
        ("restarting", "Restarting (1) 3 seconds ago", False, {"RestartCount": 14}, "restarting", True),
        ("paused", "Up 2 hours (Paused)", False, None, "paused", False),
        ("created", "Created", False, None, "created", False),
        ("exited", "Exited (0) 3 hours ago", False, None, "stopped", False),
        ("exited", "Exited (1) 3 hours ago", False, None, "crashed", True),  # the same quiet grey as a stop
        ("exited", "Exited (137) 3 hours ago", True, None, "stopped", False),  # Kiboto's own stop
        ("exited", "Exited (137) 3 hours ago", False, {"State": {"OOMKilled": True}}, "crashed", True),
        ("exited", "Exited (143) 3 hours ago", False, None, "stopped", False),
        ("exited", "Exited (1) 3 hours ago", True, None, "stopped", False),
        ("exited", "", False, {"State": {"ExitCode": 2}}, "crashed", True),
        ("dead", "Dead", False, None, "dead", True),
        ("weird", "", False, None, "unknown", False),
    ],
)
def test_one_word_for_the_state_and_whether_to_look(state, status, by_kiboto, inspect, condition, look):
    got = dc.describe(state, status, by_kiboto, inspect)
    assert (got["condition"], got["needs_look"]) == (condition, look)


def test_the_reasons_and_numbers():
    oom = dc.describe("exited", "Exited (137) 1 minute ago", False, {"State": {"OOMKilled": True}, "RestartCount": 3})
    assert oom == {
        "condition": "crashed",
        "needs_look": True,
        "health": "",
        "exit_code": 137,
        "restart_count": 3,
        "reason": "out_of_memory",
    }
    assert dc.describe("exited", "Exited (143) 1 minute ago")["reason"] == "stopped_outside"
    assert dc.describe("exited", "Exited (2) 1 minute ago")["reason"] == "exit_code"
    assert dc.describe("running", "Up 1 hour (unhealthy)")["health"] == "unhealthy"
    assert dc.exit_code("Up 2 days") is None and dc.health("Up 2 days") == ""


def test_kiboto_remembers_its_own_stops_across_a_restart(stops):
    assert not dc.stopped_by_kiboto("abc", "jellyfin")
    dc.note_stopped("abc", "", "jellyfin")
    assert dc.stopped_by_kiboto("jellyfin") and dc.stopped_by_kiboto("abc")
    assert json.loads((stops / "docker_stopped.json").read_text()) == ["abc", "jellyfin"]
    dc._stopped = None  # Kiboto restarted
    assert dc.stopped_by_kiboto("abc")
    dc.note_started("jellyfin", "abc")
    assert not dc.stopped_by_kiboto("abc", "jellyfin")
    dc.note_stopped("gone", "here")
    dc.forget_missing({"here"})  # an app that was removed is forgotten
    assert json.loads((stops / "docker_stopped.json").read_text()) == ["here"]
    (stops / "docker_stopped.json").write_text("{ not json")
    dc._stopped = None
    assert not dc.stopped_by_kiboto("here")


def _docker(listing, inspects, status=200):
    """A Docker socket that answers the list and each inspect."""

    def conn_factory(*_a, **_k):
        conn = MagicMock()
        asked = {}

        def request(_method, path):
            asked["path"] = path

        def getresponse():
            res = MagicMock()
            if asked["path"].startswith("/containers/json"):
                res.status = status
                res.read.return_value = json.dumps(listing).encode()
            else:
                cid = asked["path"].split("/")[2]
                res.status = 200
                res.read.return_value = json.dumps(inspects.get(cid, {})).encode()
            return res

        conn.request.side_effect = request
        conn.getresponse.side_effect = getresponse
        return conn

    return conn_factory


@pytest.fixture
def fresh(stops, monkeypatch):
    monkeypatch.setattr(ds, "_CACHED_CONTAINERS", [])
    monkeypatch.setattr(ds, "_LAST_DOCKER_POLL", 0.0)
    monkeypatch.setattr(ds, "_CONTAINER_INSPECT_CACHE", {})
    monkeypatch.setattr(ds, "_DOCKER_STATE", {"available": True, "answering": True, "as_of": 0.0, "error": ""})
    monkeypatch.setattr(ds, "start_docker_telemetry_collector", lambda: None)
    monkeypatch.setattr(ds, "docker_sock", lambda: "/var/run/docker.sock")


LISTING = [
    {"Id": "a" * 64, "Names": ["/plex"], "Image": "plex", "State": "running", "Status": "Up 2 days (unhealthy)"},
    {"Id": "b" * 64, "Names": ["/sonarr"], "Image": "sonarr", "State": "exited", "Status": "Exited (137) 1 hour ago"},
    {"Id": "c" * 64, "Names": ["/radarr"], "Image": "radarr", "State": "exited", "Status": "Exited (1) 1 hour ago"},
]


def test_the_list_carries_the_condition_and_says_when_it_is_old(fresh):
    with (
        patch.object(ds.os.path, "exists", return_value=True),
        patch.object(ds, "UnixHTTPConnection", _docker(LISTING, {})),
    ):
        apps = {a["name"]: a for a in ds.read_docker_containers(force=True)}
    assert apps["plex"]["condition"] == "unhealthy" and apps["plex"]["needs_look"] is True
    assert apps["sonarr"]["condition"] == "stopped" and apps["sonarr"]["reason"] == "stopped_outside"
    assert apps["radarr"]["condition"] == "crashed" and apps["radarr"]["exit_code"] == 1
    state = ds.docker_state()
    assert state["available"] and state["answering"] and not state["stale"] and state["as_of"] > 0

    # Docker stops answering: the last list is returned, and the state says that it is an old one
    with (
        patch.object(ds.os.path, "exists", return_value=True),
        patch.object(ds, "UnixHTTPConnection", _docker([], {}, status=500)),
    ):
        again = ds.read_docker_containers(force=True)
    assert len(again) == 3
    assert ds.docker_state() == {
        "available": True,
        "answering": False,
        "as_of": state["as_of"],
        "error": "HTTP 500",
        "stale": True,
    }

    def broken(*_a, **_k):
        raise OSError("connection refused")

    with patch.object(ds.os.path, "exists", return_value=True), patch.object(ds, "UnixHTTPConnection", broken):
        ds.read_docker_containers(force=True)
    assert ds.docker_state()["error"] == "connection refused" and ds.docker_state()["stale"] is True

    # no Docker at all: an empty list, and the state says why
    with patch.object(ds.os.path, "exists", return_value=False):
        assert ds.read_docker_containers(force=True) == []
    assert ds.docker_state()["available"] is False


def test_a_stop_from_kiboto_is_not_a_crash_and_a_changed_state_is_asked_again(fresh):
    running = [{**LISTING[1], "State": "running", "Status": "Up 1 hour"}]
    inspect_running = {"b" * 12: {"State": {"Status": "running"}, "RestartCount": 0}}
    with (
        patch.object(ds.os.path, "exists", return_value=True),
        patch.object(ds, "UnixHTTPConnection", _docker(running, inspect_running)),
    ):
        assert ds.read_docker_containers(force=True)[0]["condition"] == "running"
        assert ds.container_action("sonarr", "stop") == {"success": True, "action": "stop", "id": "sonarr"}
    assert dc.stopped_by_kiboto("b" * 12) and dc.stopped_by_kiboto("sonarr")  # by every name the list has for it

    # the inspect answer in the cache says "running"; the list says "exited": it is asked again
    ds._CONTAINER_INSPECT_CACHE["b" * 12] = {"State": {"Status": "running"}, "_ts": 9e12}
    inspect_dead = {"b" * 12: {"State": {"Status": "exited", "OOMKilled": False, "ExitCode": 137}, "RestartCount": 2}}
    with (
        patch.object(ds.os.path, "exists", return_value=True),
        patch.object(ds, "UnixHTTPConnection", _docker([LISTING[1]], inspect_dead)),
    ):
        app = ds.read_docker_containers(force=True)[0]
        assert (app["condition"], app["restart_count"], app["reason"]) == ("stopped", 2, "")
        ds.container_action("b" * 12, "start")
    assert not dc.stopped_by_kiboto("sonarr")


def test_the_status_route_and_the_stream(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ds, "_DOCKER_STATE", {"available": False, "answering": False, "as_of": 0.0, "error": ""})
    monkeypatch.setattr(ds, "_CACHED_CONTAINERS", [])
    body = client.get("/api/docker/status", headers=auth_headers).json()
    assert body == {"available": False, "answering": False, "as_of": 0.0, "error": "", "stale": False}
    from backend.services import stats_collector

    data = {}
    with patch.object(stats_collector, "broadcaster"), patch.object(stats_collector, "log_metrics"):
        try:
            stats_collector._publish(data, [], [], {}, 0)
        except (KeyError, TypeError, AttributeError):
            pass  # the rest of the payload is not this test's
    assert data["docker_state"]["available"] is False


def test_the_update_check_says_when_it_did_not_find_out(monkeypatch):
    from backend.services import docker_updates as du

    monkeypatch.setattr(
        du, "_update_cache", {"checked_at": 5, "total_containers": 1, "updates_available_count": 0, "containers": {}}
    )
    monkeypatch.setattr(du, "_docker_request", lambda *a, **k: (500, None))
    res = du.check_all_container_updates(force=True)
    assert res["checked"] is False and res["reason"] == "docker" and res["updates_available_count"] == 0

    def boom(*_a, **_k):
        raise OSError("no socket")

    monkeypatch.setattr(du, "_docker_request", boom)
    assert du.check_all_container_updates(force=True)["checked"] is False

    answers = {
        "plex": {"name": "plex", "id": "p1", "status": "up_to_date", "has_update": False},
        "immich": {"name": "immich", "id": "i1", "status": "error", "has_update": False, "error": "timeout"},
        "ghost": {"name": "ghost", "id": "g1", "status": "auth_required", "has_update": False},
        "web": {"name": "web", "id": "w1", "status": "update_available", "has_update": True},
    }
    monkeypatch.setattr(du, "_docker_request", lambda *a, **k: (200, [{"Names": ["/" + n]} for n in answers]))
    monkeypatch.setattr(du, "_check_container_image_update", lambda c: dict(answers[c["Names"][0].lstrip("/")]))
    res = du.check_all_container_updates(force=True)
    assert res["checked"] is True and res["unchecked"] == ["ghost", "immich"] and res["updates_available_count"] == 1
    assert du.get_cached_update_status()["unchecked"] == ["ghost", "immich"]
