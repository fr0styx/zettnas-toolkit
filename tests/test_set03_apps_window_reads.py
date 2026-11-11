"""SET-03: two ways the Apps window reached further than it should.

- The Compose tab read whatever file a container label named, with no check on the path.
- The terminal connection accepted containers:manage, a lower right than the route that runs a
  command in a container, and left no trace.
"""

import os

import pytest

from backend import config
from backend.api import docker as docker_api
from backend.services import compose_synthesizer as cs

INSPECT = {
    "Name": "/web",
    "Config": {"Image": "nginx", "Labels": {}, "Env": []},
    "HostConfig": {},
    "NetworkSettings": {},
}


def _compose(monkeypatch, path):
    doc = {**INSPECT, "Config": {**INSPECT["Config"], "Labels": {"com.docker.compose.project.config_files": path}}}
    monkeypatch.setattr(cs, "fetch_container_raw_inspect", lambda cid: doc)
    names = [n for n in dir(cs) if n.startswith("get_") and "compose" in n]
    assert names, "the function behind the Compose tab was not found"
    return getattr(cs, names[0])("web")


def test_a_label_cannot_make_kiboto_read_any_file(monkeypatch, tmp_path):
    secret = tmp_path / "outside" / "secret.yml"
    secret.parent.mkdir()
    secret.write_text("top: secret\n")
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path / "pool")], raising=False)
    out = _compose(monkeypatch, str(secret))
    assert out["source"] == "synthesized" and "top: secret" not in str(out)


def test_a_compose_file_in_the_storage_folders_is_still_read(monkeypatch, tmp_path):
    stack = tmp_path / "pool" / "stacks" / "web"
    stack.mkdir(parents=True)
    (stack / "docker-compose.yml").write_text("services:\n  web:\n    image: nginx  # from disk\n")
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path / "pool")], raising=False)
    out = _compose(monkeypatch, os.path.join(str(stack), "docker-compose.yml"))
    assert out["source"] == "disk"


class _Socket:
    def __init__(self, token):
        self.query_params = {"ticket": token}
        self.cookies = {}
        self.headers = {}


@pytest.mark.parametrize("scopes,allowed", [(["containers:exec"], True), (["containers:manage"], False), ([], False)])
def test_the_terminal_needs_the_right_to_run_commands(monkeypatch, scopes, allowed):
    import asyncio

    session = {"user_id": "u1", "username": "ann", "role_id": "x", "scopes": scopes}
    monkeypatch.setattr("backend.auth.query_credential_allowed", lambda token: token)
    monkeypatch.setattr("backend.auth.validate_websocket_origin", lambda ws, is_cookie_auth=False: True)
    monkeypatch.setattr("backend.auth.get_current_session", lambda token: session)
    who = asyncio.run(docker_api._authenticate_ws(_Socket("t"), ("containers:exec",)))
    assert bool(who) is allowed
    if allowed:
        assert who.username == "ann"


def test_the_terminal_route_asks_for_that_right_and_logs():
    import inspect

    src = inspect.getsource(docker_api.websocket_docker_terminal)
    assert '("containers:exec",)' in src and "containers:manage" not in src
    assert '"container.terminal"' in src
