"""B14 AI-40: the Private AI pack, its presets, its installer, and its idle stop."""

import json
import os

import pytest

from backend.services import ai_pack


def _box_files(tmp_path, ram_kb, gpu=True, npu=False):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text(f"MemTotal:       {ram_kb} kB\nMemFree: 1 kB\n")
    dev = tmp_path / "dev"
    (dev / "dri").mkdir(parents=True)
    if gpu:
        (dev / "dri" / "renderD128").write_text("")
    if npu:
        (dev / "accel").mkdir()
        (dev / "accel" / "accel0").write_text("")
    return str(proc), str(dev)


@pytest.mark.parametrize(
    ("ram_gb", "gpu", "preset"),
    [(64, True, "large"), (32, True, "large"), (16, True, "standard"), (8, True, "small"), (64, False, "small")],
)
def test_the_preset_follows_the_box(tmp_path, ram_gb, gpu, preset):
    proc, dev = _box_files(tmp_path, ram_gb * 1048576, gpu=gpu)
    b = ai_pack.box(proc, dev)
    assert b["ram_gb"] == ram_gb and b["gpu"] is gpu
    r = ai_pack.recommend(b)
    assert r["preset"] == preset and r["why"]
    assert r["device"] == ("GPU" if gpu else "CPU")


def test_the_container_has_no_port_a_memory_limit_and_its_own_label(tmp_path):
    _, dev = _box_files(tmp_path, 16 * 1048576, gpu=True, npu=True)
    body = ai_pack.create_body(
        "standard", "/data/zettnas-ai/models", "zettnas_default", "img@sha256:" + "a" * 64, dev=dev
    )
    hc = body["HostConfig"]
    assert "PortBindings" not in hc and "ExposedPorts" not in body
    assert hc["NetworkMode"] == "zettnas_default"
    assert body["NetworkingConfig"]["EndpointsConfig"]["zettnas_default"]["Aliases"] == ["zettnas-ai"]
    assert hc["Memory"] == 10240 * 1024 * 1024
    assert [d["PathOnHost"] for d in hc["Devices"]] == ["/dev/dri", "/dev/accel/accel0"]
    assert body["Labels"][ai_pack.LABEL] == "standard"
    assert not any(k.startswith("net.unraid") for k in body["Labels"])  # Unraid would stop it on shutdown
    assert "CHAT_MODEL=OpenVINO/Qwen3-4B-int4-ov" in body["Env"] and "DEVICE=GPU" in body["Env"]
    assert body["Cmd"][0] == "-c" and "--add_to_config" in body["Cmd"][1]


class FakeDocker:
    def __init__(self, existing=None, running=True):
        self.calls = []
        self.existing = existing
        self.running = running

    def __call__(self, method, path, body=None, headers=None):
        self.calls.append((method, path, body))
        if path == "/containers/zettnas-ai/json":
            if self.existing is None:
                return 404, {}
            return 200, {"Config": {"Labels": self.existing}, "State": {"Running": self.running}}
        if path.startswith("/containers/") and path.endswith("/json"):  # ZettNAS itself
            return 200, {"NetworkSettings": {"Networks": {"zettnas_default": {}}}}
        if path.startswith("/containers/create"):
            return 201, {"Id": "new"}
        return 204, {}


def test_install_creates_and_starts_the_pack(tmp_path, monkeypatch):
    d = FakeDocker()
    monkeypatch.setattr(ai_pack, "_docker", d)
    monkeypatch.setattr("backend.services.app_catalog._pull_image_blocking", lambda image: (True, ""))
    monkeypatch.setattr(os, "chown", lambda *a: None)
    events = list(ai_pack.stream_install("small", str(tmp_path)))
    assert events[-1]["step"] == "done"
    created = [c for c in d.calls if c[1].startswith("/containers/create")]
    assert created and created[0][2]["Labels"][ai_pack.LABEL] == "small"
    assert ("POST", "/containers/new/start", None) in d.calls
    assert os.path.isdir(tmp_path / "zettnas-ai" / "models")


def test_install_leaves_someone_elses_container_alone(tmp_path, monkeypatch):
    d = FakeDocker(existing={"maintainer": "me"})
    monkeypatch.setattr(ai_pack, "_docker", d)
    events = list(ai_pack.stream_install("small", str(tmp_path)))
    assert events[-1]["step"] == "error" and "left alone" in events[-1]["message"]
    assert not any(c[0] in ("POST", "DELETE") for c in d.calls)
    assert list(ai_pack.stream_install("huge", str(tmp_path)))[-1]["step"] == "error"


def test_status_says_what_the_pack_is_doing(monkeypatch):
    monkeypatch.setattr(ai_pack, "box", lambda: {"ram_gb": 16, "gpu": True, "npu": False})
    monkeypatch.setattr(ai_pack, "in_use", lambda cfg: False)
    monkeypatch.setattr(ai_pack, "_docker", FakeDocker())
    assert ai_pack.status({})["state"] == "absent"
    monkeypatch.setattr(ai_pack, "_docker", FakeDocker(existing={"x": "1"}))
    assert ai_pack.status({})["state"] == "not-ours"
    monkeypatch.setattr(ai_pack, "_docker", FakeDocker(existing={ai_pack.LABEL: "standard"}, running=False))
    assert ai_pack.status({})["state"] == "stopped"
    monkeypatch.setattr(ai_pack, "models_ready", lambda timeout=2.0: True)
    monkeypatch.setattr(ai_pack, "_docker", FakeDocker(existing={ai_pack.LABEL: "standard"}))
    assert ai_pack.status({})["state"] == "ready"


def test_the_warm_up_phase_comes_from_the_log():
    assert (
        ai_pack._phase("x\nzettnas-ai: downloading OpenVINO/Qwen3-4B-int4-ov\n")
        == "downloading OpenVINO/Qwen3-4B-int4-ov"
    )
    assert ai_pack._phase("zettnas-ai: serving\n") == "loading"
    assert ai_pack._phase("") == "starting"


def test_using_the_pack_sets_chat_and_asks_for_a_reindex(monkeypatch):
    updates = []
    monkeypatch.setattr(ai_pack, "models_ready", lambda timeout=2.0: True)

    class Engine:
        def update_config(self, u):
            updates.append(u)
            return u

    cfg = ai_pack.use_pack(Engine())
    assert cfg["llm_endpoint"] == "http://zettnas-ai:8000/v1" and cfg["active_model"] == "zettnas-chat"
    assert "rerank_endpoint" not in cfg  # OVMS's rerank ranked badly in testing: left alone
    assert "embedding_model" not in cfg  # the embeddings move through a re-index, not at once
    assert ai_pack.reindex_request()["embedding_host"] == "http://zettnas-ai:8000/v3"
    assert ai_pack.in_use(cfg)
    monkeypatch.setattr(ai_pack, "models_ready", lambda timeout=2.0: False)
    with pytest.raises(RuntimeError):
        ai_pack.use_pack(Engine())


def test_idle_stops_it_and_the_next_question_starts_it(monkeypatch):
    d = FakeDocker(existing={ai_pack.LABEL: "standard"}, running=True)
    monkeypatch.setattr(ai_pack, "_docker", d)
    cfg = {"llm_endpoint": "http://zettnas-ai:8000/v1", "idle_unload_minutes": 15}
    now = [1000.0]
    clock = lambda: now[0]  # noqa: E731
    ai_pack._LAST_USE["at"] = 1000.0
    assert not ai_pack.idle_tick(cfg, clock=clock)  # just used
    now[0] += 16 * 60
    assert not ai_pack.idle_tick(cfg, indexing=True, clock=clock)  # indexing still needs it
    assert ai_pack.idle_tick(cfg, clock=clock)
    assert ("POST", "/containers/zettnas-ai/stop?t=20", None) in d.calls
    assert not ai_pack.idle_tick({"llm_endpoint": "http://ovms:8000/v1"}, clock=clock)  # not using the pack

    d.running = False
    ready = iter([False, True])
    monkeypatch.setattr(ai_pack, "models_ready", lambda timeout=2.0: next(ready))
    assert ai_pack.wake_for("http://zettnas-ai:8000/v3/embeddings", sleep=lambda s: None, clock=clock)
    assert ("POST", "/containers/zettnas-ai/start", None) in d.calls
    assert ai_pack.wake_for("http://ollama:11434/api/embed")  # not the pack: nothing to do


def test_the_api_reports_installs_and_uses(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ai_pack, "status", lambda cfg: {"state": "absent", "installed": False})
    assert client.get("/api/v1/ai/pack", headers=auth_headers).json()["state"] == "absent"
    monkeypatch.setattr(ai_pack, "stream_install", lambda preset, root: iter([{"step": "done", "preset": preset}]))
    r = client.post("/api/v1/ai/pack/install", json={"preset": "small"}, headers=auth_headers)
    assert json.loads(r.text.strip().splitlines()[-1]) == {"step": "done", "preset": "small"}
    r = client.post("/api/v1/docker/catalog/ai-pack/deploy", json={}, headers=auth_headers)
    assert json.loads(r.text.strip().splitlines()[-1])["step"] == "done"  # the catalog goes to the same installer
    monkeypatch.setattr(ai_pack, "use_pack", lambda engine: (_ for _ in ()).throw(RuntimeError("not ready")))
    assert client.post("/api/v1/ai/pack/use", headers=auth_headers).status_code == 409
    monkeypatch.setattr(ai_pack, "use_pack", lambda engine: {"llm_endpoint": "http://zettnas-ai:8000/v1"})
    assert (
        client.post("/api/v1/ai/pack/use", headers=auth_headers).json()["reindex"]["embedding_model"] == "zettnas-embed"
    )
