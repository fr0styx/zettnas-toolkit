"""The NAS tools ZettAI can run: status, disks, fans, Docker, file search, sync, calculations, storage and network (split out of ai_chat_agent.py, ARCH-1)."""

import ast
import contextvars
import os
import re
import time
from typing import (  # noqa: F401
    Any,
)

from backend.config import (  # noqa: F401
    FAN_STATE_FILE,
    logger,
)
from backend.fsutil import (  # noqa: F401
    atomic_write_json,
    json_locked,
    read_json,
)
from backend.services.chat_context import (  # noqa: F401
    _grounding_or_none,
)
from backend.services.media_engine import (  # noqa: F401
    detect_hardware_accelerator,
    read_total_ram_bytes,
)
from backend.services.rag_engine import (  # noqa: F401
    get_running_disks_list,
    get_sleeping_disks_list,
    similarity_profile,
)
from backend.settings import test_mode
from backend.state import (  # noqa: F401
    Z_STATE,
)


def _core():
    """backend.services.ai_chat_agent, read at call time: it holds the shared state, and tests patch names there."""
    from backend.services import ai_chat_agent

    return ai_chat_agent


def tool_get_system_telemetry() -> dict[str, Any]:
    """Reads live host CPU, RAM, temperature, uptime, and NPU/GPU accelerator status."""
    ram_total_b = read_total_ram_bytes()
    ram_total_gb = round(ram_total_b / (1024**3), 1)
    ram_avail_gb = round(ram_total_gb * 0.62, 1)
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        kb = int(line.split()[1])
                        ram_avail_gb = round(kb / (1024**2), 1)
                        break
    except Exception:
        logger.debug("backend.services.ai_chat_agent.tool_get_system_telemetry: ignored error", exc_info=True)
    ram_used_gb = round(max(0.1, ram_total_gb - ram_avail_gb), 1)
    ram_pct = round((ram_used_gb / max(1.0, ram_total_gb)) * 100.0, 1)

    cached = Z_STATE.cached_stats if isinstance(Z_STATE.cached_stats, dict) else {}
    cpu_raw = cached.get("cpu")
    if isinstance(cpu_raw, dict):
        cpu_pct = cached.get("cpu_pct") if cached.get("cpu_pct") is not None else (cpu_raw.get("util") or 8.5)
        cpu_temp = cached.get("cpu_temp") if cached.get("cpu_temp") is not None else (cpu_raw.get("temp") or 42)
    else:
        cpu_pct = cached.get("cpu_pct") or cpu_raw or 8.5
        cpu_temp = cached.get("cpu_temp") or 42
    uptime_s = int(time.time() - getattr(Z_STATE, "boot_time", time.time()))

    accel = detect_hardware_accelerator()
    rag_cfg = _core().get_rag_engine().get_config()

    return {
        "tool": "get_system_telemetry",
        "status": "ok",
        "cpu_load_pct": cpu_pct,
        "cpu_temp_c": cpu_temp,
        "ram_total_gb": ram_total_gb,
        "ram_used_gb": ram_used_gb,
        "ram_available_gb": ram_avail_gb,
        "ram_used_pct": ram_pct,
        "uptime_seconds": uptime_s,
        "active_ai_model": rag_cfg.get("active_model") or "qwen2.5:3b",
        "hardware_accelerator": {
            "active_tier": accel.get("active_tier", 1),
            "device_label": accel.get("device_label", "CPU"),
            "secondary_gpu": accel.get("secondary_gpu"),
            "has_npu": bool(accel.get("has_npu")),
            "has_gpu": bool(accel.get("has_igpu") or accel.get("has_cuda") or accel.get("has_rocm")),
        },
    }


def tool_get_disks_and_standby_status() -> dict[str, Any]:
    """
    Returns physical disk power states and cached temperatures without waking sleeping drives
    (strictly obeys AGENTS.md §1.2 Standby Safety Invariant).
    """
    sleeping = get_sleeping_disks_list()
    running = get_running_disks_list()
    smart_cache = {}
    with Z_STATE.lock:
        for dev, val in (Z_STATE.cached_smart_data or {}).items():
            if isinstance(val, (tuple, list)) and len(val) >= 2:
                smart_cache[dev] = {"temp_c": val[0], "power_state": val[1]}
            elif isinstance(val, dict):
                smart_cache[dev] = val

    disks_summary = []
    for d in running:
        info = smart_cache.get(d, {})
        disks_summary.append(
            {
                "device": d,
                "state": "active/running",
                "temp_c": info.get("temp_c"),
            }
        )
    for d in sleeping:
        info = smart_cache.get(d, {})
        disks_summary.append(
            {
                "device": d,
                "state": "standby (sleeping — protected)",
                "temp_c": info.get("temp_c"),
            }
        )

    rag_stats = _core().get_rag_engine().get_index_stats()
    return {
        "tool": "get_disks_and_standby_status",
        "status": "ok",
        "zero_disk_wakeups": True,
        "running_disks_count": len(running),
        "running_disks": running,
        "sleeping_disks_count": len(sleeping),
        "sleeping_disks": sleeping,
        "disks": disks_summary,
        "deferred_ai_queue_count": rag_stats.get("deferred_queue_count", 0),
    }


def tool_get_fan_and_thermal_status() -> dict[str, Any]:
    """Reads current fan acoustic profile, thermal limits, and PWM tracker state."""
    defaults = {
        "profile": "auto",
        "manual_pct": 60,
        "temp_min": 37,
        "temp_max": 50,
        "zero_rpm_enabled": False,
    }
    saved = read_json(FAN_STATE_FILE, {})
    if isinstance(saved, dict):
        defaults.update(saved)

    pwm_state = {}
    with Z_STATE.lock:
        for k, v in (Z_STATE.fan_state_tracker or {}).items():
            if isinstance(v, dict):
                pwm_state[k] = v.get("current", 67)

    return {
        "tool": "get_fan_and_thermal_status",
        "status": "ok",
        "profile": defaults.get("profile", "auto"),
        "manual_pct": defaults.get("manual_pct", 60),
        "temp_min_c": defaults.get("temp_min", 37),
        "temp_max_c": defaults.get("temp_max", 50),
        "zero_rpm_enabled": bool(defaults.get("zero_rpm_enabled", False)),
        "pwm_channels": pwm_state,
        "cpu_fan_protected": True,
    }


@json_locked(lambda *a, **k: FAN_STATE_FILE)
def tool_set_fan_profile(
    profile: str,
    zero_rpm_enabled: bool | None = None,
    principal: Any = None,
) -> dict[str, Any]:
    """Updates the NAS fan profile safely while preserving CPU fan (pwm3) protection."""
    if not _core()._has_write_permission(principal, ("hardware:fans", "system:config", "storage:admin")):
        return {
            "tool": "set_fan_profile",
            "status": "denied",
            "error": "Permission denied: hardware:fans scope required to change fan profiles.",
        }

    clean_prof = str(profile or "").strip().lower()
    alias_map = {
        "silent": "quiet",
        "eco": "quiet",
        "low": "quiet",
        "normal": "balanced",
        "standard": "balanced",
        "max": "full",
        "full_speed": "full",
        "turbo": "performance",
        "high": "performance",
    }
    clean_prof = alias_map.get(clean_prof, clean_prof)
    valid = {"auto", "quiet", "balanced", "performance", "full", "manual"}
    if clean_prof not in valid:
        return {
            "tool": "set_fan_profile",
            "status": "error",
            "error": f"Unsupported fan profile '{profile}'. Valid profiles: auto, quiet, balanced, performance, full.",
        }

    cfg = read_json(FAN_STATE_FILE, {})
    if not isinstance(cfg, dict):
        cfg = {}
    prev_profile = cfg.get("profile", "auto")
    cfg["profile"] = clean_prof
    if zero_rpm_enabled is not None:
        cfg["zero_rpm_enabled"] = bool(zero_rpm_enabled)

    if not test_mode():
        atomic_write_json(FAN_STATE_FILE, cfg)

    return {
        "tool": "set_fan_profile",
        "status": "ok",
        "previous_profile": prev_profile,
        "new_profile": clean_prof,
        "zero_rpm_enabled": bool(cfg.get("zero_rpm_enabled", False)),
        "note": "Fan profile updated. CPU fan (pwm3) remains continuously active per thermal safety invariant.",
    }


def tool_list_docker_containers(limit: int = 40) -> dict[str, Any]:
    """Lists Docker containers on the NAS with state, image, uptime, and identifies longest-running container."""
    if test_mode():
        return {
            "tool": "list_docker_containers",
            "status": "ok",
            "total": 3,
            "running": 3,
            "stopped": 0,
            "longest_running": {
                "name": "immich_server",
                "status": "Up 2 days",
                "uptime": "Up 2 days",
                "created": 1728800000,
                "image": "ghcr.io/immich-app/immich-server:release",
            },
            "containers": [
                {
                    "name": "zettnas-toolkit",
                    "image": "ghcr.io/fr0styx/zettnas-toolkit:latest",
                    "state": "running",
                    "status": "Up 4 hours",
                    "created": 1729000000,
                },
                {
                    "name": "sonarr",
                    "image": "lscr.io/linuxserver/sonarr:latest",
                    "state": "running",
                    "status": "Up 2 days",
                    "created": 1728900000,
                },
                {
                    "name": "immich_server",
                    "image": "ghcr.io/immich-app/immich-server:release",
                    "state": "running",
                    "status": "Up 2 days",
                    "created": 1728800000,
                },
            ],
        }

    containers: list[dict[str, Any]] = []
    try:
        from backend.hardware.docker_stats import read_docker_containers

        dock_list = read_docker_containers(force=True)
        if dock_list:
            for c in dock_list:
                containers.append(
                    {
                        "name": c.get("name", "unknown"),
                        "image": c.get("image", ""),
                        "state": c.get("state", "unknown"),
                        "status": c.get("status", ""),
                        "ports": c.get("ports", ""),
                        "created": c.get("created", 0),
                        "cpu_pct": c.get("cpu_pct", 0.0),
                        "mem_used": c.get("mem_used", 0),
                        "stack": c.get("stack", ""),
                    }
                )
    except Exception as e:
        logger.debug(f"[AIChatAgent] read_docker_containers error: {e}")

    running = [c for c in containers if c.get("state") == "running"]

    def _created_sort_key(item: dict[str, Any]) -> float:
        cval = item.get("created", 0)
        try:
            val = float(cval)
            return val if val > 0 else float("inf")
        except (ValueError, TypeError):
            return float("inf")

    running_sorted = sorted(running, key=_created_sort_key)
    longest_running_info = None
    if running_sorted:
        oldest = running_sorted[0]
        longest_running_info = {
            "name": oldest.get("name"),
            "status": oldest.get("status"),
            "uptime": oldest.get("status"),
            "created": oldest.get("created"),
            "image": oldest.get("image"),
        }

    running_cnt = len(running)
    return {
        "tool": "list_docker_containers",
        "status": "ok",
        "total": len(containers),
        "running": running_cnt,
        "stopped": len(containers) - running_cnt,
        "longest_running": longest_running_info,
        "containers": containers[: max(1, min(int(limit or 40), 60))],
    }


def tool_control_docker_container(
    container_name: str,
    action: str = "restart",
    principal: Any = None,
) -> dict[str, Any]:
    """Starts, stops, or restarts a specific Docker container with safety checks."""
    if not _core()._has_write_permission(
        principal,
        ("containers:write", "containers:manage", "docker:write", "docker:admin", "system:config", "storage:admin"),
    ):
        return {
            "tool": "control_docker_container",
            "status": "denied",
            "error": "Permission denied: containers:write or admin scope required to control containers.",
        }

    clean_name = re.sub(r"[^a-zA-Z0-9_.-]", "", str(container_name or "").strip())
    clean_action = str(action or "restart").strip().lower()
    if clean_action not in ("start", "stop", "restart"):
        return {"tool": "control_docker_container", "status": "error", "error": f"Invalid action '{action}'."}
    if not clean_name:
        return {"tool": "control_docker_container", "status": "error", "error": "Container name is required."}
    if clean_name.lower() in (
        "zettnas-toolkit",
        "zettnas-db",
        "zettnas-ollama",
        "zettnas-mariadb",
        "zettnas-postgres",
    ) and clean_action in ("stop", "restart"):
        return {
            "tool": "control_docker_container",
            "status": "blocked",
            "error": f"Safety guard: Refusing to {clean_action} critical system container '{clean_name}' from inside AI assistant.",
        }

    if test_mode():
        return {
            "tool": "control_docker_container",
            "status": "ok",
            "container": clean_name,
            "action": clean_action,
            "message": f"Container '{clean_name}' {clean_action}ed successfully (test mode).",
        }

    try:
        from backend.hardware.docker_stats import container_action

        res = container_action(clean_name, clean_action)
        if res.get("success"):
            return {
                "tool": "control_docker_container",
                "status": "ok",
                "container": clean_name,
                "action": clean_action,
                "message": f"Container '{clean_name}' {clean_action}ed successfully.",
            }
        elif res.get("error") and res.get("error") != "Docker socket not available":
            logger.debug(f"[AIChatAgent] container_action failed: {res.get('error')}")
    except Exception as e:
        logger.debug(f"[AIChatAgent] container_action exception: {e}")

    # SEC-37: only through the Docker API proxy, never the docker command line
    return {
        "tool": "control_docker_container",
        "status": "error",
        "container": clean_name,
        "action": clean_action,
        "error": "The container could not be changed through ZettNAS's Docker connection.",
    }


# The file or folder a question is about ("Ask Zetty about this"); set per chat turn
FOCUS_PATH: contextvars.ContextVar[str | None] = contextvars.ContextVar("zettnas_chat_focus", default=None)


def _extract_folder_and_intent(query: str) -> tuple[str | None, str, str]:
    """
    Extracts a target folder path, remaining clean query, and retrieval mode (comprehensive vs targeted).
    """
    clean = str(query or "").strip()
    folder_path: str | None = None
    mode = "targeted"

    path_match = re.search(
        r"(?:in|from|under|for|inside|of|audit|summarize|index|scan|about)\s+(?:the\s+)?(?:folder|directory|dir|share|path)?\s*[:=]?\s*['\"]?(/mnt/[^\s'\"]+|/app/[^\s'\"]+|/homes/[^\s'\"]+|/[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)+)['\"]?",
        clean,
        re.IGNORECASE,
    )
    if not path_match:
        path_match = re.search(
            r"['\"]?(/mnt/[^\s'\"]+|/app/[^\s'\"]+|/homes/[^\s'\"]+|/[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)+)['\"]?",
            clean,
        )

    if path_match:
        folder_path = os.path.normpath(path_match.group(1)).replace("\\", "/")

    low = clean.lower()
    comprehensive_triggers = (
        "audit",
        "summarize",
        "summary",
        "overview",
        "review",
        "all files",
        "inventory",
        "everything in",
        "what is in",
        "whats in",
        "what's in",
        "list all",
        "examine",
        "compare all",
        "catalog",
    )
    if any(t in low for t in comprehensive_triggers):
        mode = "comprehensive"

    remaining_query = clean
    if folder_path:
        remaining_query = (
            re.sub(
                rf"(?:in|from|under|for|inside|of|audit|summarize)\s+(?:the\s+)?(?:folder|directory|dir|share|path)?\s*[:=]?\s*['\"]?{re.escape(folder_path)}['\"]?",
                "",
                remaining_query,
                flags=re.IGNORECASE,
            )
            .replace(folder_path, "")
            .strip()
        )

    return folder_path, remaining_query, mode


def tool_search_nas_knowledge(
    query: str,
    principal: Any = None,
    strict_relevance: bool = False,
    folder_path: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """
    Queries the local NVMe RAG index for matching documents, recipes, and photos,
    or aggregates context across whatever folder (0 disk wakeups).
    """
    from backend.services.path_access import user_can_access_path

    rag = _core().get_rag_engine()

    extracted_folder, clean_q, extracted_mode = _extract_folder_and_intent(query)
    target_folder = (folder_path or FOCUS_PATH.get() or extracted_folder or "").strip() or None
    effective_mode = mode or extracted_mode or "targeted"
    effective_query = (clean_q if (clean_q and len(clean_q) >= 2) else query).strip()

    if target_folder:
        if principal is not None and not user_can_access_path(target_folder, principal):
            return {
                "tool": "search_nas_knowledge",
                "status": "denied",
                "query": query,
                "folder_path": target_folder,
                "error": f"Permission denied: Access to '{target_folder}' is not permitted for current user.",
                "citations_count": 0,
                "citations": [],
                "photos_count": 0,
                "photos": [],
                "grounding_confidence_score": 0,
                "crag_grade": "low",
            }

    folder_manifest = None
    context_text = ""
    grounding_score: int | None = None
    crag_grade = "unrated"
    raw_citations: list[dict[str, Any]] = []
    raw_photos: list[dict[str, Any]] = []
    answer_summary = ""
    structured_card = None

    # AI-22: a question about one file is answered from that file's own text, in any language,
    # whenever it fits; only long files fall back to a targeted search inside the file.
    one_file: dict[str, Any] = {}
    if target_folder and hasattr(rag, "file_chunks"):
        try:
            one_file = rag.file_chunks(target_folder) or {}
        except Exception:
            logger.debug("chat_nas_tools: file_chunks failed", exc_info=True)
    if (
        one_file.get("found")
        and one_file.get("chunks")
        and (one_file.get("complete") or effective_mode == "comprehensive")
    ):
        context_text = "\n\n".join(c["text"] for c in one_file["chunks"])
        crag_grade = "high"
        raw_citations = [
            {
                "file_id": one_file["file_id"],
                "name": one_file["name"],
                "path": target_folder,
                "doc_title": one_file.get("title") or one_file["name"],
                "breadcrumb": c.get("heading") or "",
                "excerpt": c["text"][:450],
                "full_parent_context": c["text"],
                "score": 1.0,
                "parent_chunk_id": c["chunk_id"],
                "line_start": int(c.get("line_start") or 1),
                "line_end": int(c.get("line_end") or 1),
                "doc_type": one_file.get("doc_type", "document"),
                "source_modality": "document",
            }
            for c in one_file["chunks"]
        ]
    elif target_folder and effective_mode == "comprehensive":
        agg_res = rag.aggregate_folder_context(
            folder_path=target_folder,
            query=effective_query,
            mode="comprehensive",
            max_tokens=4000,
            principal=principal,
        )
        folder_manifest = agg_res.get("manifest")
        context_text = agg_res.get("context_text", "")
        answer_summary = agg_res.get("summary", "")
        grounding_score = _grounding_or_none(agg_res.get("grounding_confidence_score"))
        crag_grade = str(agg_res.get("crag_grade") or "high")
        chunks = agg_res.get("chunks", [])
        raw_citations = [
            {
                "file_id": c.get("file_id"),
                "name": c.get("name")
                or c.get("file_name")
                or os.path.basename(c.get("file_path", "") or c.get("path", "")),
                "path": c.get("path") or c.get("file_path"),
                "doc_title": c.get("doc_title") or c.get("title") or c.get("name") or c.get("file_name") or "",
                "breadcrumb": c.get("breadcrumb") or c.get("heading") or "",
                "excerpt": (c.get("chunk_text") or c.get("parent_text") or c.get("excerpt") or "")[:450],
                "full_parent_context": c.get("full_parent_context")
                or c.get("parent_text")
                or c.get("chunk_text")
                or c.get("excerpt")
                or "",
                "score": float(c.get("score") or c.get("mmr_score") or 0.9),
                "parent_chunk_id": c.get("parent_chunk_id"),
                "line_start": int(c.get("line_start", 1)),
                "line_end": int(c.get("line_end", 1)),
                "doc_type": c.get("doc_type", "document"),
                "source_modality": c.get("source_modality", "document"),
            }
            for c in chunks
        ]
    else:
        from backend.services import rag_tags

        # "my bills from 2024": the question's kind and year become filters (AI-36); with nothing
        # tagged so, the search runs again without them
        want = rag_tags.tags_in_question(effective_query)
        ask_res = rag.ask(
            query=effective_query,
            scope="all",
            path_prefix=target_folder,
            top_k=6,
            principal=principal,
            tags=want or None,
        )
        if want and not (ask_res.get("citations") or ask_res.get("photos")):
            ask_res = rag.ask(
                query=effective_query, scope="all", path_prefix=target_folder, top_k=6, principal=principal
            )
        raw_citations = list(ask_res.get("citations") or [])
        raw_photos = list(ask_res.get("photos") or [])
        answer_summary = ask_res.get("answer") or ""
        structured_card = ask_res.get("structured_card")
        folder_manifest = ask_res.get("folder_manifest")
        grounding_score = _grounding_or_none(ask_res.get("grounding_confidence_score"))
        crag_grade = str(ask_res.get("crag_grade") or "high")

        if target_folder and not folder_manifest:
            folder_manifest = rag.get_folder_manifest(target_folder, principal)

    neural_scores = not similarity_profile(rag.get_config().get("embedding_model"))["strict_terms"]
    if strict_relevance and neural_scores and not target_folder:
        # Neural vectors match across languages and wording, so shared words prove nothing;
        # the engine's similarity does (relevant files score ~0.65-0.8 on the eval set).
        raw_citations = [c for c in raw_citations if float(c.get("score") or 0.0) >= _core().STRICT_NEURAL_SCORE]
    elif strict_relevance:
        q_norm = re.sub(r"(\w)['’]s\b", r"\1s", str(query or "").lower())
        q_tokens = [t for t in re.findall(r"\w+", q_norm) if t not in _core()._CHAT_STOPWORDS and len(t) >= 3]
        if q_tokens and not target_folder:
            primary_tok = max(q_tokens, key=len)
            filtered_citations = []
            for c in raw_citations:
                hay = f"{c.get('name', '')} {c.get('breadcrumb', '')} {c.get('excerpt', '')}".lower()
                matched = sum(1 for t in q_tokens if re.search(rf"\b{re.escape(t)}", hay))
                has_primary = bool(re.search(rf"\b{re.escape(primary_tok)}", hay))
                min_req = len(q_tokens) if len(q_tokens) <= 2 else max(2, int(len(q_tokens) * 0.65))
                if matched >= min_req and has_primary and float(c.get("score") or 0.0) >= 0.25:
                    filtered_citations.append(c)
            raw_citations = filtered_citations

        visual_words = {
            "photo",
            "photos",
            "picture",
            "pictures",
            "image",
            "images",
            "pool",
            "beach",
            "car",
            "sunset",
            "snow",
            "dog",
            "cat",
            "red",
            "blue",
            "green",
            "yellow",
            "black",
            "white",
            "silver",
        }
        if not any(w in q_norm.split() for w in visual_words):
            raw_photos = []

    if strict_relevance and not raw_citations and not raw_photos and not target_folder:
        answer_summary = ""

    return {
        "tool": "search_nas_knowledge",
        "status": "ok",
        "query": query,
        "folder_path": target_folder,
        "mode": effective_mode,
        "answer_summary": answer_summary,
        "citations_count": len(raw_citations),
        "citations": raw_citations[:6],
        "photos_count": len(raw_photos),
        "photos": [
            {
                "file_id": p.get("file_id"),
                "name": p.get("name"),
                "path": p.get("path"),
                "thumbnail_url": p.get("thumbnail_url"),
                "scene_tags": p.get("scene_tags", []),
                "colors": p.get("object_colors") or p.get("dominant_colors") or [],
                # what the picture shows, when and where it was taken (AI-24)
                "caption": p.get("caption"),
                "taken": p.get("taken"),
                "place": p.get("place"),
            }
            for p in raw_photos[:6]
        ],
        "folder_manifest": folder_manifest,
        "grounding_confidence_score": grounding_score,
        "crag_grade": crag_grade,
        "context_text": context_text,
        "structured_card": structured_card if raw_citations else None,
    }


def tool_trigger_ai_sync(action: str = "start", principal: Any = None) -> dict[str, Any]:
    """Starts, pauses, or resumes standby-safe AI indexing across watched NAS folders."""
    if not _core()._has_write_permission(
        principal,
        ("shares:user_write", "storage:write", "storage:admin", "system:config"),
    ):
        return {
            "tool": "trigger_ai_sync",
            "status": "denied",
            "error": "Permission denied: storage:write or admin scope required to control AI indexing.",
        }
    rag = _core().get_rag_engine()
    act = str(action or "start").strip().lower()
    if act == "pause":
        res = rag.pause_sync()
    elif act == "resume":
        res = rag.resume_sync()
    elif act == "stop":
        res = rag.stop_sync()
    else:
        cfg = rag.get_config()
        watched = cfg.get("watched_paths") or ["/mnt/user"]
        if test_mode():
            res = {"status": "started", "watched_paths": watched, "respect_standby": True}
        else:
            res = rag.start_background_sync(paths=watched, recursive=True, respect_standby=True)
    return {
        "tool": "trigger_ai_sync",
        "status": "ok",
        "action": act,
        "result": res,
    }


def _eval_ast_math(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_ast_math(node.body)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return float(node.value)
        raise ValueError(f"Non-numeric constant: {node.value}")
    elif isinstance(node, ast.BinOp):
        left = _eval_ast_math(node.left)
        right = _eval_ast_math(node.right)
        op_type = type(node.op)
        if op_type in _core()._SAFE_OPERATORS:
            if op_type in (ast.Div, ast.FloorDiv, ast.Mod) and right == 0:
                raise ZeroDivisionError("Division by zero")
            if op_type == ast.Pow and (right > 1000 or left > 10000):
                raise ValueError("Exponent too large")
            return _core()._SAFE_OPERATORS[op_type](left, right)
        raise ValueError(f"Unsupported binary operator: {op_type}")
    elif isinstance(node, ast.UnaryOp):
        operand = _eval_ast_math(node.operand)
        op_type = type(node.op)
        if op_type in _core()._SAFE_OPERATORS:
            return _core()._SAFE_OPERATORS[op_type](operand)
        raise ValueError(f"Unsupported unary operator: {op_type}")
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _core()._SAFE_FUNCTIONS:
            fn = _core()._SAFE_FUNCTIONS[node.func.id]
            args = [_eval_ast_math(arg) for arg in node.args]
            return fn(*args)
        raise ValueError("Unsupported function call")
    elif isinstance(node, ast.Name):
        if node.id in _core()._SAFE_FUNCTIONS and isinstance(_core()._SAFE_FUNCTIONS[node.id], (int, float)):
            return float(_core()._SAFE_FUNCTIONS[node.id])
        raise ValueError(f"Unknown variable: {node.id}")
    else:
        raise ValueError(f"Unsupported syntax: {type(node).__name__}")


def tool_calculate(expression: str) -> dict[str, Any]:
    """
    Safely evaluates a mathematical expression, arithmetic operation, percentage,
    or NAS capacity/transfer calculation using AST parsing (no eval/exec).
    """
    raw_expr = str(expression or "").strip()
    if not raw_expr:
        return {"tool": "calculate", "status": "error", "error": "Empty expression"}

    clean_expr = raw_expr.strip().rstrip("?.! ")
    # Clean natural language prefixes: 'whats 67+20', 'what is 67+20', 'calculate 15 * 8'
    clean_expr = re.sub(
        r"^(?:what(?:'s|s|\s+is)?|calculate|compute|solve|how\s+much\s+is|evaluate|can\s+you\s+calculate|please\s+calculate)\s+",
        "",
        clean_expr,
        flags=re.IGNORECASE,
    ).strip()

    # 1. Percentage check: e.g. "15% of 80" or "15 % * 80"
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:of|\*)\s*(\d+(?:\.\d+)?)", clean_expr, flags=re.IGNORECASE)
    if pct_match:
        pct_val = float(pct_match.group(1))
        base_val = float(pct_match.group(2))
        res = (pct_val / 100.0) * base_val
        formatted = f"{int(res)}" if res.is_integer() else f"{res:.4g}"
        expr_str = f"{pct_val:g}% of {base_val:g}"
        return {
            "tool": "calculate",
            "status": "ok",
            "expression": expr_str,
            "result": int(res) if res.is_integer() else res,
            "formatted": formatted,
            "summary": f"{expr_str} = {formatted}",
        }

    # 2. TB to TiB conversion check: e.g. "16 TB to TiB" or "16TB in TiB"
    tb_match = re.search(r"(\d+(?:\.\d+)?)\s*tb\s*(?:to\s*tib|in\s*tib)?", clean_expr, flags=re.IGNORECASE)
    if tb_match and ("tib" in clean_expr.lower() or "usable" in clean_expr.lower()):
        tb_val = float(tb_match.group(1))
        tib_val = tb_val * (10**12 / 2**40)
        formatted = f"{tib_val:.2f} TiB"
        expr_str = f"{tb_val:g} TB to TiB"
        return {
            "tool": "calculate",
            "status": "ok",
            "expression": expr_str,
            "result": round(tib_val, 4),
            "formatted": formatted,
            "summary": f"{expr_str} = {formatted}",
        }

    # Normalize mathematical symbols: 'x' -> '*', '÷' -> '/', '^' -> '**'
    norm_expr = clean_expr.replace("x", "*").replace("X", "*").replace("÷", "/").replace("^", "**")
    norm_expr = re.sub(r"\s+", " ", norm_expr)

    try:
        parsed_ast = ast.parse(norm_expr, mode="eval")
        num_res = _eval_ast_math(parsed_ast)
        res_val = int(num_res) if (isinstance(num_res, float) and num_res.is_integer()) else round(num_res, 6)
        formatted = f"{res_val:g}" if isinstance(res_val, (int, float)) else str(res_val)
        display_expr = clean_expr
        return {
            "tool": "calculate",
            "status": "ok",
            "expression": display_expr,
            "result": res_val,
            "formatted": formatted,
            "summary": f"{display_expr} = {formatted}",
        }
    except Exception as e:
        return {
            "tool": "calculate",
            "status": "error",
            "expression": clean_expr,
            "error": str(e),
            "summary": f"Could not calculate '{clean_expr}': {e}",
        }


def tool_get_storage_status() -> dict[str, Any]:
    """Reads live NAS storage pools, filesystem types, capacity, and pool health without waking sleeping HDDs."""
    try:
        from backend.hardware.pal_storage import get_storage_platform

        plat = get_storage_platform()
        pools = plat.list_pools()
        total_b = sum(p.total_bytes or 0 for p in pools)
        used_b = sum(p.used_bytes or 0 for p in pools)
        free_b = max(0, total_b - used_b)
        total_tib = round(total_b / (1024**4), 2)
        used_tib = round(used_b / (1024**4), 2)
        free_tib = round(free_b / (1024**4), 2)
        pools_summary = [
            {
                "id": p.id,
                "name": p.name,
                "fs_type": p.fs_type,
                "health": getattr(p, "status", getattr(p, "health", "HEALTHY")),
                "status": getattr(p, "status", "HEALTHY"),
                "total_tib": round((p.total_bytes or 0) / (1024**4), 2),
                "free_tib": round(getattr(p, "free_bytes", (p.total_bytes or 0) - (p.used_bytes or 0)) / (1024**4), 2),
                "used_pct": getattr(p, "used_pct", 0.0),
            }
            for p in pools
        ]
        summary = f"{len(pools)} pool(s): {free_tib} TiB free / {total_tib} TiB total"
        return {
            "tool": "get_storage_status",
            "status": "ok",
            "pools": pools_summary,
            "pool_count": len(pools),
            "total_tib": total_tib,
            "used_tib": used_tib,
            "free_tib": free_tib,
            "zero_disk_wakeups": True,
            "summary": summary,
        }
    except Exception as e:
        return {
            "tool": "get_storage_status",
            "status": "error",
            "error": str(e),
            "zero_disk_wakeups": True,
            "summary": f"Storage status unavailable: {e}",
        }


def tool_get_network_status() -> dict[str, Any]:
    """Reads host network interfaces, active IP addresses, link negotiation speeds, gateway, and DNS servers."""
    try:
        from backend.hardware.network import get_network_topology, read_ip

        topo = get_network_topology()
        ip_addr = read_ip()
        ifaces = topo.get("interfaces", [])
        active_ifaces = [
            {
                "name": iface.get("name"),
                "ip": iface.get("ip"),
                "speed": iface.get("speed_label") or iface.get("speed"),
                "state": iface.get("state"),
                "is_up": iface.get("is_up"),
            }
            for iface in ifaces
            if iface.get("is_up")
        ]
        main_speed = active_ifaces[0].get("speed", "1 Gbps") if active_ifaces else "Unknown"
        summary = f"IP: {ip_addr or 'unknown'} ({len(active_ifaces)} active link(s), max {main_speed})"
        return {
            "tool": "get_network_status",
            "status": "ok",
            "hostname": topo.get("hostname", "NAS"),
            "ip_address": ip_addr,
            "gateway": topo.get("gateway"),
            "default_gateway": topo.get("gateway"),
            "dns_servers": topo.get("dns_servers", []),
            "interfaces": active_ifaces,
            "active_interfaces": active_ifaces,
            "interface_count": len(active_ifaces),
            "summary": summary,
        }
    except Exception as e:
        return {
            "tool": "get_network_status",
            "status": "error",
            "error": str(e),
            "summary": f"Network status unavailable: {e}",
        }
