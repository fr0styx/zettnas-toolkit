"""The AI pack (AI-40, PERF-1): chat and search embeddings on the Intel GPU in one OpenVINO
Model Server, installed from the app catalog and set up for ZettNAS.

- One container, "zettnas-ai", on ZettNAS's own Docker network with no published port (OVMS has
  no sign-in), with a memory limit, the GPU (/dev/dri) and the NPU when there is one.
- The image is pinned by digest (catalog_digests.json, inside the signed ZettNAS image).
- On first start it downloads the preset's two models from Hugging Face (OpenVINO's own
  int4/int8 builds), writes one OVMS config serving them as zettnas-chat and zettnas-embed,
  and serves them; later starts reuse the downloads.
- No reranker: OVMS 2026.4's rerank put an invoice above the roof repair a question was about
  (bge-reranker-base) or failed outright (Qwen3-Reranker), so the pack leaves reranking alone.
- Presets follow the box: recommend() reads its memory, GPU and NPU.
- Installing never touches AI containers someone built by hand, and ZettNAS uses the pack only
  after use_pack() (the "Use it" button), which leaves anything it doesn't set alone.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.request
from collections.abc import Iterator
from typing import Any

from backend.config import logger

CONTAINER = "zettnas-ai"
IMAGE = "openvino/model_server:latest-gpu"
LABEL = "zettnas.ai-pack"
PORT = 8000
OVMS_UID = 5000  # the image runs as ovms (5000:5000); the models folder is handed to it
CHAT_NAME, EMBED_NAME = "zettnas-chat", "zettnas-embed"
EMBED_MODEL = "OpenVINO/Qwen3-Embedding-0.6B-int8-ov"  # multilingual, 1024 dimensions
EMBED_DIM = 1024

PRESETS: dict[str, dict[str, Any]] = {
    "small": {"chat": "OpenVINO/Qwen3-1.7B-int4-ov", "mem_mb": 6144, "min_ram_gb": 0},
    "standard": {"chat": "OpenVINO/Qwen3-4B-int4-ov", "mem_mb": 10240, "min_ram_gb": 12},
    "large": {"chat": "OpenVINO/Qwen3-8B-int4-ov", "mem_mb": 16384, "min_ram_gb": 32},
}

# Runs inside the container (bash): download what is missing, describe the two models in one
# config, then serve it. A download that fails leaves the container restarting, so it retries.
SCRIPT = r"""set -e
M=/models
pull() {
  if [ ! -f "$M/$1/graph.pbtxt" ]; then
    echo "zettnas-ai: downloading $1"
    /ovms/bin/ovms --pull --source_model "$1" --model_repository_path "$M" --task "$2" --target_device "$DEVICE"
  fi
}
pull "$CHAT_MODEL" text_generation
pull "$EMBED_MODEL" embeddings
rm -f "$M/config.json"
/ovms/bin/ovms --add_to_config --config_path "$M/config.json" --model_name zettnas-chat --model_path "$M/$CHAT_MODEL"
/ovms/bin/ovms --add_to_config --config_path "$M/config.json" --model_name zettnas-embed --model_path "$M/$EMBED_MODEL"
echo "zettnas-ai: serving"
exec /ovms/bin/ovms --config_path "$M/config.json" --rest_port 8000
"""


def _docker(method: str, path: str, body: dict | None = None, headers: dict | None = None):
    from backend.services.container_mutator import _docker_request

    return _docker_request(method, path, body=body, headers=headers or {})


# --- the box ---------------------------------------------------------------------------------


def box(proc: str | None = None, dev: str = "/dev") -> dict[str, Any]:
    """Memory, Intel GPU and NPU of this machine."""
    from backend.config import HOST_PROC

    ram_kb = 0
    try:
        with open(os.path.join(proc or HOST_PROC, "meminfo")) as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    ram_kb = int(line.split()[1])
                    break
    except (OSError, ValueError):
        pass
    try:
        gpu = any(n.startswith("renderD") for n in os.listdir(os.path.join(dev, "dri")))
    except OSError:
        gpu = False
    return {
        "ram_gb": round(ram_kb / 1048576, 1),
        "gpu": gpu,
        "npu": os.path.exists(os.path.join(dev, "accel", "accel0")),
        "cpus": os.cpu_count() or 1,
    }


def recommend(b: dict[str, Any]) -> dict[str, Any]:
    """The preset for this box, and why."""
    ram = float(b.get("ram_gb") or 0)
    if not b.get("gpu"):
        name, why = "small", "no Intel GPU was found, so the small chat model runs on the processor"
    elif ram >= PRESETS["large"]["min_ram_gb"]:
        name, why = "large", f"{ram:.0f} GB of memory and an Intel GPU"
    elif ram >= PRESETS["standard"]["min_ram_gb"]:
        name, why = "standard", f"{ram:.0f} GB of memory and an Intel GPU"
    else:
        name, why = "small", f"{ram:.0f} GB of memory leaves room for the small chat model only"
    p = PRESETS[name]
    return {
        "preset": name,
        "why": why,
        "chat_model": p["chat"],
        "embed_model": EMBED_MODEL,
        "mem_mb": p["mem_mb"],
        "device": "GPU" if b.get("gpu") else "CPU",
    }


# --- install ---------------------------------------------------------------------------------


def own_network() -> str | None:
    """The Docker network ZettNAS itself is on (its container's first user network)."""
    st, me = _docker("GET", f"/containers/{socket.gethostname()}/json")
    if st != 200 or not isinstance(me, dict):
        return None
    nets = list(((me.get("NetworkSettings") or {}).get("Networks") or {}).keys())
    for n in nets:
        if n not in ("host", "none"):
            return n
    return None


def render_groups(dev: str = "/dev") -> list[str]:
    """The groups that own the GPU's device files, so the model server (user ovms) may open them
    on hosts that don't leave them open to everyone."""
    try:
        names = [n for n in os.listdir(os.path.join(dev, "dri")) if n.startswith(("renderD", "card"))]
        return sorted({str(os.stat(os.path.join(dev, "dri", n)).st_gid) for n in names} - {"0"})
    except OSError:
        return []


def create_body(preset: str, models_dir: str, network: str, image: str, dev: str = "/dev") -> dict[str, Any]:
    p = PRESETS[preset]
    device = "GPU" if os.path.isdir(os.path.join(dev, "dri")) else "CPU"
    devices = [d for d in ("/dev/dri", "/dev/accel/accel0") if os.path.exists(os.path.join(dev, d[len("/dev/") :]))]
    from backend.services.image_ref import FOLLOW_TAG_LABEL

    labels = {LABEL: preset, "com.zettnas.managed": "1"}  # no Unraid label: Unraid's stop list
    if "@" in image:
        labels[FOLLOW_TAG_LABEL] = "1"
    return {
        "Image": image,
        "Entrypoint": ["/bin/bash"],
        "Cmd": ["-c", SCRIPT],
        "Env": [
            f"CHAT_MODEL={p['chat']}",
            f"EMBED_MODEL={EMBED_MODEL}",
            f"DEVICE={device}",
        ],
        "HostConfig": {
            "Binds": [f"{models_dir}:/models:rw"],
            "Devices": [{"PathOnHost": d, "PathInContainer": d, "CgroupPermissions": "rwm"} for d in devices],
            "GroupAdd": render_groups(dev),
            "Memory": int(p["mem_mb"]) * 1024 * 1024,
            "RestartPolicy": {"Name": "unless-stopped"},
            "NetworkMode": network,
        },
        "NetworkingConfig": {"EndpointsConfig": {network: {"Aliases": [CONTAINER]}}},
        "Labels": labels,
    }


def stream_install(preset: str | None = None, storage_root: str = "/mnt/user/appdata") -> Iterator[dict[str, Any]]:
    """Installs the pack, yielding progress events like the catalog's deploy."""
    from backend.services.app_catalog import _pull_image_blocking
    from backend.services.image_ref import pinned

    preset = preset or recommend(box())["preset"]
    if preset not in PRESETS:
        yield {"step": "error", "percent": 0, "message": f"Unknown preset {preset}.", "done": True}
        return
    st, old = _docker("GET", f"/containers/{CONTAINER}/json")
    if st == 200 and not ((old.get("Config") or {}).get("Labels") or {}).get(LABEL):
        yield {
            "step": "error",
            "percent": 0,
            "message": f"A container named {CONTAINER} exists and wasn't made by the AI pack; it is left alone.",
            "done": True,
        }
        return
    network = own_network()
    if not network:
        yield {"step": "error", "percent": 0, "message": "ZettNAS couldn't find its own Docker network.", "done": True}
        return
    image = pinned(IMAGE)
    yield {"step": "pull", "percent": 10, "message": f"Downloading the model server ({IMAGE})...", "done": False}
    ok, err = _pull_image_blocking(image)
    if not ok:
        yield {"step": "error", "percent": 0, "message": f"Could not download {IMAGE}: {err}", "done": True}
        return
    models_dir = os.path.join(storage_root, CONTAINER, "models")
    os.makedirs(models_dir, exist_ok=True)
    try:
        os.chown(models_dir, OVMS_UID, OVMS_UID)
    except OSError as e:
        logger.warning(f"[AI pack] could not hand {models_dir} to the model server: {e}")
    if st == 200:
        _docker("POST", f"/containers/{CONTAINER}/stop?t=20")
        _docker("DELETE", f"/containers/{CONTAINER}")
    yield {"step": "create", "percent": 60, "message": "Creating the AI container...", "done": False}
    st, resp = _docker(
        "POST",
        f"/containers/create?name={CONTAINER}",
        body=create_body(preset, models_dir, network, image),
        headers={"X-ZettNAS-Elevated": "1"},  # the GPU: a built-in app's device, like Jellyfin's
    )
    if st != 201:
        yield {"step": "error", "percent": 0, "message": f"Could not create {CONTAINER}: {resp}", "done": True}
        return
    _docker("POST", f"/containers/{resp.get('Id')}/start")
    yield {
        "step": "done",
        "percent": 100,
        "message": "The AI pack is starting. It downloads its models first (a few GB), then warms up.",
        "done": True,
        "container_name": CONTAINER,
    }


# --- status and use --------------------------------------------------------------------------


def base_url() -> str:
    return f"http://{CONTAINER}:{PORT}"


def models_ready(timeout: float = 2.0) -> bool:
    """Both models loaded and AVAILABLE."""
    try:
        with urllib.request.urlopen(f"{base_url()}/v1/config", timeout=timeout) as r:  # noqa: S310
            cfg = json.loads(r.read())
        states = [v["model_version_status"][0]["state"] for v in cfg.values() if v.get("model_version_status")]
        return len(states) >= 2 and all(s == "AVAILABLE" for s in states)
    except Exception:
        return False


def _phase(logs: str) -> str:
    """What the container says it is doing: downloading, loading or serving."""
    lines = [ln for ln in logs.splitlines() if "zettnas-ai:" in ln]
    if not lines:
        return "starting"
    last = lines[-1]
    if "serving" in last:
        return "loading"
    m = re.search(r"downloading (\S+)", last)
    return f"downloading {m.group(1)}" if m else "starting"


def status(cfg: dict[str, Any]) -> dict[str, Any]:
    """cfg: the AI settings (passed in: this module doesn't import the AI engine, which calls it)."""
    b = box()
    out: dict[str, Any] = {"box": b, "recommendation": recommend(b), "installed": False, "state": "absent"}
    st, info = _docker("GET", f"/containers/{CONTAINER}/json")
    if st != 200 or not isinstance(info, dict):
        return out
    labels = (info.get("Config") or {}).get("Labels") or {}
    if not labels.get(LABEL):
        out["state"] = "not-ours"  # someone's own container under that name: never touched
        return out
    out.update(installed=True, preset=labels.get(LABEL))
    if not (info.get("State") or {}).get("Running"):
        out["state"] = "stopped"
    elif models_ready():
        out["state"] = "ready"
    else:
        st_l, logs = _docker("GET", f"/containers/{CONTAINER}/logs?stdout=1&stderr=1&tail=200")
        out["state"] = "warming"
        out["phase"] = _phase(logs if isinstance(logs, str) else "")
    out["in_use"] = in_use(cfg)
    return out


def pack_config() -> dict[str, Any]:
    """What use_pack() sets: chat at once; embeddings through a re-index."""
    return {"llm_endpoint": f"{base_url()}/v1", "active_model": CHAT_NAME}


def reindex_request() -> dict[str, Any]:
    """The re-embed onto the pack's embedder (POST /api/ai/reindex); search keeps the old
    vectors until every chunk is done."""
    return {"embedding_model": EMBED_NAME, "embedding_dim": EMBED_DIM, "embedding_host": f"{base_url()}/v3"}


def in_use(cfg: dict[str, Any]) -> bool:
    return str(cfg.get("llm_endpoint") or "").startswith(base_url())


def use_pack(engine: Any) -> dict[str, Any]:
    """Chat through the pack (the person said so in AI settings); engine: the AI engine."""
    if not models_ready():
        raise RuntimeError("The AI pack isn't ready yet.")
    return engine.update_config(pack_config())


# --- idle stop, and back on the first question --------------------------------------------------
# The pack's models hold several GB. After idle_unload_minutes (AI settings, default 15) without
# a question, a search or indexing, ZettNAS stops the container; the next request that needs it
# starts it again and waits while it warms up (B14 gate: under 300 MB held while idle).

WARM_TIMEOUT_SECS = 180.0
RUNNING_CACHE_SECS = 15.0
NOT_READY_SECS = 60.0  # a pack that didn't come up isn't waited for again for this long (NAI-1)
_LAST_USE = {"at": time.monotonic()}
_RUNNING = {"at": -1e9, "value": False}
_STARTED = {"at": -1e9}
_NOT_READY = {"at": -1e9}


def warming(clock=time.monotonic) -> bool:
    """The pack was started for a request and hasn't answered yet: a search says "warming up"."""
    return clock() - _STARTED["at"] < WARM_TIMEOUT_SECS and not _RUNNING["value"]


def mark_used() -> None:
    _LAST_USE["at"] = time.monotonic()


def _ours_running() -> tuple[bool, bool]:
    """(the pack's own container exists, it runs), cached for a few seconds."""
    now = time.monotonic()
    st, info = _docker("GET", f"/containers/{CONTAINER}/json")
    ours = st == 200 and isinstance(info, dict) and bool(((info.get("Config") or {}).get("Labels") or {}).get(LABEL))
    running = ours and bool((info.get("State") or {}).get("Running"))
    _RUNNING.update(at=now, value=running)
    return ours, running


def wake_for(url: str | None, sleep=time.sleep, clock=time.monotonic, wait: float | None = None) -> bool:
    """Before a request to url: when it is the pack and the pack was stopped for idling, start it
    and wait until its models are loaded, at most `wait` seconds (a search passes what its own
    deadline leaves; indexing waits the full warm-up). True when the pack answers (or url isn't
    the pack). A search never waits minutes for a pack that is warming up or broken (NAI-1)."""
    if not url or f"//{CONTAINER}:" not in url:
        return True
    mark_used()
    if clock() - _RUNNING["at"] < RUNNING_CACHE_SECS and _RUNNING["value"]:
        return True
    limit = WARM_TIMEOUT_SECS if wait is None else max(0.0, min(wait, WARM_TIMEOUT_SECS))
    if wait is not None and clock() - _NOT_READY["at"] < NOT_READY_SECS:
        limit = 0.0  # it didn't come up a moment ago: don't hold this search for it
    ours, running = _ours_running()
    if not ours:
        return True  # not ours to start: the request goes as it would have
    if not running:
        logger.info("[AI pack] starting the AI container for a request (warming up)")
        _docker("POST", f"/containers/{CONTAINER}/start")
        _STARTED["at"] = clock()
    deadline = clock() + limit
    while True:
        if models_ready():
            _RUNNING.update(at=clock(), value=True)
            return True
        if clock() + 2.0 > deadline:
            break
        sleep(2.0)
    if limit >= WARM_TIMEOUT_SECS:
        _NOT_READY["at"] = clock()  # waited the whole warm-up: broken, not warming
    return False


def idle_tick(cfg: dict[str, Any], indexing: bool = False, clock=time.monotonic) -> bool:
    """Stops the pack's container when ZettNAS uses it and nothing asked for it for the idle
    time. True when it stopped it."""
    try:
        idle_secs = max(1, int(cfg.get("idle_unload_minutes") or 15)) * 60
    except (TypeError, ValueError):
        idle_secs = 15 * 60
    if indexing or not in_use(cfg) or clock() - _LAST_USE["at"] < idle_secs:
        return False
    ours, running = _ours_running()
    if not (ours and running):
        return False
    logger.info("[AI pack] idle: stopping the AI container until the next question")
    _docker("POST", f"/containers/{CONTAINER}/stop?t=20")
    _RUNNING.update(at=clock(), value=False)
    return True
