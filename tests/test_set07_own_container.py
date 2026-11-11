"""SET-07: the list of apps can not stop, restart or pause Kiboto itself, and a selection is not
deleted in one forced call."""

from unittest.mock import patch

from backend.hardware import docker_stats
from backend.services import docker_stacks

OWN = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
OTHER = "f" * 64


def _as_own_container():
    return patch("socket.gethostname", return_value=OWN[:12])


def test_own_container_is_known_by_id_and_by_name():
    with _as_own_container():
        assert docker_stats.is_kiboto_itself(OWN)
        assert docker_stats.is_kiboto_itself(OWN[:12])
        assert docker_stats.is_kiboto_itself(OTHER, "kiboto")
        assert not docker_stats.is_kiboto_itself(OTHER, "jellyfin")
        assert not docker_stats.is_kiboto_itself("0123")  # a short prefix names nothing


def test_a_short_hostname_matches_no_app():
    with patch("socket.gethostname", return_value="nas"):
        assert not docker_stats.is_kiboto_itself("nas-photos")
        assert not docker_stats.is_kiboto_itself(OTHER)


def test_stop_restart_and_pause_are_refused_before_docker_is_asked():
    with _as_own_container(), patch.object(docker_stats, "UnixHTTPConnection") as conn:
        for action in ("stop", "restart", "pause"):
            res = docker_stats.container_action(OWN, action)
            assert res["success"] is False
            assert res["error"] == docker_stats.KIBOTO_ITSELF
        conn.assert_not_called()


def test_other_apps_are_still_stopped():
    with (
        _as_own_container(),
        patch.object(docker_stats.os.path, "exists", return_value=True),
        patch.object(docker_stats, "UnixHTTPConnection") as conn,
    ):
        conn.return_value.getresponse.return_value.status = 204
        conn.return_value.getresponse.return_value.read.return_value = b""
        assert docker_stats.container_action(OTHER, "stop")["success"] is True


def test_a_stack_action_passes_over_kiboto():
    stack = {
        "containers": [{"id": OWN, "name": "kiboto"}, {"id": OTHER, "name": "db"}],
        "location_type": None,
        "working_dir": None,
        "compose_yaml": None,
    }
    asked = []

    def fake_request(method, path, *a, **k):
        asked.append(path)
        return 204, b""

    for action in ("stop", "restart", "redeploy"):
        asked.clear()
        with (
            _as_own_container(),
            patch.object(docker_stacks, "get_stack_details", return_value=stack),
            patch.object(docker_stacks, "_docker_request", side_effect=fake_request),
            patch.object(docker_stacks, "topological_sort_stack_containers", side_effect=lambda c, *a, **k: list(c)),
        ):
            docker_stacks.execute_stack_action("home", action)
        assert asked, action
        assert not [p for p in asked if OWN in p], action
        assert [p for p in asked if OTHER in p], action
