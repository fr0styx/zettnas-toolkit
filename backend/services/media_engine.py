"""
ZettNAS Toolkit - Gated Smart Media & NPU/GPU/CPU Acceleration Engine
Hardware-gated local photo indexing, Multi-Modal RAG, and AI vision service (CLIP / Color / Scene / Document).
Strictly gated on hosts with < 8GB RAM for heavy background scans to prevent memory pressure from compromising core NAS operations,
while supporting lightweight 384-d deterministic RAG and Standby-Safe indexing.
Prioritizes Tier 1 NPU (/dev/accel/accel0, /dev/rknpu, /dev/hailo0, /dev/apex_0) -> Tier 2 GPU (/dev/nvidia0, /dev/dri/renderD128, /dev/kfd) -> Tier 3 CPU.
"""

import datetime
import glob
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from backend.config import DATA_DIR, HOST_DEV, HOST_PROC, HOST_SYS, logger
from backend.fsutil import atomic_write_json, read_json
from backend.services.rag_engine import (
    get_rag_engine,
    get_running_disks_list,
    get_sleeping_disks_list,
)

MEDIA_STATUS_FILE = os.path.join(DATA_DIR, "media_indexing_status.json")
MIN_RAM_REQUIRED_BYTES = 8 * 1024 * 1024 * 1024  # 8GB strict gating threshold


def read_total_ram_bytes() -> int:
    """Safely determines total system physical RAM in bytes from /proc/meminfo."""
    for p in [os.path.join(HOST_PROC, "meminfo"), "/proc/meminfo"]:
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            parts = line.split()
                            if len(parts) >= 2 and parts[1].isdigit():
                                return int(parts[1]) * 1024
            except Exception:
                logger.debug("backend.services.media_engine.read_total_ram_bytes: ignored error", exc_info=True)
    return 0


def detect_hardware_accelerator() -> dict[str, Any]:
    """
    Probes hardware compute accelerators in strict priority order:
      Tier 1 (NPU): Intel AI Boost NPU, Rockchip RKNPU, AMD Ryzen AI XDNA, Hailo-8, Coral EdgeTPU
      Tier 2 (GPU): NVIDIA CUDA, Intel QuickSync/Arc iGPU, AMD ROCm
      Tier 3 (CPU): AVX-512 / AVX2 / ARM NEON Software Execution Provider
    """
    # --- Tier 1: NPU Probes ---
    has_intel_npu = False
    for p in [
        "/dev/accel/accel0",
        os.path.join(HOST_DEV, "accel/accel0"),
        "/dev/accel0",
        "/sys/class/accel/accel0",
        os.path.join(HOST_SYS, "class/accel/accel0"),
    ]:
        if os.path.exists(p):
            has_intel_npu = True
            break

    has_rknpu = False
    for p in ["/dev/rknpu", os.path.join(HOST_DEV, "rknpu"), "/sys/kernel/debug/rknpu"]:
        if os.path.exists(p):
            has_rknpu = True
            break

    has_hailo = False
    for p in ["/dev/hailo0", os.path.join(HOST_DEV, "hailo0")]:
        if os.path.exists(p):
            has_hailo = True
            break

    has_coral = False
    for p in ["/dev/apex_0", os.path.join(HOST_DEV, "apex_0")]:
        if os.path.exists(p):
            has_coral = True
            break

    has_npu = has_intel_npu or has_rknpu or has_hailo or has_coral

    # --- Tier 2: GPU Probes ---
    has_cuda = False
    for p in ["/dev/nvidia0", os.path.join(HOST_DEV, "nvidia0")]:
        if os.path.exists(p):
            has_cuda = True
            break

    has_igpu = False
    dri_nodes = glob.glob("/dev/dri/renderD*") + glob.glob(os.path.join(HOST_DEV, "dri/renderD*"))
    if dri_nodes or os.path.exists("/dev/dri/renderD128"):
        has_igpu = True

    has_rocm = os.path.exists("/dev/kfd") or os.path.exists(os.path.join(HOST_DEV, "kfd"))

    secondary_gpu = None
    if has_cuda:
        secondary_gpu = "NVIDIA CUDA GPU (/dev/nvidia0)"
    elif has_igpu:
        secondary_gpu = "Intel Arc / QuickSync iGPU (/dev/dri/renderD128)"
    elif has_rocm:
        secondary_gpu = "AMD ROCm Compute (/dev/kfd)"

    # Resolve active tier in strict NPU -> GPU -> CPU priority order
    backend = "cpu"
    device_label = "CPU Software Emulation"
    device_node = "cpu"
    active_tier = 3
    active_tier_name = "CPU"
    tier_code = "CPU_TIER_3"
    execution_provider = "CPUExecutionProvider"

    if has_intel_npu:
        backend = "intel_npu"
        device_label = "Intel AI Boost NPU (/dev/accel/accel0)"
        device_node = "/dev/accel/accel0"
        active_tier = 1
        active_tier_name = "NPU"
        tier_code = "NPU_TIER_1"
        execution_provider = "OpenVINOExecutionProvider"
    elif has_rknpu:
        backend = "rockchip_npu"
        device_label = "Rockchip RKNPU2 NPU (/dev/rknpu)"
        device_node = "/dev/rknpu"
        active_tier = 1
        active_tier_name = "NPU"
        tier_code = "NPU_TIER_1"
        execution_provider = "RKNPUExecutionProvider"
    elif has_hailo:
        backend = "hailo_npu"
        device_label = "Hailo-8 AI NPU (/dev/hailo0)"
        device_node = "/dev/hailo0"
        active_tier = 1
        active_tier_name = "NPU"
        tier_code = "NPU_TIER_1"
        execution_provider = "HailoRTExecutionProvider"
    elif has_coral:
        backend = "coral_edgetpu"
        device_label = "Google Coral EdgeTPU (/dev/apex_0)"
        device_node = "/dev/apex_0"
        active_tier = 1
        active_tier_name = "NPU"
        tier_code = "NPU_TIER_1"
        execution_provider = "EdgeTPUExecutionProvider"
    elif has_cuda:
        backend = "nvidia_cuda"
        device_label = "NVIDIA CUDA GPU (/dev/nvidia0)"
        device_node = "/dev/nvidia0"
        active_tier = 2
        active_tier_name = "GPU"
        tier_code = "GPU_TIER_2"
        execution_provider = "CUDAExecutionProvider"
    elif has_igpu:
        backend = "intel_qsv"
        device_label = "Intel/AMD Hardware iGPU (/dev/dri/renderD128)"
        device_node = "/dev/dri/renderD128"
        active_tier = 2
        active_tier_name = "GPU"
        tier_code = "GPU_TIER_2"
        execution_provider = "OpenVINOExecutionProvider"
    elif has_rocm:
        backend = "amd_rocm"
        device_label = "AMD ROCm Compute (/dev/kfd)"
        device_node = "/dev/kfd"
        active_tier = 2
        active_tier_name = "GPU"
        tier_code = "GPU_TIER_2"
        execution_provider = "ROCMExecutionProvider"

    return {
        "available": True,
        "has_npu": has_npu,
        "has_igpu": has_igpu,
        "has_rocm": has_rocm,
        "has_cuda": has_cuda,
        "has_rknpu": has_rknpu,
        "has_hailo": has_hailo,
        "has_coral": has_coral,
        "acceleration_backend": backend,
        "type": backend,
        "name": device_label,
        "device_label": device_label,
        "device_node": device_node,
        "active_tier": active_tier,
        "tier_number": active_tier,
        "active_tier_name": active_tier_name,
        "tier": tier_code,
        "secondary_gpu": secondary_gpu,
        "priority_order": ["NPU", "GPU", "CPU"],
        "priority_chain": ["npu", "gpu", "cpu"],
        "execution_provider": execution_provider,
        "vector_dim": 384,
        "standby_safe": True,
        "fallback_chain": [
            {"tier": 1, "type": "NPU", "backend": "intel_npu", "available": has_npu},
            {
                "tier": 2,
                "type": "GPU",
                "backend": "intel_qsv" if has_igpu else "gpu",
                "available": has_igpu or has_rocm or has_cuda,
            },
            {"tier": 3, "type": "CPU", "backend": "cpu", "available": True},
        ],
    }


def _parse_hf_date(raw_date_str: str) -> tuple[str, float, str]:
    """
    Parses an ISO or date string from Hugging Face Hub (e.g. '2026-10-08T09:12:10.000Z' or '2024-09-19')
    into (display_str, timestamp, iso_str).
    """
    raw = str(raw_date_str or "").strip()
    if not raw:
        return ("Recent", 0.0, "")
    try:
        clean_iso = raw.replace("Z", "+00:00")
        if "T" in clean_iso:
            dt = datetime.datetime.fromisoformat(clean_iso)
        else:
            dt = datetime.datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=datetime.UTC)
        ts = dt.timestamp()
        disp = dt.strftime("%b %d, %Y")
        return (disp, ts, raw)
    except Exception:
        m = re.match(r"^(\d{4})-(\d{2})", raw)
        if m:
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            mon_idx = max(1, min(12, int(m.group(2)))) - 1
            return (f"{months[mon_idx]} {m.group(1)}", 0.0, raw)
        return (raw[:10] if len(raw) >= 10 else "Recent", 0.0, raw)


def is_model_2026_or_newer(m: dict[str, Any]) -> bool:
    """
    Returns True if the model was released in 2026 or later, filtering out older
    legacy models from 2024, 2025, or earlier.
    """
    ts = float(m.get("release_timestamp") or 0.0)
    if ts >= 1767225600.0:  # 2026-01-01T00:00:00Z
        return True

    # Check date strings for pre-2026 years (2020-2025)
    for k in ("release_date", "release_date_str", "created_at", "createdAt"):
        val = str(m.get(k) or "").strip()
        if val:
            if any(f"{yr}" in val for yr in range(2000, 2026)):
                return False
            if "2026" in val or "2027" in val or "Recent" in val:
                return True

    if 0.0 < ts < 1767225600.0:
        return False

    return False


def _estimate_hf_model_specs(
    repo_id: str,
    tags: list[str] | None = None,
    safetensors_total: int | None = None,
    gguf_total: int | None = None,
    pipeline_tag: str | None = None,
) -> dict[str, Any]:
    """
    Infers parameter count, quantization format, estimated RAM/VRAM footprint,
    and accelerator requirements from Hugging Face Hub model metadata.
    """
    tags_list = [str(t).lower() for t in (tags or [])]
    repo_lower = repo_id.lower()
    name_part = repo_id.split("/")[-1] if "/" in repo_id else repo_id

    # 1. Detect parameter count (in Billions)
    params_b: float | None = None
    raw_params = safetensors_total or gguf_total
    if isinstance(raw_params, (int, float)) and raw_params > 10_000_000:
        params_b = round(float(raw_params) / 1e9, 1)

    if params_b is None:
        # Look for MoE patterns like 8x7B, 8x22B first
        moe_match = re.search(r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*b\b", repo_lower)
        if moe_match:
            params_b = round(float(moe_match.group(1)) * float(moe_match.group(2)) * 0.85, 1)
        else:
            param_match = re.search(r"(?:^|[-_/ ])(\d+(?:\.\d+)?)\s*b(?:$|[-_/ .])", repo_lower)
            if not param_match:
                for t in tags_list:
                    m = re.search(r"^(\d+(?:\.\d+)?)b$", t)
                    if m:
                        param_match = m
                        break
            if param_match:
                params_b = float(param_match.group(1))
            elif "mini" in repo_lower:
                params_b = 3.8
            elif "small" in repo_lower:
                params_b = 14.0
            elif "large" in repo_lower:
                params_b = 32.0
            elif "embed" in repo_lower or "minilm" in repo_lower or "bge-" in repo_lower or "clip" in repo_lower:
                params_b = 0.4
            else:
                params_b = 7.0

    # 2. Detect quantization and bytes per parameter
    has_2bit = any(
        k in repo_lower or k in tags_list for k in ("iq2", "iq2_xxs", "iq2_xs", "iq2_s", "iq2_m", "2bit", "2-bit")
    )
    has_3bit = any(k in repo_lower or k in tags_list for k in ("iq3", "q3_k_m", "3bit", "3-bit"))
    if has_2bit:
        quant = "IQ2 / 2-Bit GGUF"
        bytes_per_param = 0.28
    elif has_3bit:
        quant = "IQ3 / 3-Bit GGUF"
        bytes_per_param = 0.44
    elif any(
        k in repo_lower or k in tags_list for k in ("int4", "q4_k_m", "q4_0", "q4", "awq", "gptq", "4bit", "4-bit")
    ):
        quant = "INT4 / Q4_K_M"
        bytes_per_param = 0.62
    elif any(k in repo_lower or k in tags_list for k in ("int8", "q8_0", "q8", "fp8", "8bit", "8-bit")):
        quant = "INT8 / FP8"
        bytes_per_param = 1.05
    elif any(k in repo_lower or k in tags_list for k in ("gguf",)):
        quant = "GGUF (Q4_K_M est.)"
        bytes_per_param = 0.65
    elif any(k in repo_lower or k in tags_list for k in ("openvino", "-ov")):
        quant = "OpenVINO INT4/INT8"
        bytes_per_param = 0.65
    else:
        quant = "FP16 / BF16 Safetensors"
        bytes_per_param = 2.05

    # If actual GGUF file size on disk is reported by HF API, prioritize that exact size!
    if isinstance(gguf_total, (int, float)) and gguf_total > 50_000_000 and has_2bit:
        est_ram_gb = round((float(gguf_total) / (1024**3)) + 0.8, 1)
    else:
        # Estimated memory = model weights + ~0.8GB runtime/KV-cache overhead
        est_ram_gb = round(max(0.5, (params_b * bytes_per_param) + 0.8), 1)

    # Recommended total host RAM so OS + NAS services have headroom
    min_ram_gb = round(max(4.0, est_ram_gb * 2.0), 1)
    requires_dgpu_vram_gb = round(est_ram_gb, 1) if est_ram_gb > 12.0 else 0.0

    is_embed = any(
        k in repo_lower or k in tags_list or (pipeline_tag and k in pipeline_tag.lower())
        for k in ("embedding", "embed", "feature-extraction", "sentence-similarity", "mrl")
    )
    is_vision = any(
        k in repo_lower or k in tags_list or (pipeline_tag and k in pipeline_tag.lower())
        for k in ("vl", "vision", "clip", "image-text", "vlm", "llava", "pixtral")
    )
    if is_embed:
        category = "embeddings_rag"
        rec_npu = True
        rec_gpu = True
        est_ram_gb = round(max(0.2, (params_b * bytes_per_param) + 0.15), 1)
        min_ram_gb = round(max(1.0, est_ram_gb * 2.0), 1)
    elif params_b <= 4.2 and quant.startswith(("INT4", "INT8", "OpenVINO", "GGUF")):
        category = "npu_edge_llm"
        rec_npu = True
        rec_gpu = True
    elif is_vision:
        category = "vision_multimodal"
        rec_npu = params_b <= 8.5
        rec_gpu = True
    elif params_b <= 15.0:
        category = "gpu_balanced_llm"
        rec_npu = False
        rec_gpu = True
    else:
        category = "high_capacity_llm"
        rec_npu = False
        rec_gpu = True

    params_label = f"{params_b:g}B" + (" VL" if is_vision else "")
    return {
        "name": name_part,
        "params": params_label,
        "params_b": params_b,
        "quantization": quant,
        "est_ram_gb": est_ram_gb,
        "min_ram_gb": min_ram_gb,
        "requires_dgpu_vram_gb": requires_dgpu_vram_gb,
        "category": category,
        "recommended_for_npu": rec_npu,
        "recommended_for_gpu": rec_gpu,
    }


def evaluate_model_hardware_fit(
    model: dict[str, Any],
    accel: dict[str, Any],
    eff_ram: float,
    primary_rec: str = "qwen2.5:3b",
) -> dict[str, Any]:
    """
    Evaluates whether a model fits the user's detected NPU, GPU, and RAM headroom.
    Marks any model that exceeds safe NAS memory or onboard NPU/iGPU limits with
    `fits_hardware = False` and a detailed `warning_message`.
    """
    has_npu = bool(accel.get("has_npu"))
    has_dgpu = bool(accel.get("has_cuda") or accel.get("has_rocm"))
    has_igpu = bool(accel.get("has_igpu"))
    has_gpu = has_dgpu or has_igpu
    npu_label = accel.get("device_label", "Onboard NPU") if has_npu else "None detected"
    gpu_label = (
        accel.get("secondary_gpu")
        or (accel.get("device_label") if accel.get("active_tier") == 2 else None)
        or "CPU Fallback"
    )

    est_ram_gb = float(model.get("est_ram_gb") or model.get("vram_or_ram_gb") or 2.0)
    min_ram_gb = float(model.get("min_ram_gb") or max(4.0, est_ram_gb * 2.0))
    req_dgpu_vram_gb = float(model.get("requires_dgpu_vram_gb") or (est_ram_gb if est_ram_gb > 12.0 else 0.0))

    # Safe AI RAM ceiling on a storage NAS (55% of physical RAM so ZFS/Unraid/Docker never OOM)
    safe_ai_ram_gb = round(eff_ram * 0.55, 1)
    # Onboard NPU + integrated GPU shared aperture limit when no discrete CUDA/ROCm GPU is installed
    npu_igpu_ceiling_gb = 12.0

    fits_hardware = True
    warning_severity: str | None = None
    warning_message: str | None = None

    if est_ram_gb > eff_ram or min_ram_gb > eff_ram:
        fits_hardware = False
        warning_severity = "critical"
        fit_status = "insufficient_ram"
        fit_badge = f"⚠️ Doesn't Fit Hardware ({int(min_ram_gb)}GB+ RAM)"
        warning_message = (
            f"Hardware Warning: Requires ~{est_ram_gb:.1f} GB model memory ({min_ram_gb:.0f} GB+ system RAM recommended), "
            f"which exceeds your host's {eff_ram:.1f} GB RAM capacity."
        )
        fit_reason = warning_message
    elif est_ram_gb > safe_ai_ram_gb:
        fits_hardware = False
        warning_severity = "critical"
        fit_status = "insufficient_ram"
        fit_badge = f"⚠️ Exceeds Safe NAS RAM ({est_ram_gb:.1f}GB)"
        warning_message = (
            f"Hardware Warning: Model weights (~{est_ram_gb:.1f} GB) exceed your safe NAS AI memory ceiling "
            f"({safe_ai_ram_gb:.1f} GB of {eff_ram:.1f} GB RAM) and risk OOM-killing storage services."
        )
        fit_reason = warning_message
    elif (req_dgpu_vram_gb > 0 or est_ram_gb > npu_igpu_ceiling_gb) and not has_dgpu:
        fits_hardware = False
        warning_severity = "warning"
        fit_status = "insufficient_vram"
        fit_badge = f"⚠️ Exceeds Onboard NPU/iGPU ({est_ram_gb:.1f}GB)"
        accel_desc = f"{npu_label} + {gpu_label}" if (has_npu and has_igpu) else (npu_label if has_npu else gpu_label)
        warning_message = (
            f"Hardware Warning: Requires ~{est_ram_gb:.1f} GB dedicated GPU VRAM ({max(16, int(req_dgpu_vram_gb))} GB+ dGPU). "
            f"Exceeds onboard {accel_desc} shared aperture ({npu_igpu_ceiling_gb:.0f} GB max) and will run at <2 tok/s on CPU."
        )
        fit_reason = warning_message
    elif (
        has_npu
        and model.get("recommended_for_npu")
        and model.get("category") in ("builtin_npu", "npu_edge_llm", "vision_multimodal")
    ) or (has_gpu and model.get("recommended_for_gpu") and str(model.get("ollama_tag", "")).lower() == primary_rec):
        fit_status = "best_match"
        target_acc = model.get("target_accelerator", "NPU" if has_npu else "GPU")
        if target_acc == "NPU":
            fit_badge = "★ Best for Onboard NPU"
            fit_reason = f"Hardware-matched for {npu_label} ({est_ram_gb:.1f} GB footprint)."
        elif target_acc == "NPU+GPU":
            fit_badge = "★ Best for NPU + iGPU"
            fit_reason = f"Splits vision encoder onto NPU and language decoder onto {gpu_label}."
        else:
            fit_badge = "★ Best for Onboard GPU"
            fit_reason = f"Hardware-matched for {gpu_label} with {eff_ram:.1f} GB system RAM."
    else:
        fit_status = "compatible"
        fit_badge = "✓ Fits Your Hardware"
        fit_reason = (
            f"Fits comfortably within your {eff_ram:.1f} GB RAM & accelerator budget ({est_ram_gb:.1f} GB required)."
        )

    return {
        "fits_hardware": fits_hardware,
        "hardware_warning": not fits_hardware,
        "warning_severity": warning_severity,
        "warning_message": warning_message,
        "fit_status": fit_status,
        "fit_badge": fit_badge,
        "fit_reason": fit_reason,
    }


def build_llm_recommendations(
    accel: dict[str, Any],
    ram_gb: float,
    active_model: str = "qwen2.5:3b",
    custom_models: list[dict[str, Any]] | None = None,
    include_incompatible: bool = False,
    sort_by: str = "date",
    min_release_year: int | None = None,
    removed_models: list[str] | None = None,
) -> dict[str, Any]:
    """
    Generates industry-standard Hugging Face LLM & Multi-Modal model recommendations dynamically
    tailored to the NAS's detected onboard NPU, GPU, and system memory headroom, flagging any
    models that do not fit the user's hardware. Built-in entries are mainstream models with their licences (AI-16).
    """
    has_npu = bool(accel.get("has_npu"))
    has_dgpu = bool(accel.get("has_cuda") or accel.get("has_rocm"))
    has_gpu = bool(has_dgpu or accel.get("has_igpu"))
    npu_label = accel.get("device_label", "Onboard NPU") if has_npu else "None detected"
    gpu_label = (
        accel.get("secondary_gpu")
        or (accel.get("device_label") if accel.get("active_tier") == 2 else None)
        or "CPU Fallback"
    )
    eff_ram = max(4.0, float(ram_gb or 16.0))
    safe_ai_ram_gb = round(eff_ram * 0.55, 1)
    active_norm = str(active_model or "qwen2.5:3b").strip().lower()

    if removed_models is None:
        try:
            rag_cfg = get_rag_engine().get_config()
            removed_models = rag_cfg.get("removed_models", [])
        except Exception:
            removed_models = []
    removed_set = {str(r).lower().strip() for r in (removed_models or []) if r}

    if has_npu and has_gpu:
        tier_headline = f"{npu_label} + {gpu_label} ({eff_ram:.1f} GB RAM)"
        advisor_summary = (
            "Dual-accelerator topology detected: Tier 1 NPU handles continuous <8W multi-modal indexing & "
            "INT4/INT8 edge inference, while Tier 2 GPU accelerates 7B–14B conversational RAG synthesis."
        )
        primary_rec = "qwen2.5:7b" if eff_ram >= 16.0 else "qwen2.5:3b"
    elif has_npu:
        tier_headline = f"{npu_label} ({eff_ram:.1f} GB RAM)"
        advisor_summary = (
            "Onboard NPU Tier 1 active: INT4/INT8 quantized 1B–4B models and OpenVINO multi-modal embeddings "
            "are recommended for maximum throughput and ultra-low thermal/power footprint."
        )
        primary_rec = "deepseek-r1-distill-qwen-1.5b-npu-ov"
    elif has_gpu:
        tier_headline = f"{gpu_label} ({eff_ram:.1f} GB RAM)"
        advisor_summary = "Hardware GPU Tier 2 active: 3B–8B Q4_K_M models are recommended for fast local RAG synthesis and visual search."
        primary_rec = "qwen2.5:7b" if eff_ram >= 16.0 else "qwen2.5:3b"
    else:
        tier_headline = f"CPU AVX2/NEON Execution ({eff_ram:.1f} GB RAM)"
        advisor_summary = (
            "Software CPU execution active: Built-in lightweight 384-d embeddings and 1.5B–3B Q4 quantized models "
            "are recommended to preserve NAS responsiveness."
        )
        primary_rec = "qwen2.5:3b" if eff_ram >= 8.0 else "builtin-npu"

    catalog: list[dict[str, Any]] = [
        # --- Tier 1: NPU / Low-Power Edge Models (0.4B - 4B) ---
        {
            "id": "builtin-npu",
            "ollama_tag": "builtin-npu",
            "hf_repo": "OpenVINO/clip-vit-base-patch16-int8-ov",
            "hf_url": "https://huggingface.co/OpenVINO/clip-vit-base-patch16-int8-ov",
            "name": "ZettAI Built-in Multi-Modal Engine (CLIP + MiniLM INT8)",
            "family": "OpenVINO / ONNX Native",
            "license": "MIT (CLIP) / Apache-2.0 (MiniLM)",
            "category": "builtin_npu",
            "role": "Instant Semantic Search, Visual Photo Indexing & Extractive QA",
            "params": "0.4B INT8",
            "quantization": "INT8 Native",
            "est_ram_gb": 0.6,
            "min_ram_gb": 4.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2024-05-15T00:00:00Z",
            "release_date": "2024-05-15",
            "release_date_str": "May 15, 2024",
            "release_timestamp": 1715731200.0,
            "target_accelerator": "NPU" if has_npu else ("GPU" if has_gpu else "CPU"),
            "target_device": npu_label if has_npu else (gpu_label if has_gpu else "CPU AVX2/NEON"),
            "est_speed": "~120 docs/s · <12ms query" if has_npu else "~60 docs/s · <20ms query",
            "power_profile": "Ultra-Low (< 5W)",
            "capabilities": ["semantic_search", "visual_photo_search", "ocr", "extractive_qa"],
            "recommended_for_npu": True,
            "recommended_for_gpu": True,
        },
        {
            "id": "qwen2.5-3b-npu",
            "ollama_tag": "qwen2.5:3b",
            "hf_repo": "Qwen/Qwen2.5-3B-Instruct-GGUF",
            "hf_url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF",
            "name": "Qwen2.5 3B Instruct (NPU INT4 Edge)",
            "family": "Qwen2.5",
            "license": "Qwen Research License (non-commercial)",
            "category": "npu_edge_llm",
            "role": "Fast Knowledge QA, Summarization & Multilingual Chat (EN/ZH/DE/FR/ES)",
            "params": "3.1B",
            "quantization": "INT4 / Q4_K_M",
            "est_ram_gb": 2.1,
            "min_ram_gb": 8.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2024-09-19T00:00:00Z",
            "release_date": "2024-09-19",
            "release_date_str": "Sep 19, 2024",
            "release_timestamp": 1726704000.0,
            "target_accelerator": "NPU" if has_npu else ("GPU" if has_gpu else "CPU"),
            "target_device": npu_label if has_npu else gpu_label,
            "est_speed": "~48 tok/s (NPU)" if has_npu else ("~40 tok/s (GPU)" if has_gpu else "~16 tok/s (CPU)"),
            "power_profile": "Low Power (< 8W NPU)" if has_npu else "Balanced (~15W)",
            "capabilities": ["rag_qa", "chat", "summarization", "multilingual"],
            "recommended_for_npu": True,
            "recommended_for_gpu": False,
        },
        {
            "id": "llama3.2-3b-npu",
            "ollama_tag": "llama3.2:3b",
            "hf_repo": "meta-llama/Llama-3.2-3B-Instruct",
            "hf_url": "https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct",
            "name": "Llama 3.2 3B Instruct (NPU / iGPU Optimized)",
            "family": "Meta Llama 3.2",
            "license": "Llama 3.2 Community License",
            "category": "npu_edge_llm",
            "role": "Low-Latency Conversational Assistant & File Tagging",
            "params": "3.2B",
            "quantization": "INT4 / Q4_K_M",
            "est_ram_gb": 2.0,
            "min_ram_gb": 8.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2024-09-25T00:00:00Z",
            "release_date": "2024-09-25",
            "release_date_str": "Sep 25, 2024",
            "release_timestamp": 1727222400.0,
            "target_accelerator": "NPU" if has_npu else ("GPU" if has_gpu else "CPU"),
            "target_device": npu_label if has_npu else gpu_label,
            "est_speed": "~50 tok/s (NPU)" if has_npu else ("~42 tok/s (GPU)" if has_gpu else "~18 tok/s (CPU)"),
            "power_profile": "Low Power (< 8W NPU)" if has_npu else "Balanced (~15W)",
            "capabilities": ["rag_qa", "chat", "fast_tagging"],
            "recommended_for_npu": True,
            "recommended_for_gpu": False,
        },
        {
            "id": "phi3.5-mini-npu",
            "ollama_tag": "phi3.5:3.8b",
            "hf_repo": "OpenVINO/Phi-3.5-mini-instruct-int4-ov",
            "hf_url": "https://huggingface.co/OpenVINO/Phi-3.5-mini-instruct-int4-ov",
            "name": "Phi-3.5 Mini 3.8B Instruct (128K Context)",
            "family": "Microsoft Phi-3.5",
            "license": "MIT",
            "category": "npu_edge_llm",
            "role": "Long-Context PDF/Contract Analysis & Recipe Extraction on NPU/iGPU",
            "params": "3.8B",
            "quantization": "INT4 / OpenVINO",
            "est_ram_gb": 2.4,
            "min_ram_gb": 8.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2024-08-20T00:00:00Z",
            "release_date": "2024-08-20",
            "release_date_str": "Aug 20, 2024",
            "release_timestamp": 1724112000.0,
            "target_accelerator": "NPU" if has_npu else ("GPU" if has_gpu else "CPU"),
            "target_device": npu_label if has_npu else gpu_label,
            "est_speed": "~42 tok/s (NPU)" if has_npu else "~35 tok/s (GPU)",
            "power_profile": "Low Power (< 10W)",
            "capabilities": ["rag_qa", "long_context", "structured_extraction"],
            "recommended_for_npu": True,
            "recommended_for_gpu": True,
        },
        {
            "id": "gemma3-4b-npu",
            "ollama_tag": "gemma3:4b",
            "hf_repo": "google/gemma-3-4b-it-qat-q4_0-gguf",
            "hf_url": "https://huggingface.co/google/gemma-3-4b-it-qat-q4_0-gguf",
            "name": "Google Gemma 3 4B Instruct QAT (Multimodal Edge)",
            "family": "Google Gemma 3",
            "license": "Gemma Terms of Use",
            "category": "npu_edge_llm",
            "role": "Quantization-Aware Vision & Document QA with 128K Context Window",
            "params": "4.0B VL",
            "quantization": "QAT Q4_0",
            "est_ram_gb": 3.1,
            "min_ram_gb": 8.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2025-03-04T00:00:00Z",
            "release_date": "2025-03-04",
            "release_date_str": "Mar 04, 2025",
            "release_timestamp": 1741046400.0,
            "target_accelerator": "NPU" if has_npu else ("GPU" if has_gpu else "CPU"),
            "target_device": npu_label if has_npu else gpu_label,
            "est_speed": "~38 tok/s (NPU/iGPU)" if (has_npu or has_gpu) else "~14 tok/s (CPU)",
            "power_profile": "Low Power (< 10W)",
            "capabilities": ["rag_qa", "vision_qa", "long_context", "multilingual"],
            "recommended_for_npu": True,
            "recommended_for_gpu": True,
        },
        {
            # A 4B multilingual model under a permissive licence (AI-7): answers in the
            # question's language for the five UI languages and many more.
            "id": "qwen3-4b",
            "ollama_tag": "qwen3:4b",
            "hf_repo": "Qwen/Qwen3-4B-GGUF",
            "hf_url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF",
            "name": "Qwen3 4B (multilingual)",
            "family": "Qwen3",
            "license": "Apache 2.0",
            "category": "npu_edge_llm",
            "role": "Multilingual answers about your documents (EN/DE/FR/ES/ZH and 100+ more)",
            "params": "4.0B",
            "quantization": "Q4_K_M",
            "est_ram_gb": 3.3,
            "min_ram_gb": 8.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2025-04-29T00:00:00Z",
            "release_date": "2025-04-29",
            "release_date_str": "Apr 29, 2025",
            "release_timestamp": 1745884800.0,
            "target_accelerator": "GPU" if has_gpu else "CPU",
            "target_device": gpu_label if has_gpu else "CPU AVX2/NEON",
            "est_speed": "Run Benchmark to measure on this NAS",
            "power_profile": "Balanced (~15W)",
            "capabilities": ["rag_qa", "chat", "summarization", "multilingual"],
            "recommended_for_npu": False,
            "recommended_for_gpu": True,
        },
        # --- Tier 2: Onboard iGPU / Balanced GPU Models (7B - 14B) ---
        {
            "id": "qwen2.5-7b-gpu",
            "ollama_tag": "qwen2.5:7b",
            "hf_repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
            "hf_url": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF",
            "name": "Qwen2.5 7B Instruct (iGPU / Hybrid Workhorse)",
            "family": "Qwen2.5",
            "license": "Apache-2.0",
            "category": "gpu_balanced_llm",
            "role": "High-Accuracy Grounded RAG, Code & Complex Document Synthesis",
            "params": "7.6B",
            "quantization": "Q4_K_M",
            "est_ram_gb": 4.7,
            "min_ram_gb": 16.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2024-09-19T00:00:00Z",
            "release_date": "2024-09-19",
            "release_date_str": "Sep 19, 2024",
            "release_timestamp": 1726704000.0,
            "target_accelerator": "GPU" if has_gpu else ("NPU" if has_npu else "CPU"),
            "target_device": gpu_label if has_gpu else npu_label,
            "est_speed": "~30 tok/s (iGPU/GPU)" if has_gpu else "~22 tok/s (NPU)",
            "power_profile": "Balanced (~18–25W iGPU)",
            "capabilities": ["rag_qa", "chat", "code", "multilingual", "citations"],
            "recommended_for_npu": False,
            "recommended_for_gpu": True,
        },
        {
            "id": "qwen2.5-vl-7b",
            "ollama_tag": "qwen2.5vl:7b",
            "hf_repo": "Qwen/Qwen2.5-VL-7B-Instruct",
            "hf_url": "https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct",
            "name": "Qwen2.5-VL 7B Vision-Language (NPU + iGPU Hybrid)",
            "family": "Qwen2.5-VL",
            "license": "Apache-2.0",
            "category": "vision_multimodal",
            "role": "Deep Photo Scene Understanding, Receipt/Invoice OCR & Visual Q&A",
            "params": "7.8B VL",
            "quantization": "INT4 / Q4_K_M",
            "est_ram_gb": 5.6,
            "min_ram_gb": 16.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2025-01-27T00:00:00Z",
            "release_date": "2025-01-27",
            "release_date_str": "Jan 27, 2025",
            "release_timestamp": 1737936000.0,
            "target_accelerator": "NPU+GPU" if (has_npu and has_gpu) else ("GPU" if has_gpu else "NPU"),
            "target_device": f"{npu_label} + {gpu_label}"
            if (has_npu and has_gpu)
            else (gpu_label if has_gpu else npu_label),
            "est_speed": "~26 tok/s (Hybrid NPU+iGPU)",
            "power_profile": "Hybrid (~20W)",
            "capabilities": ["vision_qa", "ocr", "scene_captioning", "invoice_parsing"],
            "recommended_for_npu": True,
            "recommended_for_gpu": True,
        },
        {
            "id": "mistral-nemo-12b",
            "ollama_tag": "mistral-nemo:12b",
            "hf_repo": "mistralai/Mistral-Nemo-Instruct-2407-GGUF",
            "hf_url": "https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407-GGUF",
            "name": "Mistral NeMo 12B Instruct (128K Context RAG)",
            "family": "Mistral AI / NVIDIA",
            "license": "Apache-2.0",
            "category": "gpu_balanced_llm",
            "role": "Enterprise Document Synthesis, Legal/Financial Summarization & Tekken Tokenizer",
            "params": "12.2B",
            "quantization": "Q4_K_M",
            "est_ram_gb": 7.5,
            "min_ram_gb": 16.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2024-07-18T00:00:00Z",
            "release_date": "2024-07-18",
            "release_date_str": "Jul 18, 2024",
            "release_timestamp": 1721260800.0,
            "target_accelerator": "GPU" if has_gpu else "CPU",
            "target_device": gpu_label if has_gpu else npu_label,
            "est_speed": "~21 tok/s (iGPU/GPU)" if has_gpu else "~10 tok/s (CPU)",
            "power_profile": "Balanced (~24W)",
            "capabilities": ["rag_qa", "long_context", "citations", "multilingual"],
            "recommended_for_npu": False,
            "recommended_for_gpu": True,
        },
        {
            "id": "deepseek-r1-14b",
            "ollama_tag": "deepseek-r1:14b",
            "hf_repo": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B-GGUF",
            "hf_url": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-14B-GGUF",
            "name": "DeepSeek-R1 Distill Qwen 14B (Reasoning Workstation)",
            "family": "DeepSeek-R1",
            "license": "MIT (Qwen 2.5 base licence also applies)",
            "category": "high_capacity_llm",
            "role": "Deep Chain-of-Thought Reasoning & Multi-Document Cross-Verification",
            "params": "14.8B",
            "quantization": "Q4_K_M",
            "est_ram_gb": 9.0,
            "min_ram_gb": 24.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2025-01-20T00:00:00Z",
            "release_date": "2025-01-20",
            "release_date_str": "Jan 20, 2025",
            "release_timestamp": 1737331200.0,
            "target_accelerator": "GPU" if has_gpu else "CPU",
            "target_device": gpu_label if has_gpu else npu_label,
            "est_speed": "~18 tok/s (iGPU Shared Memory)" if has_gpu else "~9 tok/s",
            "power_profile": "Performance (~28W)",
            "capabilities": ["deep_reasoning", "rag_qa", "multi_doc_synthesis"],
            "recommended_for_npu": False,
            "recommended_for_gpu": True,
        },
        {
            "id": "deepseek-r1-distill-qwen-1.5b-npu-ov",
            "ollama_tag": "DeepSeek-R1-Distill-Qwen-1.5B",
            "hf_repo": "OpenVINO/DeepSeek-R1-Distill-Qwen-1.5B-int4-gq-ov",
            "hf_url": "https://huggingface.co/OpenVINO/DeepSeek-R1-Distill-Qwen-1.5B-int4-gq-ov",
            "name": "DeepSeek-R1 1.5B Reasoning (OpenVINO NPU ~3W Silent)",
            "family": "DeepSeek-R1",
            "license": "MIT (Qwen 2.5 base licence also applies)",
            "category": "npu_edge_llm",
            "role": "Ultra-Low Power (<3W) Hardware Copilot & Chain-of-Thought Reasoning on Intel AI Boost NPU",
            "params": "1.5B INT4-GQ",
            "quantization": "OpenVINO INT4 Group-Quant",
            "est_ram_gb": 1.1,
            "min_ram_gb": 4.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2026-02-10T00:00:00Z",
            "release_date": "2026-02-10",
            "release_date_str": "Feb 10, 2026",
            "release_timestamp": 1770681600.0,
            "target_accelerator": "NPU" if has_npu else ("GPU" if has_gpu else "CPU"),
            "target_device": npu_label if has_npu else gpu_label,
            "est_speed": "~75 tok/s (NPU)" if has_npu else "~45 tok/s (GPU)",
            "power_profile": "Silent / Zero Fan (< 3W NPU)",
            "capabilities": ["reasoning", "rag_qa", "chat", "telemetry", "multilingual"],
            "recommended_for_npu": True,
            "recommended_for_gpu": False,
        },
        {
            "id": "embeddinggemma",
            "ollama_tag": "embeddinggemma",
            "hf_repo": "google/embeddinggemma-300m",
            "hf_url": "https://huggingface.co/google/embeddinggemma-300m",
            "name": "Google EmbeddingGemma 300M (text embeddings)",
            "family": "Google Gemma",
            "license": "Gemma Terms of Use",
            "category": "embeddings_rag",
            "role": "Text embeddings for document search; 2,048-token input, Matryoshka sizes 768/512/256/128",
            "params": "0.3B",
            "quantization": "BF16",
            "est_ram_gb": 0.6,
            "min_ram_gb": 1.0,
            "requires_dgpu_vram_gb": 0.0,
            "created_at": "2025-09-04T00:00:00Z",
            "release_date": "2025-09-04",
            "release_date_str": "Sep 04, 2025",
            "release_timestamp": 1756944000.0,
            "target_accelerator": "NPU" if has_npu else ("GPU" if has_gpu else "CPU"),
            "target_device": npu_label if has_npu else gpu_label,
            "est_speed": "",
            "power_profile": "Low",
            "capabilities": [
                "feature-extraction",
                "embeddings",
                "rag_qa",
                "semantic_search",
                "code_search",
                "matryoshka_mrl",
            ],
            "recommended_for_npu": True,
            "recommended_for_gpu": True,
        },
    ]
    if include_incompatible:
        catalog.extend(
            [
                # --- Tier 3: Heavy Discrete GPU / Datacenter Release Models (Hardware Warning on Standard NAS) ---
                {
                    "id": "gemma3-27b-dgpu",
                    "ollama_tag": "gemma3:27b",
                    "hf_repo": "google/gemma-3-27b-it-qat-q4_0-gguf",
                    "hf_url": "https://huggingface.co/google/gemma-3-27b-it-qat-q4_0-gguf",
                    "name": "Google Gemma 3 27B Instruct QAT (Discrete GPU Class)",
                    "family": "Google Gemma 3",
                    "license": "Gemma Terms of Use",
                    "category": "high_capacity_llm",
                    "role": "Heavy Multimodal Vision-Language & Research Reasoning (Requires 24GB+ dGPU)",
                    "params": "27.0B VL",
                    "quantization": "QAT Q4_0",
                    "est_ram_gb": 17.5,
                    "min_ram_gb": 36.0,
                    "requires_dgpu_vram_gb": 24.0,
                    "created_at": "2025-03-04T00:00:00Z",
                    "release_date": "2025-03-04",
                    "release_date_str": "Mar 04, 2025",
                    "release_timestamp": 1741046400.0,
                    "target_accelerator": "dGPU (24GB+ VRAM)",
                    "target_device": gpu_label if has_dgpu else "Requires 24GB+ Discrete GPU",
                    "est_speed": "~32 tok/s (24GB dGPU) · <3 tok/s (iGPU/CPU)",
                    "power_profile": "High Power (180W+ dGPU)",
                    "capabilities": ["vision_qa", "deep_reasoning", "rag_qa", "long_context"],
                    "recommended_for_npu": False,
                    "recommended_for_gpu": has_dgpu,
                },
                {
                    "id": "qwen2.5-32b-dgpu",
                    "ollama_tag": "qwen2.5:32b",
                    "hf_repo": "Qwen/Qwen2.5-32B-Instruct-GGUF",
                    "hf_url": "https://huggingface.co/Qwen/Qwen2.5-32B-Instruct-GGUF",
                    "name": "Qwen2.5 32B Instruct (24GB+ Discrete GPU Workstation)",
                    "family": "Qwen2.5",
                    "license": "Apache-2.0",
                    "category": "high_capacity_llm",
                    "role": "Repository-Scale Code Architecture & Complex Multi-Hop Synthesis",
                    "params": "32.5B",
                    "quantization": "Q4_K_M",
                    "est_ram_gb": 20.5,
                    "min_ram_gb": 48.0,
                    "requires_dgpu_vram_gb": 24.0,
                    "created_at": "2024-09-19T00:00:00Z",
                    "release_date": "2024-09-19",
                    "release_date_str": "Sep 19, 2024",
                    "release_timestamp": 1726704000.0,
                    "target_accelerator": "dGPU (24GB+ VRAM)",
                    "target_device": gpu_label if has_dgpu else "Requires 24GB+ Discrete GPU",
                    "est_speed": "~28 tok/s (24GB dGPU) · <2.5 tok/s (iGPU/CPU)",
                    "power_profile": "High Power (200W+ dGPU)",
                    "capabilities": ["code", "deep_reasoning", "rag_qa", "multilingual"],
                    "recommended_for_npu": False,
                    "recommended_for_gpu": has_dgpu,
                },
                {
                    "id": "llama3.3-70b-datacenter",
                    "ollama_tag": "llama3.3:70b",
                    "hf_repo": "meta-llama/Llama-3.3-70B-Instruct-GGUF",
                    "hf_url": "https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct-GGUF",
                    "name": "Meta Llama 3.3 70B Instruct (48GB+ VRAM Server Class)",
                    "family": "Meta Llama 3.3",
                    "license": "Llama 3.3 Community License",
                    "category": "high_capacity_llm",
                    "role": "Frontier-Grade Knowledge Synthesis (Exceeds Standard NAS Memory & NPU/iGPU)",
                    "params": "70.6B",
                    "quantization": "Q4_K_M",
                    "est_ram_gb": 43.5,
                    "min_ram_gb": 96.0,
                    "requires_dgpu_vram_gb": 48.0,
                    "created_at": "2024-12-06T00:00:00Z",
                    "release_date": "2024-12-06",
                    "release_date_str": "Dec 06, 2024",
                    "release_timestamp": 1733443200.0,
                    "target_accelerator": "Multi-GPU (48GB+ VRAM)",
                    "target_device": "Requires 48GB+ VRAM / 96GB+ RAM",
                    "est_speed": "~18 tok/s (Dual 24GB GPU) · <0.8 tok/s (Swap/CPU)",
                    "power_profile": "Server Class (350W+)",
                    "capabilities": ["deep_reasoning", "rag_qa", "multilingual", "code"],
                    "recommended_for_npu": False,
                    "recommended_for_gpu": False,
                },
                {
                    "id": "deepseek-r1-70b-datacenter",
                    "ollama_tag": "deepseek-r1:70b",
                    "hf_repo": "deepseek-ai/DeepSeek-R1-Distill-Llama-70B-GGUF",
                    "hf_url": "https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Llama-70B-GGUF",
                    "name": "DeepSeek-R1 Distill Llama 70B (48GB+ VRAM Server Class)",
                    "family": "DeepSeek-R1",
                    "license": "MIT (Llama 3.3 base licence also applies)",
                    "category": "high_capacity_llm",
                    "role": "Frontier Chain-of-Thought Mathematical & Scientific Verification",
                    "params": "70.6B",
                    "quantization": "Q4_K_M",
                    "est_ram_gb": 44.0,
                    "min_ram_gb": 96.0,
                    "requires_dgpu_vram_gb": 48.0,
                    "created_at": "2025-01-20T00:00:00Z",
                    "release_date": "2025-01-20",
                    "release_date_str": "Jan 20, 2025",
                    "release_timestamp": 1737331200.0,
                    "target_accelerator": "Multi-GPU (48GB+ VRAM)",
                    "target_device": "Requires 48GB+ VRAM / 96GB+ RAM",
                    "est_speed": "~16 tok/s (48GB VRAM) · <0.7 tok/s (Swap/CPU)",
                    "power_profile": "Server Class (350W+)",
                    "capabilities": ["deep_reasoning", "rag_qa", "multi_doc_synthesis"],
                    "recommended_for_npu": False,
                    "recommended_for_gpu": False,
                },
                {
                    "id": "llama3.1-405b-datacenter",
                    "ollama_tag": "llama3.1:405b",
                    "hf_repo": "meta-llama/Llama-3.1-405B-Instruct-FP8",
                    "hf_url": "https://huggingface.co/meta-llama/Llama-3.1-405B-Instruct-FP8",
                    "name": "Meta Llama 3.1 405B Instruct FP8 (Datacenter Cluster Only)",
                    "family": "Meta Llama 3.1",
                    "license": "Llama 3.1 Community License",
                    "category": "high_capacity_llm",
                    "role": "405-Billion Parameter Datacenter Frontier Model (Requires 8x H100 / 256GB+ VRAM)",
                    "params": "405B",
                    "quantization": "FP8",
                    "est_ram_gb": 245.0,
                    "min_ram_gb": 512.0,
                    "requires_dgpu_vram_gb": 256.0,
                    "created_at": "2024-07-23T00:00:00Z",
                    "release_date": "2024-07-23",
                    "release_date_str": "Jul 23, 2024",
                    "release_timestamp": 1721692800.0,
                    "target_accelerator": "8x GPU Cluster (256GB+ VRAM)",
                    "target_device": "Requires 256GB+ VRAM / 512GB+ RAM",
                    "est_speed": "Cannot fit in NAS memory",
                    "power_profile": "Datacenter (> 1200W)",
                    "capabilities": ["deep_reasoning", "frontier_llm"],
                    "recommended_for_npu": False,
                    "recommended_for_gpu": False,
                },
            ]
        )

    # Merge any user-pulled custom Hugging Face models so they persist in the catalog
    seen_ids = {m["ollama_tag"].lower() for m in catalog} | {m["hf_repo"].lower() for m in catalog}
    for cm in custom_models or []:
        if not isinstance(cm, dict):
            continue
        cm_tag = str(cm.get("ollama_tag") or cm.get("id") or cm.get("hf_repo") or "").strip()
        if not cm_tag or cm_tag.lower() in seen_ids:
            continue
        seen_ids.add(cm_tag.lower())
        catalog.append(cm)

    enriched_models = []
    compatible_count = 0
    warning_count = 0

    for m in catalog:
        tag_lower = str(m.get("ollama_tag") or m.get("id") or "").lower()
        hf_lower = str(m.get("hf_repo") or "").lower()
        m_id_lower = str(m.get("id") or "").lower()

        # Skip any model removed by user
        keys_to_check = {
            tag_lower,
            hf_lower,
            m_id_lower,
            tag_lower.replace("hf.co/", ""),
            m_id_lower.replace("hf.co/", ""),
            f"hf.co/{hf_lower}",
        }
        if keys_to_check & removed_set:
            continue

        # Strictly remove any older models released before 2026 (2024, 2025, etc.)
        if min_release_year and min_release_year >= 2026 and not is_model_2026_or_newer(m):
            continue

        is_sel = (
            tag_lower == active_norm
            or str(m.get("id", "")).lower() == active_norm
            or (hf_lower and hf_lower == active_norm)
        )
        fit_eval = evaluate_model_hardware_fit(m, accel=accel, eff_ram=eff_ram, primary_rec=primary_rec)
        if fit_eval["fits_hardware"]:
            compatible_count += 1
        else:
            warning_count += 1
            if not include_incompatible and not is_sel:
                continue

        enriched = dict(m)
        enriched["id"] = m.get("ollama_tag") or m.get("id")
        enriched["model_key"] = m.get("id") or m.get("ollama_tag")
        enriched["source"] = m.get("source", "huggingface")
        enriched["hf_repo"] = m.get("hf_repo") or m.get("id")
        enriched["hf_url"] = m.get("hf_url") or f"https://huggingface.co/{enriched['hf_repo']}"
        enriched.update(fit_eval)
        enriched["why_recommended"] = fit_eval["fit_reason"]
        enriched["use_case"] = m.get("role", "Hugging Face Release Model")
        enriched["vram_or_ram_gb"] = m.get("est_ram_gb", 2.0)
        enriched["estimated_speed"] = m.get("est_speed", "~20 tok/s")
        enriched["recommended"] = fit_eval["fit_status"] == "best_match" or (
            m.get("ollama_tag") == "deepseek-r1:14b" and eff_ram >= 32.0 and (has_npu or has_gpu)
        )
        enriched["is_selected"] = is_sel
        enriched["active"] = is_sel

        # Date & Release metadata
        raw_m_date = m.get("created_at") or m.get("release_date") or m.get("createdAt") or ""
        r_disp, r_ts, r_iso = _parse_hf_date(raw_m_date)
        enriched["created_at"] = m.get("created_at") or r_iso or raw_m_date
        enriched["release_date"] = m.get("release_date") or (r_iso[:10] if r_iso else "")
        enriched["release_date_str"] = m.get("release_date_str") or r_disp
        enriched["release_timestamp"] = float(m.get("release_timestamp") or r_ts)

        enriched_models.append(enriched)

    # Sort enriched models according to sort_by
    if sort_by == "date":
        enriched_models.sort(
            key=lambda x: (
                float(x.get("release_timestamp") or 0.0),
                int(x.get("downloads") or 0),
            ),
            reverse=True,
        )
    elif sort_by == "recommended":
        enriched_models.sort(
            key=lambda x: (
                1 if x.get("recommended") else 0,
                1 if x.get("fits_hardware") else 0,
                float(x.get("release_timestamp") or 0.0),
            ),
            reverse=True,
        )
    elif sort_by == "downloads":
        enriched_models.sort(
            key=lambda x: (
                int(x.get("downloads") or 0),
                float(x.get("release_timestamp") or 0.0),
            ),
            reverse=True,
        )
    elif sort_by == "size_asc":
        enriched_models.sort(key=lambda x: float(x.get("est_ram_gb") or x.get("vram_or_ram_gb") or 0.0))
    elif sort_by == "size_desc":
        enriched_models.sort(
            key=lambda x: float(x.get("est_ram_gb") or x.get("vram_or_ram_gb") or 0.0),
            reverse=True,
        )

    return {
        "headline": f"NPU + GPU Hybrid ({tier_headline})"
        if (has_npu and has_gpu)
        else (f"NPU ({tier_headline})" if has_npu else (f"GPU ({tier_headline})" if has_gpu else tier_headline)),
        "hardware_summary": f"{tier_headline} — {advisor_summary}",
        "active_model": active_model or "qwen2.5:3b",
        "compatible_count": compatible_count,
        "warning_count": warning_count,
        "sort_by": sort_by,
        "hardware_profile": {
            "has_npu": has_npu,
            "npu_device": npu_label,
            "has_gpu": has_gpu,
            "has_dgpu": has_dgpu,
            "gpu_device": gpu_label,
            "total_ram_gb": eff_ram,
            "safe_ai_ram_gb": safe_ai_ram_gb,
            "npu_igpu_ceiling_gb": 12.0 if not has_dgpu else round(eff_ram * 0.55, 1),
            "tier_headline": tier_headline,
            "advisor_summary": advisor_summary,
            "primary_recommendation": primary_rec,
            "active_model": active_model or "qwen2.5:3b",
        },
        "models": enriched_models,
    }


def _normalize_hf_repo_input(raw_input: str) -> str:
    """Normalizes a Hugging Face URL or repo string into `org/model` or search query."""
    cleaned = str(raw_input or "").strip()
    cleaned = re.sub(r"^https?://(?:www\.)?huggingface\.co/", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"/(?:tree|blob|resolve)/.*$", "", cleaned)
    return cleaned.strip("/")


def is_embedding_only_model(model: Any) -> bool:
    """
    Returns True if the given model (ID string or model dict) is an embedding-only model
    (e.g., feature-extraction, sentence-similarity, embeddinggemma, bge, nomic-embed)
    which cannot perform conversational chat generation.
    """
    if isinstance(model, dict):
        pipeline = str(model.get("pipeline_tag") or "").lower()
        if pipeline in ("feature-extraction", "sentence-similarity"):
            return True
        caps = [str(c).lower() for c in model.get("capabilities", [])]
        if "embedding" in caps or "feature-extraction" in caps or "sentence-similarity" in caps:
            if not any(c in caps for c in ("text-generation", "conversational", "text2text-generation", "chat")):
                return True
        m_id = str(model.get("id") or model.get("hf_repo") or model.get("ollama_tag") or "").lower()
    else:
        m_id = str(model or "").lower()

    if any(k in m_id for k in ("embedding", "bge-", "e5-", "gte-", "minilm", "nomic-embed", "sentence-transformers")):
        if "instruct" not in m_id and "chat" not in m_id:
            return True
        if any(k in m_id for k in ("embeddinggemma", "bge-m3", "bge-large")):
            return True
    return False


def _format_hf_api_item(
    item: dict[str, Any],
    accel: dict[str, Any],
    eff_ram: float,
    active_norm: str,
) -> dict[str, Any]:
    """Converts a raw Hugging Face Hub `/api/models` item into a ZettAI hardware-evaluated model dict."""
    repo_id = str(item.get("id") or item.get("modelId") or "").strip()
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    safetensors_info = item.get("safetensors") if isinstance(item.get("safetensors"), dict) else {}
    gguf_info = item.get("gguf") if isinstance(item.get("gguf"), dict) else {}
    safetensors_total = safetensors_info.get("total")
    gguf_total = gguf_info.get("totalFileSize") or gguf_info.get("total") or item.get("totalFileSize")
    pipeline_tag = str(item.get("pipeline_tag") or "text-generation")

    specs = _estimate_hf_model_specs(
        repo_id=repo_id,
        tags=tags,
        safetensors_total=safetensors_total,
        gguf_total=gguf_total,
        pipeline_tag=pipeline_tag,
    )
    has_npu = bool(accel.get("has_npu"))
    has_dgpu = bool(accel.get("has_cuda") or accel.get("has_rocm"))
    has_gpu = bool(has_dgpu or accel.get("has_igpu"))
    npu_label = accel.get("device_label", "Onboard NPU") if has_npu else "CPU"
    gpu_label = accel.get("secondary_gpu") or accel.get("device_label") or "GPU"

    params_b = specs["params_b"]
    if params_b <= 4.2 and has_npu:
        target_accel = "NPU"
        target_dev = npu_label
        est_speed = "~40–50 tok/s (NPU)"
        power = "Low Power (< 10W)"
    elif params_b <= 15.0 and has_gpu:
        target_accel = "GPU"
        target_dev = gpu_label
        est_speed = "~18–30 tok/s (iGPU/GPU)"
        power = "Balanced (~20–28W)"
    elif params_b > 15.0:
        target_accel = "dGPU (24GB+ VRAM)" if params_b <= 35.0 else "Multi-GPU (48GB+ VRAM)"
        target_dev = gpu_label if has_dgpu else f"Requires {max(24, int(specs['est_ram_gb']))}GB+ Discrete GPU"
        est_speed = "~20 tok/s (dGPU) · <2 tok/s (NAS CPU/iGPU)"
        power = "High Power (180W–350W+)"
    else:
        target_accel = "CPU"
        target_dev = "CPU AVX2/NEON"
        est_speed = "~10–16 tok/s (CPU)"
        power = "Balanced (~15W)"

    author = repo_id.split("/")[0] if "/" in repo_id else "HuggingFace"
    downloads = int(item.get("downloads") or 0)
    likes = int(item.get("likes") or 0)
    role_desc = f"Hugging Face Release ({pipeline_tag}) · {downloads:,} downloads · ♥ {likes:,}"

    raw_date = (
        item.get("createdAt") or item.get("created_at") or item.get("lastModified") or item.get("last_modified") or ""
    )
    release_date_str, release_ts, created_at_iso = _parse_hf_date(raw_date)

    candidate = {
        "id": f"hf.co/{repo_id}",
        "ollama_tag": f"hf.co/{repo_id}",
        "hf_repo": repo_id,
        "hf_url": f"https://huggingface.co/{repo_id}",
        "name": specs["name"],
        "family": author,
        "category": specs["category"],
        "role": role_desc,
        "use_case": role_desc,
        "params": specs["params"],
        "quantization": specs["quantization"],
        "est_ram_gb": specs["est_ram_gb"],
        "vram_or_ram_gb": specs["est_ram_gb"],
        "min_ram_gb": specs["min_ram_gb"],
        "requires_dgpu_vram_gb": specs["requires_dgpu_vram_gb"],
        "created_at": created_at_iso or raw_date,
        "release_date": created_at_iso[:10] if created_at_iso else "",
        "release_date_str": release_date_str,
        "release_timestamp": release_ts,
        "target_accelerator": target_accel,
        "target_device": target_dev,
        "est_speed": est_speed,
        "estimated_speed": est_speed,
        "power_profile": power,
        "downloads": downloads,
        "likes": likes,
        "pipeline_tag": pipeline_tag,
        "capabilities": [pipeline_tag, "huggingface_hub"],
        "recommended_for_npu": specs["recommended_for_npu"],
        "recommended_for_gpu": specs["recommended_for_gpu"],
        "source": "huggingface_hub",
    }

    fit_eval = evaluate_model_hardware_fit(candidate, accel=accel, eff_ram=eff_ram)
    candidate.update(fit_eval)
    candidate["why_recommended"] = fit_eval["fit_reason"]
    candidate["recommended"] = fit_eval["fit_status"] == "best_match"
    is_sel = active_norm in (candidate["id"].lower(), repo_id.lower())
    candidate["is_selected"] = is_sel
    candidate["active"] = is_sel
    return candidate


def search_huggingface_models(
    query: str = "",
    limit: int = 12,
    sort_by: str = "date",
    min_release_year: int | None = None,
) -> dict[str, Any]:
    """
    Searches the live https://huggingface.co/api/models database of release models
    (with offline fallback to the expanded ZettAI Hugging Face catalog) and flags
    every model that does not fit the user's NAS hardware. Filters out models released
    before 2026 when min_release_year is active.
    """
    ram_bytes = read_total_ram_bytes()
    eff_ram = max(4.0, round(ram_bytes / (1024**3), 1))
    accel = detect_hardware_accelerator()
    rag = get_rag_engine()
    rag_cfg = rag.get_config()
    active_model = str(rag_cfg.get("active_model") or rag_cfg.get("llm_model") or "qwen2.5:3b").strip()
    active_norm = active_model.lower()

    clean_q = _normalize_hf_repo_input(query)
    safe_limit = max(1, min(int(limit or 16), 50))

    results: list[dict[str, Any]] = []
    source_mode = "huggingface_live"
    exact_match_item: dict[str, Any] | None = None

    if os.environ.get("TESTING") != "1" and os.environ.get("ZETTNAS_TEST_MODE") != "1":
        try:
            # If user pasted an exact `org/repo` or full huggingface.co URL, fetch that exact model first
            if "/" in clean_q and " " not in clean_q:
                exact_url = f"https://huggingface.co/api/models/{urllib.parse.quote(clean_q, safe='/')}"
                req_exact = urllib.request.Request(
                    exact_url,
                    headers={"User-Agent": "ZettNAS-Toolkit/1.0 (https://huggingface.co)"},
                )
                try:
                    with urllib.request.urlopen(req_exact, timeout=4.0) as resp:
                        exact_data = json.loads(resp.read().decode("utf-8"))
                        if isinstance(exact_data, dict) and exact_data.get("id"):
                            formatted_exact = _format_hf_api_item(exact_data, accel, eff_ram, active_norm)
                            exact_match_item = formatted_exact
                            results.append(formatted_exact)
                except Exception:
                    logger.debug(
                        "backend.services.media_engine.search_huggingface_models: ignored error", exc_info=True
                    )

            api_fetch_limit = min(60, max(40, safe_limit * 3))
            params = {
                "search": clean_q or "Instruct GGUF",
                "limit": str(api_fetch_limit),
                "sort": "downloads",
                "direction": "-1",
                "full": "true",
            }
            api_url = f"https://huggingface.co/api/models?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "ZettNAS-Toolkit/1.0 (https://huggingface.co)"},
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                raw_items = json.loads(resp.read().decode("utf-8"))
                if isinstance(raw_items, list):
                    seen = {r["hf_repo"].lower() for r in results}
                    for item in raw_items:
                        if not isinstance(item, dict) or not item.get("id"):
                            continue
                        rid = str(item["id"]).lower()
                        if rid in seen:
                            continue
                        seen.add(rid)
                        results.append(_format_hf_api_item(item, accel, eff_ram, active_norm))
        except Exception as e:
            logger.debug(f"[MediaEngine] Live Hugging Face API search fallback ({e})")
            source_mode = "catalog_fallback"
    else:
        source_mode = "test_catalog"

    # Also match against the built-in Hugging Face release catalog (or synthesize if exact repo was requested offline)
    builtin_recs = build_llm_recommendations(
        accel=accel,
        ram_gb=eff_ram,
        active_model=active_model,
        custom_models=rag_cfg.get("custom_hf_models", []),
        sort_by=sort_by,
    )
    seen_repos = {str(r.get("hf_repo", "")).lower() for r in results}
    q_lower = clean_q.lower()
    for m in builtin_recs.get("models", []):
        haystack = f"{m.get('name', '')} {m.get('hf_repo', '')} {m.get('id', '')} {m.get('family', '')} {m.get('params', '')}".lower()
        if not q_lower or q_lower in haystack:
            repo_l = str(m.get("hf_repo", "")).lower()
            if repo_l not in seen_repos:
                seen_repos.add(repo_l)
                results.append(m)

    # If the user searched for a specific `org/model` and offline fallback didn't find it, synthesize & evaluate it
    if not results and clean_q:
        synth_repo = clean_q if "/" in clean_q else f"huggingface/{clean_q}"
        results.append(
            _format_hf_api_item(
                {"id": synth_repo, "tags": [], "pipeline_tag": "text-generation"},
                accel,
                eff_ram,
                active_norm,
            )
        )

    # Filter out older models released before 2026
    if min_release_year and min_release_year >= 2026:
        results = [m for m in results if is_model_2026_or_newer(m)]

    # Sort results according to sort_by
    if sort_by == "date":
        results.sort(
            key=lambda x: (
                float(x.get("release_timestamp") or 0.0),
                int(x.get("downloads") or 0),
            ),
            reverse=True,
        )
    elif sort_by == "recommended":
        results.sort(
            key=lambda x: (
                1 if x.get("recommended") else 0,
                1 if x.get("fits_hardware") else 0,
                float(x.get("release_timestamp") or 0.0),
            ),
            reverse=True,
        )
    elif sort_by == "downloads":
        results.sort(
            key=lambda x: (
                int(x.get("downloads") or 0),
                float(x.get("release_timestamp") or 0.0),
            ),
            reverse=True,
        )
    elif sort_by == "size_asc":
        results.sort(key=lambda x: float(x.get("est_ram_gb") or x.get("vram_or_ram_gb") or 0.0))
    elif sort_by == "size_desc":
        results.sort(
            key=lambda x: float(x.get("est_ram_gb") or x.get("vram_or_ram_gb") or 0.0),
            reverse=True,
        )

    # Prioritize exact repo match, official author organization, or top canonical release if user queried a specific model
    exact_target = clean_q.lower()
    if exact_target and results:

        def match_priority(m: dict[str, Any]) -> tuple:
            repo = str(m.get("hf_repo", "")).lower()
            mid = str(m.get("id", "")).lower()
            name = str(m.get("name", "")).lower()
            dls = int(m.get("downloads", 0) or 0)

            # Exact full repo match
            if repo == exact_target or mid == exact_target:
                return (4, dls)
            # Exact model name match (e.g. org/exact_target)
            if repo.endswith(f"/{exact_target}") or name == exact_target:
                return (3, dls)
            # Official organization match when searching query (e.g. google/..., qwen/..., deepseek-ai/..., meta-llama/...)
            is_official_org = any(
                repo.startswith(f"{org}/")
                for org in ("google", "meta-llama", "qwen", "deepseek-ai", "mistralai", "microsoft")
            )
            if exact_target in repo and is_official_org:
                return (2, dls)
            # Query in repo name
            if exact_target in repo:
                return (1, dls)
            return (0, dls)

        best_score = max(match_priority(m)[0] for m in results)
        if best_score >= 2:
            matched = [m for m in results if match_priority(m)[0] >= 2]
            matched.sort(key=lambda m: (match_priority(m)[0], int(m.get("downloads", 0) or 0)), reverse=True)
            rest = [m for m in results if match_priority(m)[0] < 2]
            results = matched + rest
        elif exact_match_item and not any(
            str(m.get("hf_repo", "")).lower() == exact_match_item.get("hf_repo", "").lower() for m in results
        ):
            results.insert(0, exact_match_item)

    return {
        "status": "ok",
        "source": source_mode,
        "query": clean_q,
        "count": len(results[:safe_limit]),
        "sort_by": sort_by,
        "hardware_profile": builtin_recs.get("hardware_profile", {}),
        "models": results[:safe_limit],
    }


def pull_huggingface_model(repo_id: str, activate: bool = True) -> dict[str, Any]:
    """
    Pulls/registers a release model from https://huggingface.co into the user's
    ZettAI model catalog, evaluates whether it fits the user's hardware, and
    returns a prominent hardware warning if the model exceeds NAS limits.
    """
    clean_repo = _normalize_hf_repo_input(repo_id)
    if not clean_repo:
        raise ValueError("Hugging Face repository ID or URL is required (e.g. 'Qwen/Qwen2.5-7B-Instruct-GGUF').")

    ram_bytes = read_total_ram_bytes()
    eff_ram = max(4.0, round(ram_bytes / (1024**3), 1))
    accel = detect_hardware_accelerator()
    rag = get_rag_engine()
    rag_cfg = rag.get_config()
    active_norm = str(rag_cfg.get("active_model") or "qwen2.5:3b").lower()

    fetched_item: dict[str, Any] | None = None
    if os.environ.get("TESTING") != "1" and os.environ.get("ZETTNAS_TEST_MODE") != "1" and "/" in clean_repo:
        try:
            exact_url = f"https://huggingface.co/api/models/{urllib.parse.quote(clean_repo, safe='/')}"
            req = urllib.request.Request(
                exact_url,
                headers={"User-Agent": "ZettNAS-Toolkit/1.0 (https://huggingface.co)"},
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict) and data.get("id"):
                    fetched_item = data
        except Exception as e:
            logger.debug(f"[MediaEngine] HF metadata fetch fallback for {clean_repo}: {e}")

    if fetched_item is None:
        fetched_item = {
            "id": clean_repo if "/" in clean_repo else f"huggingface/{clean_repo}",
            "tags": [],
            "pipeline_tag": "text-generation",
        }

    model_entry = _format_hf_api_item(fetched_item, accel=accel, eff_ram=eff_ram, active_norm=active_norm)
    model_entry["pulled_from_hf"] = True
    model_entry["pulled_at"] = time.time()

    custom_list = list(rag_cfg.get("custom_hf_models") or [])
    custom_list = [
        c
        for c in custom_list
        if isinstance(c, dict) and str(c.get("hf_repo", "")).lower() != str(model_entry["hf_repo"]).lower()
    ]
    custom_list.insert(0, model_entry)

    removed_list = list(rag_cfg.get("removed_models") or [])
    clean_repo_l = str(clean_repo).lower()
    clean_removed = [
        r
        for r in removed_list
        if str(r).lower()
        not in (
            clean_repo_l,
            f"hf.co/{clean_repo_l}",
            clean_repo_l.replace("hf.co/", ""),
            str(model_entry.get("id", "")).lower(),
            str(model_entry.get("ollama_tag", "")).lower(),
        )
    ]

    updates: dict[str, Any] = {
        "custom_hf_models": custom_list[:25],
        "removed_models": clean_removed,
    }
    is_embed = is_embedding_only_model(model_entry)
    if is_embed:
        model_entry["role"] = f"Vector Embedding Model ({model_entry.get('pipeline_tag') or 'embedding'})"
        model_entry["category"] = "Embedding & Semantic Search"
        model_entry["is_embedding"] = True
        updates["embedding_model"] = model_entry["id"]
        model_entry["warning_message"] = (
            f"Configured '{model_entry['id']}' as vector embedding engine for semantic search & RAG. "
            f"Conversational chat remains '{rag_cfg.get('active_model') or 'qwen2.5:3b'}'."
        )
    elif activate:
        updates["active_model"] = model_entry["id"]
        updates["llm_model"] = model_entry["id"]
        model_entry["is_selected"] = True
        model_entry["active"] = True

    updated_cfg = rag.update_config(updates)
    recs = build_llm_recommendations(
        accel=accel,
        ram_gb=eff_ram,
        active_model=updated_cfg.get("active_model") or model_entry["id"],
        custom_models=updated_cfg.get("custom_hf_models", []),
        removed_models=updated_cfg.get("removed_models", []),
    )

    return {
        "status": "ok",
        "model": model_entry,
        "fits_hardware": model_entry["fits_hardware"],
        "hardware_warning": model_entry["hardware_warning"],
        "warning_message": model_entry.get("warning_message"),
        "active_model": updated_cfg.get("active_model"),
        "llm_recommendations": recs,
    }


def remove_llm_model(model_id: str) -> dict[str, Any]:
    """
    Removes/deletes a model from the ZettAI catalog:
    1. Removes it from custom_hf_models (if user-pulled).
    2. Adds its normalized tags to removed_models in rag_config so it no longer appears in recommendations.
    3. Deletes it from local Ollama if present (via DELETE /api/delete).
    4. If the removed model was the active model, safely falls back to the top remaining model or NPU model.
    5. Returns updated recommendations and active_model.
    """
    clean_id = str(model_id or "").strip()
    if not clean_id:
        raise ValueError("Model identifier is required.")

    rag = get_rag_engine()
    rag_cfg = rag.get_config()

    norm_target = clean_id.lower()
    tag_norm = norm_target.replace("hf.co/", "")

    # 1. Remove from custom_hf_models
    custom_list = list(rag_cfg.get("custom_hf_models") or [])
    updated_custom = [
        c
        for c in custom_list
        if isinstance(c, dict)
        and str(c.get("id", "")).lower() not in (norm_target, tag_norm, f"hf.co/{tag_norm}")
        and str(c.get("ollama_tag", "")).lower() not in (norm_target, tag_norm, f"hf.co/{tag_norm}")
        and str(c.get("hf_repo", "")).lower() not in (norm_target, tag_norm, f"hf.co/{tag_norm}")
    ]

    # 2. Add to removed_models
    removed_list = list(rag_cfg.get("removed_models") or [])
    new_removed = set(str(r).lower() for r in removed_list)
    new_removed.add(norm_target)
    new_removed.add(tag_norm)
    if "/" in tag_norm:
        new_removed.add(f"hf.co/{tag_norm}")

    # 3. Delete from the Ollama runtime ZettNAS actually talks to (AI-17)
    deleted_from_runtime = False
    try:
        from backend.services.rag_engine import _resolve_ollama_host

        runtime_hosts = [_resolve_ollama_host()]
    except Exception:
        runtime_hosts = ["http://127.0.0.1:11434"]
    for base_url in runtime_hosts:
        try:
            del_url = f"{base_url}/api/delete"
            for tag_candidate in (clean_id, tag_norm, norm_target):
                d_payload = json.dumps({"name": tag_candidate}).encode("utf-8")
                d_req = urllib.request.Request(
                    del_url,
                    data=d_payload,
                    headers={"Content-Type": "application/json", "User-Agent": "ZettNAS-Toolkit/2.0"},
                    method="DELETE",
                )
                try:
                    with urllib.request.urlopen(d_req, timeout=5.0) as resp:
                        if resp.status == 200:
                            logger.info(f"[MediaEngine] Deleted model {tag_candidate} from Ollama at {base_url}")
                            deleted_from_runtime = True
                            break
                except urllib.error.HTTPError:
                    continue
        except Exception:
            logger.debug("backend.services.media_engine.remove_llm_model: ignored error", exc_info=True)

    # 4. Check active model fallback if current active was deleted
    current_active = str(rag_cfg.get("active_model", "")).strip().lower()
    ram_bytes = read_total_ram_bytes()
    eff_ram = max(4.0, round(ram_bytes / (1024**3), 1))
    accel = detect_hardware_accelerator()

    fallback_active = None
    if current_active in (norm_target, tag_norm) or current_active.replace("hf.co/", "") == tag_norm:
        temp_recs = build_llm_recommendations(
            accel=accel,
            ram_gb=eff_ram,
            active_model="builtin-npu",
            custom_models=updated_custom,
            removed_models=sorted(list(new_removed)),
        )
        remaining = temp_recs.get("models") or []
        if remaining:
            fallback_active = remaining[0].get("id")
        else:
            fallback_active = "builtin-npu"

    updates: dict[str, Any] = {
        "custom_hf_models": updated_custom,
        "removed_models": sorted(list(new_removed)),
    }
    if fallback_active:
        updates["active_model"] = fallback_active
        updates["llm_model"] = fallback_active

    updated_cfg = rag.update_config(updates)

    recs = build_llm_recommendations(
        accel=accel,
        ram_gb=eff_ram,
        active_model=updated_cfg.get("active_model") or fallback_active or "builtin-npu",
        custom_models=updated_cfg.get("custom_hf_models", []),
        removed_models=updated_cfg.get("removed_models", []),
    )

    return {
        "status": "ok",
        "removed_model": clean_id,
        "deleted_from_runtime": deleted_from_runtime,
        "active_model": updated_cfg.get("active_model"),
        "llm_recommendations": recs,
    }


class MediaEngine:
    """Manages AI media indexing, multi-modal RAG, and semantic visual search."""

    def __init__(self):
        self._lock = threading.Lock()
        self._is_scanning = False

    def get_status(self) -> dict[str, Any]:
        ram_bytes = read_total_ram_bytes()
        ram_gb = round(ram_bytes / (1024**3), 1)
        is_gated = ram_bytes < MIN_RAM_REQUIRED_BYTES

        accel = detect_hardware_accelerator()
        persisted = read_json(MEDIA_STATUS_FILE, {})
        rag = get_rag_engine()
        if os.environ.get("TESTING") != "1" and os.environ.get("ZETTNAS_TEST_MODE") != "1":
            try:
                rag.sync_watched_deferred_queue()
                rag.check_and_trigger_spinup_auto_learn(background=True)
            except Exception as e:
                logger.debug(f"[MediaEngine] Spin-up auto-learn check error: {e}")

        rag_stats = rag.get_index_stats()
        rag_cfg = rag.get_config()
        sync_progress = rag.get_sync_progress()
        available_folders = rag.discover_available_folders()
        sleeping_disks = get_sleeping_disks_list()
        running_disks = get_running_disks_list()
        deferred_queue = rag.get_deferred_queue()
        learning_results = rag.get_learning_results()
        llm_recs = build_llm_recommendations(
            accel=accel,
            ram_gb=ram_gb,
            active_model=rag_cfg.get("active_model") or rag_cfg.get("llm_model") or "qwen2.5:3b",
            custom_models=rag_cfg.get("custom_hf_models", []),
        )

        indexed_count = max(int(persisted.get("indexed_count", 0)), int(rag_stats.get("indexed_count", 0)))
        last_ts = rag_stats.get("last_scan_timestamp") or persisted.get("last_scan_timestamp")

        base_cats = persisted.get(
            "categories",
            {"faces": 0, "locations": 0, "objects": 0, "albums": 0},
        )
        categories = {
            "faces": base_cats.get("faces", 0),
            "locations": base_cats.get("locations", 0),
            "objects": max(base_cats.get("objects", 0), rag_stats.get("total_photos", 0)),
            "albums": base_cats.get("albums", 0),
            "photos": rag_stats.get("total_photos", 0),
            "videos": rag_stats.get("total_videos", 0),
            "documents": rag_stats.get("total_docs", 0),
            "recipes": rag_stats.get("total_recipes", 0),
            "chunks": rag_stats.get("total_chunks", 0),
        }

        return {
            "status": "ok",
            "enabled": bool(rag_cfg.get("enabled", True)),
            "zettai_status": learning_results.get("zettai_status", "Idle"),
            "is_gated": is_gated,
            "total_ram_bytes": ram_bytes,
            "total_ram_gb": ram_gb,
            "min_ram_required_gb": 8.0,
            "gate_reason": "Insufficient host RAM (< 8GB). AI media engine is locked to protect NAS core stability."
            if is_gated
            else None,
            "acceleration": accel,
            "hardware": accel,
            "llm_recommendations": llm_recs,
            "learning_results": learning_results,
            "index_stats": rag_stats,
            "sync_progress": sync_progress,
            "sync_state": sync_progress.get("state", "idle"),
            "is_scanning": self._is_scanning or rag_stats.get("is_scanning", False),
            "is_paused": rag_stats.get("is_paused", False),
            "watched_paths": rag_cfg.get("watched_paths", []),
            "excluded_paths": rag_cfg.get("excluded_paths", []),
            "scope_mode": rag_cfg.get("scope_mode", "include"),
            "available_folders": available_folders,
            "indexed_count": indexed_count,
            "last_scan_timestamp": last_ts,
            "categories": categories,
            "standby_guard": {
                "active": True,
                "respect_standby": rag_cfg.get("respect_standby", True),
                "auto_learn_on_spinup": rag_cfg.get("auto_learn_on_spinup", True),
                "sleeping_disks_count": len(sleeping_disks),
                "sleeping_disks": sleeping_disks,
                "running_disks_count": len(running_disks),
                "running_disks": running_disks,
                "deferred_queue_count": rag_stats.get("deferred_queue_count", 0),
                "deferred_queue": deferred_queue,
                "last_auto_learn_event": sync_progress.get("last_auto_learn_event"),
                "zero_disk_wakeups": True,
            },
        }

    def trigger_scan(self, media_path: str = "/mnt/storage/media") -> dict[str, Any]:
        status = self.get_status()
        if status["is_gated"]:
            raise PermissionError(status["gate_reason"])

        with self._lock:
            if self._is_scanning:
                return {"status": "already_scanning", "message": "Media indexing scan is already in progress."}

            self._is_scanning = True
            t = threading.Thread(
                target=self._scan_worker,
                args=(media_path,),
                daemon=True,
                name="MediaEngineScanner",
            )
            t.start()

        return {
            "status": "started",
            "media_path": media_path,
            "acceleration_backend": status["acceleration"]["acceleration_backend"],
        }

    def _scan_worker(self, media_path: str) -> None:
        try:
            logger.info(f"[MediaEngine] Starting spindown-safe multi-modal indexing on {media_path}")
            rag = get_rag_engine()
            cfg = rag.get_config()
            res = rag.index_directory(
                media_path,
                respect_standby=bool(cfg.get("respect_standby", True)),
            )
            stats = rag.get_index_stats()
            count = stats.get("indexed_count", res.get("indexed_files", 0))

            atomic_write_json(
                MEDIA_STATUS_FILE,
                {
                    "indexed_count": count,
                    "last_scan_timestamp": time.time(),
                    "categories": {
                        "faces": max(0, stats.get("total_photos", 0) // 4),
                        "locations": max(0, stats.get("total_photos", 0) // 6),
                        "objects": stats.get("total_photos", 0),
                        "albums": max(0, stats.get("total_photos", 0) // 10),
                        "photos": stats.get("total_photos", 0),
                        "videos": stats.get("total_videos", 0),
                        "documents": stats.get("total_docs", 0),
                        "recipes": stats.get("total_recipes", 0),
                    },
                },
            )
            logger.info(f"[MediaEngine] Completed indexing ({count} total assets).")
        except Exception as e:
            logger.error(f"[MediaEngine] Indexing scan failed: {e}")
        finally:
            with self._lock:
                self._is_scanning = False


_MEDIA_ENGINE: MediaEngine | None = None


def get_media_engine() -> MediaEngine:
    global _MEDIA_ENGINE
    if _MEDIA_ENGINE is None:
        _MEDIA_ENGINE = MediaEngine()
    return _MEDIA_ENGINE
