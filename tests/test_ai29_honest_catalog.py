"""AI-29: the model catalog says what is true. No built-in "NPU engine" that has no inference
code, licences on every model, no guessed speeds, and devices as the AI server reports them."""

import json

import pytest

from backend.services import ai_device
from backend.services import media_engine as me

CPU = {"has_npu": False, "has_igpu": False}
IGPU = {"has_npu": False, "has_igpu": True, "active_tier": 2, "device_label": "Intel Graphics"}
NPU_IGPU = {
    "has_npu": True,
    "has_igpu": True,
    "active_tier": 1,
    "device_label": "Intel AI Boost NPU",
    "secondary_gpu": "Intel Graphics",
}
DGPU = {"has_cuda": True, "has_npu": False, "active_tier": 2, "device_label": "RTX 4090"}


def test_the_catalog_file_is_honest():
    data = me.model_catalog()
    models = data["models"] + data["large_models"]
    ids = {m["id"] for m in models}
    assert "builtin-npu" not in ids
    for m in models:
        assert m["license"] and m["license_kind"] in ("open", "community", "non_commercial"), m["id"]
        assert m["runtime"] in ("ollama", "ovms")
        assert m["classes"] and set(m["classes"]) <= {"cpu", "igpu", "npu", "dgpu"}
        if m["runtime"] == "ollama":
            assert "npu" not in m["classes"], f"{m['id']}: Ollama doesn't run on the NPU"
        text = json.dumps(m).lower()
        assert "tok/s" not in text and "npu int4" not in text and "silent" not in text
    qwen = next(m for m in models if m["ollama_tag"] == "qwen2.5:3b")
    assert qwen["license_kind"] == "non_commercial"


@pytest.mark.parametrize("accel,cls", [(CPU, "cpu"), (IGPU, "igpu"), (NPU_IGPU, "npu"), (DGPU, "dgpu")])
def test_hardware_class(accel, cls):
    assert me.hardware_class(accel) == cls


def test_where_a_model_would_run():
    hw = {
        "has_npu": True,
        "has_gpu": True,
        "has_dgpu": False,
        "npu_label": "NPU X",
        "gpu_label": "GPU Y",
        "class": "npu",
    }
    ollama = me.catalog_entry({"id": "a", "hf_repo": "x/a", "runtime": "ollama", "classes": ["cpu", "igpu"]}, hw)
    assert ollama["target_accelerator"] == "GPU" and ollama["target_device"] == "GPU Y"
    assert ollama["recommended_for_npu"] is False and ollama["est_speed"] is None
    assert ollama["suits_this_box"] is False
    ovms = me.catalog_entry(
        {"id": "b", "hf_repo": "OpenVINO/b", "runtime": "ovms", "classes": ["npu"], "license_kind": "open"}, hw
    )
    assert (
        ovms["target_accelerator"] == "NPU" and ovms["recommended_for_npu"] is True and ovms["suits_this_box"] is True
    )
    big = me.catalog_entry(
        {"id": "c", "hf_repo": "x/c", "runtime": "ollama", "requires_dgpu_vram_gb": 24, "classes": ["dgpu"]}, hw
    )
    assert big["target_accelerator"] == "Discrete GPU" and "24 GB" in big["target_device"]
    cpu_hw = dict(hw, has_npu=False, has_gpu=False, **{"class": "cpu"})
    research = me.catalog_entry(
        {"id": "d", "hf_repo": "x/d", "runtime": "ollama", "classes": ["cpu"], "license_kind": "non_commercial"}, cpu_hw
    )
    assert research["target_accelerator"] == "CPU" and research["license_note"].startswith("Research licence")
    dgpu_hw = dict(hw, has_dgpu=True)
    assert (
        me.catalog_entry({"id": "e", "hf_repo": "x/e", "requires_dgpu_vram_gb": 24}, dgpu_hw)["target_accelerator"]
        == "GPU"
    )


@pytest.mark.parametrize("accel", [CPU, IGPU, NPU_IGPU, DGPU])
def test_recommendations_make_no_claims_they_cant_back(accel):
    recs = me.build_llm_recommendations(
        accel=accel, ram_gb=16, active_model="qwen3:4b", include_incompatible=True, removed_models=[]
    )
    assert recs["hardware_profile"]["hardware_class"] == me.hardware_class(accel)
    text = json.dumps(recs).lower()
    assert "builtin-npu" not in text and "tok/s" not in text and "<8w" not in text
    for m in recs["models"]:
        assert m["estimated_speed"] is None and "power_profile" not in m
        if m.get("runtime") == "ollama":
            assert m["target_accelerator"] != "NPU"
    best = [m for m in recs["models"] if m["fit_status"] == "best_match"]
    if accel is NPU_IGPU:
        assert any(m["runtime"] == "ovms" for m in best)


def test_little_memory_gets_no_chat_recommendation():
    recs = me.build_llm_recommendations(accel=CPU, ram_gb=4, active_model="", removed_models=[])
    assert recs["hardware_profile"]["primary_recommendation"] == ""


# --- the device the server reports ---


def test_endpoint_kind():
    assert ai_device.endpoint_kind("http://ovms:8000/v3") == "ovms"
    assert ai_device.endpoint_kind("http://x:8000/v1/chat/completions") == "ovms"
    assert ai_device.endpoint_kind("http://ollama:11434") == "ollama"
    assert ai_device.endpoint_kind(None) == "ollama"


def test_ollama_reports_gpu_memory():
    ps = {
        "models": [
            {"name": "qwen3:4b", "size": 100, "size_vram": 100},
            {"name": "big:7b", "size": 100, "size_vram": 40},
            {"name": "cpu:1b", "size": 50, "size_vram": 0},
        ]
    }
    get = lambda url: ps  # noqa: E731
    assert ai_device.ollama_device("http://o:11434/api/chat", "qwen3:4b", get) == "GPU"
    assert ai_device.ollama_device("http://o:11434", "big:7b", get) == "GPU+CPU"
    assert ai_device.ollama_device("http://o:11434", "cpu:1b", get) == "CPU"
    assert ai_device.ollama_device("http://o:11434", "absent:1b", get) is None
    latest = {"models": [{"name": "qwen3:latest", "size": 1, "size_vram": 1}]}
    assert ai_device.ollama_device("http://o:11434", "qwen3", lambda url: latest) == "GPU"

    def down(url):
        raise OSError("refused")

    assert ai_device.ollama_device("http://o:11434", "qwen3:4b", down) is None


@pytest.mark.parametrize(
    "cfg,device",
    [
        ({"Cmd": ["--model_path", "/m", "--target_device", "GPU"]}, "GPU"),
        ({"Cmd": ["--target_device=npu"]}, "NPU"),
        ({"Entrypoint": ["/ovms/bin/ovms"], "Cmd": ["--target_device", "$DEVICE"], "Env": ["DEVICE=GPU"]}, "GPU"),
        ({"Cmd": ["--config_path", "/c.json"], "Env": ["TARGET_DEVICE=AUTO"]}, "AUTO"),
        ({"Cmd": ["--config_path", "/c.json"]}, None),
    ],
)
def test_ovms_device_from_its_container(cfg, device):
    assert ai_device.ovms_device("http://ovms:8000/v3", inspect=lambda name: {"Config": cfg}) == device


def test_ovms_device_without_docker_or_container():
    assert ai_device.ovms_device("http://ovms:8000/v3", inspect=lambda name: None) is None
    assert ai_device.ovms_device("not a url", inspect=lambda name: {}) is None

    def broken(name):
        raise OSError("no socket")

    assert ai_device.ovms_device("http://ovms:8000/v3", inspect=broken) is None


def test_ovms_device_default_inspect_handles_docker_errors(monkeypatch):
    from backend.services import docker_client

    def missing(*a, **k):
        raise docker_client.DockerNotFound(404, "No such container", "/containers/ovms/json")

    monkeypatch.setattr(docker_client, "call", missing)
    assert ai_device.ovms_device("http://ovms:8000/v3") is None
    monkeypatch.setattr(docker_client, "call", lambda *a, **k: {"Config": {"Cmd": ["--target_device", "CPU"]}})
    assert ai_device.ovms_device("http://ovms:8000/v3") == "CPU"


def test_device_for_is_cached(monkeypatch):
    ai_device._CACHE.clear()
    calls = []
    monkeypatch.setattr(ai_device, "ovms_device", lambda ep: calls.append(ep) or "GPU")
    monkeypatch.setattr(ai_device, "ollama_device", lambda ep, m: calls.append(m) or "CPU")
    assert ai_device.device_for("http://ovms:8000/v3", "m") == "GPU"
    assert ai_device.device_for("http://ovms:8000/v3", "m") == "GPU"
    assert ai_device.device_for("http://ollama:11434", "q") == "CPU"
    assert ai_device.device_for(None, "q") is None
    assert len(calls) == 2


def test_device_info_records():
    host = {"active_tier": 1, "device_label": "Intel AI Boost NPU", "secondary_gpu": "Intel Graphics"}
    assert ai_device.device_info("ovms", "NPU", host)["name"] == "Intel AI Boost NPU"
    gpu = ai_device.device_info("ollama", "GPU+CPU", host)
    assert gpu["tier_code"] == "GPU_TIER_2" and "part of the model on the CPU" in gpu["device_label"]
    assert ai_device.device_info("ollama", "GPU", {})["name"] == "GPU"
    cpu = ai_device.device_info("ollama", "CPU", host)
    assert cpu["tier_code"] == "CPU_TIER_3" and cpu["has_gpu"] is False
    assert ai_device.device_info("ovms", "AUTO", host)["device_label"] == "AUTO"
    unknown = ai_device.device_info("ollama", None)
    assert unknown["active_tier"] == 0 and unknown["device_source"] == "unknown"


def test_telemetry_says_not_reported(monkeypatch):
    from backend.services import chat_llm_runtime as rt

    monkeypatch.setattr(rt.ai_device, "device_for", lambda ep, m: None)
    monkeypatch.setattr(rt, "_chat_endpoint", lambda m: "http://ollama:11434")
    tel = rt.build_llm_execution_telemetry(active_model="qwen3:4b", accel=None)
    assert tel["hardware_tier"] == "Not reported"
    assert "Intel Arc" not in json.dumps(tel)


def test_chat_endpoint_prefers_the_configured_one(monkeypatch):
    from backend.services import chat_llm_runtime as rt

    class Engine:
        def __init__(self, ep):
            self.ep = ep

        def get_config(self):
            return {"llm_endpoint": self.ep}

    core = rt._core()
    monkeypatch.setattr(core, "get_rag_engine", lambda: Engine("http://ovms:8000/v3"))
    assert rt._chat_endpoint("m") == "http://ovms:8000/v3"
    monkeypatch.setattr(core, "get_rag_engine", lambda: Engine(""))
    monkeypatch.setitem(core._ACTIVE_ENDPOINT_CACHE, "m:", ("ollama_local", "http://ollama-host:11434/api/chat", 0))
    assert rt._chat_endpoint("m") == "http://ollama-host:11434/api/chat"
    assert rt._chat_endpoint("other") is None


@pytest.mark.parametrize(
    "repo,accel,acc",
    [
        ("Qwen/Qwen3-4B-GGUF", NPU_IGPU, "GPU"),  # an Ollama model on an NPU box still runs on the GPU
        ("Qwen/Qwen3-4B-GGUF", CPU, "CPU"),
        ("Qwen/Qwen2.5-32B-Instruct-GGUF", IGPU, "dGPU (24GB+ VRAM)"),
        ("meta-llama/Llama-3.3-70B-Instruct-GGUF", DGPU, "Multi-GPU (48GB+ VRAM)"),
    ],
)
def test_hugging_face_results_make_no_npu_or_speed_claims(repo, accel, acc):
    item = {"id": repo, "tags": ["gguf"], "downloads": 10, "likes": 1, "createdAt": "2026-01-02T00:00:00Z"}
    m = me._format_hf_api_item(item, accel, 32.0, "")
    assert m["target_accelerator"] == acc
    assert m["est_speed"] is None and m["estimated_speed"] is None and m["power_profile"] is None


def test_runtime_lookup_survives_missing_config_and_detection(monkeypatch):
    from backend.services import chat_llm_runtime as rt

    core = rt._core()

    def broken():
        raise RuntimeError("no engine")

    monkeypatch.setattr(core, "get_rag_engine", broken)
    assert rt._chat_endpoint("nothing-cached") is None

    def no_detection():
        raise OSError("no /dev")

    monkeypatch.setattr(rt, "detect_hardware_accelerator", no_detection)
    monkeypatch.setattr(rt.ai_device, "device_for", lambda ep, m: "CPU")
    res = rt.resolve_model_runtime_accelerator("qwen3:4b", None, endpoint="http://ollama:11434")
    assert res["tier_code"] == "CPU_TIER_3"
