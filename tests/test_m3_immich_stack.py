"""M3: one-click Immich deploys its whole stack (server, ML, Valkey, Postgres)."""

import json
import os

from backend.services import app_catalog


class FakeDocker:
    def __init__(self):
        self.created = {}
        self.networks = set()

    def __call__(self, method, path, body=None, timeout=15.0, headers=None):
        if method == "GET" and path.startswith("/images/"):
            return 200, {}
        if method == "GET" and path.startswith("/networks/"):
            return (200, {}) if path.split("/")[-1] in self.networks else (404, {})
        if method == "POST" and path == "/networks/create":
            self.networks.add(body["Name"])
            return 201, {"Id": "net1"}
        if method == "GET" and path.startswith("/containers/"):
            name = path.split("/")[2]
            return (200, {"State": {"Running": True}}) if name in self.created else (404, {})
        if method == "POST" and path.startswith("/containers/create"):
            name = path.split("name=")[1]
            self.created[name] = body
            return 201, {"Id": f"id-{name}"}
        if method == "POST" and path.endswith("/start"):
            return 204, {}
        return 204, {}


def _env(body):
    return dict(e.split("=", 1) for e in body["Env"])


def test_immich_stack(tmp_path, monkeypatch):
    fake = FakeDocker()
    monkeypatch.setattr(app_catalog, "_docker_request", fake)
    monkeypatch.setattr(app_catalog, "check_port_available_detailed", lambda *a, **k: (True, None))
    events = list(app_catalog.stream_deploy_catalog_app("immich", storage_root=str(tmp_path)))
    assert events[-1]["step"] == "success", events[-1]
    assert set(fake.created) == {"immich", "immich_database", "immich_redis", "immich_machine-learning"}
    assert fake.networks == {"immich_net"}
    server, db = fake.created["immich"], fake.created["immich_database"]
    assert server["HostConfig"]["NetworkMode"] == "immich_net"
    assert db["NetworkingConfig"]["EndpointsConfig"]["immich_net"]["Aliases"] == ["database"]
    pw = _env(server)["DB_PASSWORD"]
    assert len(pw) >= 24 and _env(db)["POSTGRES_PASSWORD"] == pw and "{{" not in pw
    assert db["HostConfig"]["ShmSize"] == 134217728
    with open(os.path.join(tmp_path, "immich", ".zettnas-secrets.json")) as f:
        assert json.load(f)["db_password"] == pw
    # a redeploy keeps the database password
    fake2 = FakeDocker()
    monkeypatch.setattr(app_catalog, "_docker_request", fake2)
    list(app_catalog.stream_deploy_catalog_app("immich", storage_root=str(tmp_path)))
    assert _env(fake2.created["immich"])["DB_PASSWORD"] == pw
