"""COMP-15: the office suite (Nextcloud + Collabora's built-in server), set up after it starts."""

import pytest

from backend.services import app_after_start as aas
from backend.services.catalog_templates import CURATED_APP_CATALOG


class FakeDocker:
    """Answers exec create/start/inspect; `answers` gives (exit code, output) per command, in turn."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.ran = []
        self._next = {}

    def request(self, method, path, body=None, timeout=15):
        if path.endswith("/exec"):
            self.ran.append((body["Cmd"], body.get("User", "")))
            n = str(len(self.ran))
            self._next[n] = self.answers.pop(0) if self.answers else (0, "")
            return 201, {"Id": n}
        if path.startswith("/exec/") and path.endswith("/json"):
            return 200, {"ExitCode": self._next[path.split("/")[2]][0]}
        if path.startswith("/containers/") and path.endswith("/json"):
            return 200, {"Name": "/zettnas-toolkit"}
        return 404, {}

    def raw_request(self, method, path, body, timeout=0):
        out = self._next[path.split("/")[2]][1].encode()
        return 200, b"\x01\x00\x00\x00" + len(out).to_bytes(4, "big") + out


@pytest.fixture
def docker(monkeypatch):
    def make(answers=()):
        fake = FakeDocker(answers)
        monkeypatch.setattr("backend.services.docker_client.request", fake.request)
        monkeypatch.setattr("backend.services.docker_client.raw_request", fake.raw_request)
        return fake

    return make


def office():
    return next(a for a in CURATED_APP_CATALOG if a["id"] == "office-suite")


def test_the_template():
    app = office()
    assert app["join_zettnas_network"] is True
    assert app["env"]["NEXTCLOUD_ADMIN_PASSWORD"] == "{{secret:admin_password}}"
    cmds = [" ".join(s["cmd"]) for s in app["after_start"]]
    assert "status --output=json" in cmds[0] and app["after_start"][0]["tries"] > 10
    assert any("user_external" in c for c in cmds)
    assert any("--value=http://{{zettnas}}:8084/" in c for c in cmds)
    assert any("richdocumentscode{{arch}}" in c for c in cmds)
    assert all(s["user"] == "www-data" for s in app["after_start"])


def test_placeholders_and_hosts(docker):
    docker()
    ctx = aas.context("nas.local", 8093)
    assert ctx == {"host": "nas.local", "port": "8093", "zettnas": "zettnas-toolkit", "arch": ctx["arch"]}
    assert aas.fill("{{host}}:{{port}} {{secret:admin_password}} {{nope}}", ctx, {"admin_password": "pw"}) == (
        "nas.local:8093 pw {{nope}}"
    )
    assert aas.valid_host("192.168.1.5") == "192.168.1.5" and aas.valid_host("[fd00::1]") == "[fd00::1]"
    assert aas.valid_host("evil.com/x") == "" and aas.valid_host("a b") == "" and aas.valid_host(None) == ""
    assert aas.context("bad host!", 80)["host"] == "localhost"


def test_steps_run_in_order_and_retry(docker):
    fake = docker([(1, "not yet"), (0, '{"installed":false}'), (0, '{"installed":true}'), (0, "ok")])
    app = {
        "after_start": [
            {"label": "Wait", "cmd": ["occ", "status"], "user": "www-data", "expect": '"installed":true', "tries": 5},
            {"label": "Set", "cmd": ["occ", "set", "--value={{host}}"]},
        ]
    }
    slept = []
    gen = aas.run_steps(app, "office", {}, sleep=slept.append, ctx={"host": "nas"})
    events = []
    try:
        while True:
            events.append(next(gen))
    except StopIteration as stop:
        unfinished = stop.value
    assert unfinished == []
    assert [e["message"] for e in events] == ["Wait...", "Set..."]
    assert fake.ran[-1] == (["occ", "set", "--value=nas"], "")
    assert fake.ran[0][1] == "www-data" and len(slept) == 2


def test_a_step_that_never_finishes_is_named(docker):
    docker([(1, "boom"), (1, "boom")])
    app = {"after_start": [{"label": "Install the office server", "cmd": ["x"], "tries": 2, "every": 0}]}
    gen = aas.run_steps(app, "office", {}, sleep=lambda s: None, ctx={})
    with pytest.raises(StopIteration) as stop:
        while True:
            next(gen)
    assert stop.value.value == ["Install the office server"]


def test_only_built_in_templates_run_steps(docker):
    fake = docker()
    app = {"source_id": "community", "after_start": [{"cmd": ["rm", "-rf", "/"]}]}
    assert list(aas.run_steps(app, "x", {})) == []
    assert fake.ran == []


def test_exec_that_cannot_start(monkeypatch):
    monkeypatch.setattr("backend.services.docker_client.request", lambda *a, **k: (409, {"message": "not running"}))
    assert aas.exec_in("gone", ["true"]) == (None, "could not run it (409)")


def test_own_name_falls_back(monkeypatch):
    def down(*a, **k):
        raise OSError("no socket")

    monkeypatch.setattr("backend.services.docker_client.request", down)
    assert aas.zettnas_name() == "zettnas-toolkit"
    monkeypatch.setattr("backend.services.docker_client.request", lambda *a, **k: (404, {}))
    assert aas.zettnas_name() == "zettnas-toolkit"


def test_demux_plain_text():
    assert aas.demux(b"plain") == "plain"


def test_the_installer_passes_the_browser_host(monkeypatch):
    from backend.services import app_catalog

    seen = {}

    def fake_context(host, port):
        seen["ctx"] = (host, port)
        return {}

    def fake_steps(app, container, secrets, host="", port=0):
        seen["steps"] = container
        yield {"step": "configure", "percent": 95, "message": "x", "done": False}
        return ["Connecting the office server"]

    monkeypatch.setattr(aas, "context", fake_context)
    monkeypatch.setattr(aas, "run_steps", fake_steps)
    import inspect

    src = inspect.getsource(app_catalog.stream_deploy_catalog_app)
    assert "run_steps(app, service_name, secrets_map, browser_host, port)" in src
    assert '"setup_unfinished": unfinished' in src
    # no steps: Docker isn't asked for anything
    monkeypatch.undo()
    monkeypatch.setattr("backend.services.docker_client.request", lambda *a, **k: 1 / 0)
    assert list(aas.run_steps({"after_start": []}, "x", {})) == []


def test_api_takes_the_host(client, auth_headers, monkeypatch):
    seen = {}

    def fake_deploy(app_id, **kw):
        seen.update(kw)
        yield {"step": "success", "done": True}

    monkeypatch.setattr("backend.services.app_catalog.stream_deploy_catalog_app", fake_deploy)
    r = client.post(
        "/api/docker/catalog/office-suite/deploy", headers=auth_headers, json={"host": "nas.local", "host_port": 8093}
    )
    assert r.status_code == 200 and seen["browser_host"] == "nas.local"
