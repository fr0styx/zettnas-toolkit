"""Which device a chat model really runs on, as its server reports it (AI-29).

Ollama says how much of a loaded model sits in GPU memory (/api/ps); it never uses the NPU.
OpenVINO Model Server runs a model on the device it was started with (--target_device, or the
AI pack's DEVICE variable), read from its container. Nothing is guessed from a model's name:
when the server doesn't say, the answer is "not reported".
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

CACHE_SECONDS = 60.0
_CACHE: dict[tuple, tuple[float, str | None]] = {}


def _cached(key: tuple, compute: Callable[[], str | None]) -> str | None:
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = compute()
    _CACHE[key] = (now, value)
    return value


def endpoint_kind(endpoint: str | None) -> str:
    """ovms for OpenAI-style endpoints (/v1, /v3), otherwise ollama."""
    ep = (endpoint or "").rstrip("/")
    return "ovms" if ep.endswith(("/v1", "/v3")) or "/v1/" in ep or "/v3/" in ep else "ollama"


def _base(endpoint: str) -> str:
    u = urllib.parse.urlsplit(endpoint)
    return f"{u.scheme}://{u.netloc}"


def _get_json(url: str, timeout: float = 1.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "ZettNAS-Toolkit/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (a configured local AI server)
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def ollama_device(endpoint: str, model: str, get: Callable[[str], Any] = _get_json) -> str | None:
    """GPU, GPU+CPU or CPU for a loaded model; None when it isn't loaded or Ollama doesn't answer."""
    try:
        data = get(_base(endpoint) + "/api/ps")
    except (OSError, ValueError):
        return None
    want = (model or "").lower()
    for m in (data or {}).get("models") or []:
        names = {str(m.get("name") or "").lower(), str(m.get("model") or "").lower()}
        if want and want not in names and f"{want}:latest" not in names:
            continue
        size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
        if vram <= 0:
            return "CPU"
        return "GPU+CPU" if size and vram < size else "GPU"  # no size reported: all of it is on the GPU
    return None


def _device_in(args: list[str], env: list[str]) -> str | None:
    for i, a in enumerate(args):
        if a.startswith("--target_device="):
            return a.split("=", 1)[1] or None
        if a == "--target_device" and i + 1 < len(args) and not args[i + 1].startswith("$"):
            return args[i + 1]  # "$DEVICE" comes from the environment, read below
    for item in env:
        key, _, value = item.partition("=")
        if key in ("DEVICE", "TARGET_DEVICE") and value:
            return value
    return None


def _docker_inspect(name: str) -> Any:
    from backend.services import docker_client

    try:
        return docker_client.call("GET", f"/containers/{urllib.parse.quote(name)}/json", timeout=3.0)
    except docker_client.DockerError:
        return None  # no Docker, or no container by that name: not reported


def ovms_device(endpoint: str, inspect: Callable[[str], Any] | None = None) -> str | None:
    """The device OpenVINO Model Server was started with, from its container; None if unknown."""
    host = urllib.parse.urlsplit(endpoint).hostname or ""
    if not host:
        return None
    try:
        info = (inspect or _docker_inspect)(host)
    except (OSError, ValueError):
        return None
    cfg = (info or {}).get("Config") or {}
    args = [str(a) for a in (cfg.get("Entrypoint") or []) + (cfg.get("Cmd") or [])]
    device = _device_in(args, [str(e) for e in cfg.get("Env") or []])
    return device.upper() if device else None


def device_for(endpoint: str | None, model: str) -> str | None:
    """The reported device for this endpoint and model (cached for a minute)."""
    if not endpoint:
        return None
    if endpoint_kind(endpoint) == "ovms":
        return _cached(("ovms", _base(endpoint)), lambda: ovms_device(endpoint))
    return _cached(("ollama", _base(endpoint), model), lambda: ollama_device(endpoint, model))


def device_info(kind: str, device: str | None, host_accel: dict[str, Any] | None = None) -> dict[str, Any]:
    """The accelerator record the chat telemetry shows, from a reported device."""
    host = host_accel or {}
    engine = "OpenVINO Model Server" if kind == "ovms" else "Ollama"
    dev = (device or "").upper()
    gpu_name = (
        host.get("secondary_gpu") or (host.get("device_label") if host.get("active_tier") == 2 else None) or "GPU"
    )
    npu_name = (host.get("device_label") if host.get("active_tier") == 1 else None) or "NPU"
    if "NPU" in dev:
        tier, name, label = 1, "NPU", npu_name
    elif "GPU" in dev:
        tier, name, label = 2, "GPU", gpu_name
        if dev == "GPU+CPU":
            label = f"{gpu_name} (part of the model on the CPU)"
    elif dev:
        tier, name, label = 3, "CPU", "CPU" if dev == "CPU" else dev
    else:
        return {
            "active_tier": 0,
            "tier_number": 0,
            "tier": "UNKNOWN",
            "tier_code": "UNKNOWN",
            "tier_name": "Not reported",
            "name": "Not reported",
            "device_label": f"Not reported by {engine}",
            "runtime_engine": engine,
            "device_source": "unknown",
            "has_npu": False,
            "has_gpu": False,
        }
    code = {1: "NPU_TIER_1", 2: "GPU_TIER_2", 3: "CPU_TIER_3"}[tier]
    return {
        "active_tier": tier,
        "tier_number": tier,
        "tier": code,
        "tier_code": code,
        "tier_name": name,
        "name": label,
        "device_label": label,
        "runtime_engine": f"{engine} ({name})",
        "device_source": "runtime",
        "has_npu": tier == 1,
        "has_gpu": tier == 2,
    }
