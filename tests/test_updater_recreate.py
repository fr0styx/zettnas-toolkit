"""Self-updater recreate step (OPS-01/02/04)."""

import pytest

from backend.services import self_updater

OLD_IMAGE_CFG = {
    "Env": ["PATH=/usr/bin", "PYTHONUNBUFFERED=1"],
    "Cmd": ["python3", "app.py"],
    "Healthcheck": {"Test": ["CMD", "old-check"]},
    "WorkingDir": "/app",
    "Labels": {"org.opencontainers.image.version": "1.9.1", "maintainer": "x"},
}

INSPECT = {
    "Id": "abcdef1234567890",
    "Image": "sha256:old",
    "Config": {
        "Hostname": "abcdef123456",
        "Env": ["PATH=/usr/bin", "PYTHONUNBUFFERED=1", "WEB_PASSWORD=secret", "TZ=UTC"],
        "Cmd": ["python3", "app.py"],
        "Healthcheck": {"Test": ["CMD", "old-check"]},
        "WorkingDir": "/app",
        "Labels": {"org.opencontainers.image.version": "1.9.1", "maintainer": "x", "net.unraid.docker.icon": "i"},
    },
    "HostConfig": {"Binds": ["/mnt/user/appdata/z:/app/data"], "NetworkMode": "br0"},
    "NetworkSettings": {
        "Networks": {
            "br0": {"IPAMConfig": {"IPv4Address": "10.40.30.20"}, "Aliases": ["abcdef123456", "zettnas"]},
            "proxynet": {"Aliases": ["zettnas"]},
        }
    },
}


def test_recreate_plan_keeps_user_settings_only():
    body, extra = self_updater.build_recreate_plan(INSPECT, OLD_IMAGE_CFG, "ghcr.io/x:new")
    assert body["Image"] == "ghcr.io/x:new"
    assert body["Env"] == ["WEB_PASSWORD=secret", "TZ=UTC"]
    for key in ("Cmd", "Healthcheck", "WorkingDir", "Hostname"):
        assert key not in body
    assert body["Labels"] == {"net.unraid.docker.icon": "i"}
    assert body["HostConfig"]["Binds"] == ["/mnt/user/appdata/z:/app/data"]
    ep = body["NetworkingConfig"]["EndpointsConfig"]["br0"]
    assert ep["IPAMConfig"] == {"IPv4Address": "10.40.30.20"}
    assert ep["Aliases"] == ["zettnas"]
    assert extra == {"proxynet": {"Aliases": ["zettnas"]}}


def test_user_overridden_command_is_kept():
    inspect = {**INSPECT, "Config": {**INSPECT["Config"], "Cmd": ["python3", "app.py", "--debug"]}}
    body, _ = self_updater.build_recreate_plan(inspect, OLD_IMAGE_CFG, "img")
    assert body["Cmd"] == ["python3", "app.py", "--debug"]


class FakeDocker:
    def __init__(self, health_states=("healthy",), create_status=201, start_status=204):
        self.calls = []
        self.health = list(health_states)
        self.create_status = create_status
        self.start_status = start_status

    def __call__(self, method, path, body=None, timeout=30.0):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/containers/zettnas-toolkit/json":
            return 200, INSPECT
        if method == "GET" and path.startswith("/images/"):
            return 200, {"Config": OLD_IMAGE_CFG}
        if method == "POST" and path.startswith("/containers/create"):
            return (self.create_status, {"Id": "new123456789"}) if self.create_status == 201 else (500, "bad")
        if method == "POST" and path == "/containers/new123456789/start":
            return self.start_status, {}
        if method == "GET" and path == "/containers/new123456789/json":
            status = self.health.pop(0) if len(self.health) > 1 else self.health[0]
            if status == "exited":
                return 200, {"State": {"Running": False, "Status": "exited", "ExitCode": 1}}
            return 200, {"State": {"Running": True, "Health": {"Status": status}}}
        return 204, {}

    def paths(self):
        return [(m, p) for m, p, _ in self.calls]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(self_updater.time, "sleep", lambda s: None)


def _run(monkeypatch, fake):
    monkeypatch.setattr(self_updater, "_docker_request", fake)
    self_updater.apply_update_from_helper("zettnas-toolkit", "ghcr.io/x:new", delay=0.0)


def test_success_waits_for_health_then_removes_rollback(monkeypatch):
    fake = FakeDocker(health_states=("starting", "starting", "healthy"))
    _run(monkeypatch, fake)
    paths = fake.paths()
    assert ("POST", "/networks/proxynet/connect") in paths
    health_checks = [i for i, p in enumerate(paths) if p == ("GET", "/containers/new123456789/json")]
    delete_rollback = paths.index(("DELETE", "/containers/zettnas-toolkit-rollback?v=false"))
    assert len(health_checks) == 3 and delete_rollback > health_checks[-1]


@pytest.mark.parametrize("state", ["unhealthy", "exited"])
def test_unhealthy_new_container_rolls_back(monkeypatch, state):
    fake = FakeDocker(health_states=(state,))
    with pytest.raises(SystemExit):
        _run(monkeypatch, fake)
    paths = fake.paths()
    assert ("DELETE", "/containers/new123456789?force=true") in paths
    assert ("POST", "/containers/zettnas-toolkit-rollback/rename?name=zettnas-toolkit") in paths
    assert ("DELETE", "/containers/zettnas-toolkit-rollback?v=false") not in paths


def test_create_failure_rolls_back(monkeypatch):
    fake = FakeDocker(create_status=500)
    with pytest.raises(SystemExit):
        _run(monkeypatch, fake)
    assert ("POST", "/containers/zettnas-toolkit-rollback/rename?name=zettnas-toolkit") in fake.paths()


def test_start_failure_rolls_back(monkeypatch):
    fake = FakeDocker(start_status=500)
    with pytest.raises(SystemExit):
        _run(monkeypatch, fake)
    paths = fake.paths()
    assert ("DELETE", "/containers/new123456789?force=true") in paths
    assert ("POST", "/containers/zettnas-toolkit/start") in paths
