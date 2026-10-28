"""
ZettNAS Toolkit - Smart Media, Multi-Modal Local RAG & Visual Search API Router
Exposes hardware-accelerated (NPU -> GPU -> CPU) document/recipe RAG,
12-color perceptual + scene photo search, spindown-safe incremental indexing,
cached NVMe WebP thumbnails, and FileBot-style automated media organizing.
"""

import asyncio
import ipaddress
import logging
import os
import time
import urllib.parse
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from backend.api.system import check_user_path_access
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import ALLOWED_BROWSE_ROOTS, POOL_PATH
from backend.confirmations import require_confirmation
from backend.fsutil import resolve_within
from backend.rate_limit import rate_limit
from backend.services import ai_access
from backend.services.ai_access import require_ai_access, require_ai_search
from backend.services.ai_chat_agent import (
    AVAILABLE_NAS_TOOLS,
    build_llm_execution_telemetry,
    resolve_model_runtime_accelerator,
    run_agentic_chat,
    stream_agentic_chat,
)
from backend.services.media_engine import (
    get_media_engine,
    is_embedding_only_model,
    pull_huggingface_model,
    search_huggingface_models,
)
from backend.services.media_organizer import apply_organize, preview_organize
from backend.services.rag_engine import (
    get_rag_engine,
    get_running_disks_list,
    get_sleeping_disks_list,
    is_backing_disk_in_standby,
)
from backend.state import Z_STATE

router = APIRouter(tags=["Smart Media & AI RAG Engine"])


def _validate_media_path(path: str, principal: AuthenticatedPrincipal | None, must_exist: bool = True) -> str:
    path = str(path or "").strip()
    if not path or "\x00" in path:
        raise HTTPException(status_code=400, detail="Invalid path")
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if ".." in parts:
        raise HTTPException(status_code=403, detail="Path is outside the allowed storage folders.")
    norm = os.path.normpath(os.path.abspath(path))
    if not must_exist and is_backing_disk_in_standby(norm):
        parent_dir = os.path.dirname(norm)
        if os.path.exists(parent_dir):
            real_parent = resolve_within(parent_dir, ALLOWED_BROWSE_ROOTS)
            if real_parent is None:
                raise HTTPException(status_code=403, detail="Path is outside the allowed storage folders.")
            norm = os.path.join(real_parent, os.path.basename(norm))
        else:
            in_allowed = False
            for root in ALLOWED_BROWSE_ROOTS:
                if not root:
                    continue
                r_norm = os.path.normpath(os.path.abspath(root))
                if norm == r_norm or norm.startswith(r_norm + os.sep):
                    in_allowed = True
                    break
            if not in_allowed:
                raise HTTPException(status_code=403, detail="Path is outside the allowed storage folders.")
        check_user_path_access(norm, principal)
        return norm
    real = resolve_within(path, ALLOWED_BROWSE_ROOTS)
    if real is None:
        raise HTTPException(status_code=403, detail="Path is outside the allowed storage folders.")
    if must_exist and not os.path.exists(real):
        raise HTTPException(status_code=404, detail="Path does not exist.")
    check_user_path_access(real, principal)
    return real


class MediaScanRequest(BaseModel):
    media_path: str | None = Field(default="/mnt/storage/media", max_length=512)


class RagIndexSyncRequest(BaseModel):
    path: str | None = Field(default=None, max_length=512)
    media_path: str | None = Field(default=None, max_length=512)
    paths: list[str] | None = None
    recursive: bool = True
    respect_standby: bool = True
    force_wake: bool = False
    background: bool = False
    max_files: int = Field(default=100000, ge=0, le=500000)


class RagSyncControlRequest(BaseModel):
    action: str = Field(..., pattern="^(pause|resume|stop|status|flush|clear)$")


class RagWatchedFoldersRequest(BaseModel):
    action: str = Field(default="set", pattern="^(add|remove|set)$")
    target: str = Field(default="watched", pattern="^(watched|excluded)$")
    path: str | None = Field(default=None, max_length=512)
    paths: list[str] | None = None


class MultimodalSearchRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    q: str | None = Field(default=None, max_length=500)
    mode: str = Field(default="all", max_length=32)
    modality: str | None = Field(default=None, max_length=32)
    file_type: str | None = Field(default=None, max_length=32)
    match_tab: str = Field(default="semantic", max_length=32)
    sort_by: str = Field(default="relevance", max_length=32)
    colors: list[str] | None = None
    color: str | None = Field(default=None, max_length=64)
    scenes: list[str] | None = None
    scene: str | None = Field(default=None, max_length=64)
    path_prefix: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=24, ge=1, le=100)
    tags: list[str] | None = Field(default=None, max_length=6)  # auto-tag filters (B8)
    taken: str | None = Field(default=None, max_length=7)  # photos from "2023" or "2023-06" (AI-24)
    place: str | None = Field(default=None, max_length=120)  # photos taken there (AI-24)


class RagAskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    scope: str = Field(default="all", max_length=32)
    path_prefix: str | None = Field(default=None, max_length=512)
    top_k: int = Field(default=5, ge=1, le=12)
    limit: int | None = Field(default=None, ge=1, le=20)


class RagConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    scope_mode: str | None = None
    respect_standby: bool | None = None
    auto_learn_on_spinup: bool | None = None
    compute_preference: str | None = None
    watched_paths: list[str] | None = None
    excluded_paths: list[str] | None = None
    schedule_enabled: bool | None = None
    schedule_start: str | None = None
    schedule_end: str | None = None
    active_model: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    embedding_provider: str | None = None
    llm_endpoint: str | None = None
    llm_model: str | None = None
    llm_fallback_model: str | None = Field(default=None, max_length=128)
    idle_unload_minutes: int | None = None
    conversation_retention_days: int | None = Field(default=None, ge=0, le=3650)
    vision_captions: str | None = Field(default=None, pattern="^(auto|off)$")
    caption_language: str | None = Field(default=None, pattern="^(auto|en|de|fr|es|zh)$")  # AI-13
    vision_model: str | None = Field(default=None, max_length=128)
    embedding_host: str | None = Field(default=None, max_length=512)
    rerank_endpoint: str | None = Field(default=None, max_length=512)
    rerank_model: str | None = Field(default=None, max_length=128)
    rerank_top_n: int | None = Field(default=None, ge=2, le=100)


class ModelSelectRequest(BaseModel):
    model: str | None = Field(default=None, max_length=256)
    model_id: str | None = Field(default=None, max_length=256)


class ModelRemoveRequest(BaseModel):
    model: str | None = Field(default=None, max_length=256)
    model_id: str | None = Field(default=None, max_length=256)


class HuggingFacePullRequest(BaseModel):
    repo_id: str = Field(..., min_length=1, max_length=256)
    activate: bool = True


class AiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict[str, Any]] | None = None
    allow_web_search: bool = False  # web search and weather leave the NAS (AI-06)
    allow_nas_tools: bool = True
    model: str | None = Field(default=None, max_length=256)
    conversation_id: str | None = Field(default=None, max_length=64)
    # "Ask Zetty about this" in File Explorer: answer from this file or folder (missing feature 6)
    focus_path: str | None = Field(default=None, max_length=4096)


def _checked_focus(req: "AiChatRequest", principal: AuthenticatedPrincipal) -> str | None:
    """The file or folder the question is about, when the user may read it."""
    if not req.focus_path:
        return None
    from backend.fsutil import resolve_within
    from backend.services.path_access import ALLOWED_BROWSE_ROOTS, user_can_access_path

    target = resolve_within(req.focus_path, ALLOWED_BROWSE_ROOTS)
    if target is None or not user_can_access_path(target, principal):
        raise HTTPException(status_code=403, detail="You can't ask about that file.")
    return target


class FavoriteToggleRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)


class MediaOrganizePreviewRequest(BaseModel):
    source_dir: str = Field(..., min_length=1)
    target_dir: str | None = None
    media_type: str = "auto"  # "auto", "tv", "movie"


class MediaOrganizeApplyRequest(BaseModel):
    items: list[dict[str, Any]] = Field(..., min_length=1)
    action: str = Field("move", pattern="^(move|copy)$")
    hardlink: bool = False


class FolderAuditRequest(BaseModel):
    folder_path: str = Field(..., min_length=1, max_length=1024)
    query: str | None = Field(default=None, max_length=1000)
    mode: str = Field("comprehensive", pattern="^(comprehensive|targeted)$")
    max_tokens: int = Field(default=4000, ge=500, le=16000)


@router.get("/media/status", dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))])
@router.get("/ai/status", dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))])
def get_media_status() -> dict[str, Any]:
    engine = get_media_engine()
    status = engine.get_status()
    status["config"] = get_rag_engine().get_config()
    status["reindex_status"] = get_ai_reindex_status()
    return status


@router.post("/media/scan", dependencies=[Depends(require_scope("system:config"))])
def trigger_media_scan(
    req: MediaScanRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    engine = get_media_engine()
    raw_target = req.media_path or "/mnt/storage/media"
    if raw_target == "/mnt/storage/media" and not os.path.exists(raw_target) and os.path.exists(POOL_PATH):
        raw_target = POOL_PATH
    validated_path = _validate_media_path(raw_target, principal, must_exist=True)
    try:
        return engine.trigger_scan(media_path=validated_path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/media/index",
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin", "system:config"))],
)
@router.post(
    "/ai/index",
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin", "system:config"))],
)
@router.post(
    "/ai/index/sync",
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin", "system:config"))],
)
async def sync_rag_index(
    req: RagIndexSyncRequest,
    http_request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """
    Runs incremental, spindown-safe multi-modal indexing on the requested directory or watched folders.
    Respects `smartctl -n standby` / `Z_STATE.cached_smart_data` / Unraid `disks.ini` by default so sleeping HDDs are never woken.
    Supports synchronous or background execution with Pause/Resume/Stop controls.
    """
    if req.force_wake and not principal.has_any_scope("storage:admin", "system:config", "*"):
        raise HTTPException(status_code=403, detail="Forcing wake on sleeping disks requires storage:admin scope.")
    if req.force_wake:  # it wakes sleeping drives on purpose: the person confirms that first
        from backend.confirmations import confirm_or_raise

        confirm_or_raise(http_request, principal, "disk.wake", "indexing")

    rag = get_rag_engine()
    raw_targets: list[str] = []
    if req.paths and len(req.paths) > 0:
        raw_targets = [str(p).strip() for p in req.paths if str(p).strip()]
    elif req.path or req.media_path:
        raw_targets = [str(req.path or req.media_path).strip()]
    else:
        cfg_watched = rag.get_config().get("watched_paths") or []
        raw_targets = [str(p).strip() for p in cfg_watched if str(p).strip()]
        if not raw_targets:
            raw_targets = [POOL_PATH or "/mnt/user"]

    validated_paths: list[str] = []
    for raw_t in raw_targets:
        t = raw_t
        if t == "/mnt/storage/media" and not os.path.exists(t) and os.path.exists(POOL_PATH):
            t = POOL_PATH
        vp = _validate_media_path(t, principal, must_exist=False)
        if vp not in validated_paths:
            validated_paths.append(vp)

    if req.background:
        res = rag.start_background_sync(
            paths=validated_paths,
            recursive=req.recursive,
            respect_standby=req.respect_standby,
            force_wake=req.force_wake,
            max_files=req.max_files,
        )
        res["acceleration"] = get_media_engine().get_status()["acceleration"]
        res["stats"] = rag.get_index_stats()
        return res

    if len(validated_paths) == 1:
        res = await asyncio.to_thread(
            rag.index_directory,
            validated_paths[0],
            req.respect_standby,
            req.force_wake,
            req.max_files,
            req.recursive,
        )
    else:
        res = await asyncio.to_thread(
            rag.index_paths,
            validated_paths,
            req.respect_standby,
            req.force_wake,
            req.max_files,
            req.recursive,
        )
    res["indexed"] = res.get("indexed_files", 0)
    res["acceleration"] = get_media_engine().get_status()["acceleration"]
    res["stats"] = rag.get_index_stats()
    res["sync_progress"] = rag.get_sync_progress()
    return res


@router.post(
    "/media/index/control",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.post(
    "/ai/index/control",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
def control_rag_index(req: RagSyncControlRequest) -> dict[str, Any]:
    """Pause, resume, stop, query, or flush the active RAG & Visual Search indexing sync job."""
    rag = get_rag_engine()
    act = req.action.strip().lower()
    if act == "pause":
        res = rag.pause_sync()
    elif act == "resume":
        res = rag.resume_sync()
    elif act == "stop":
        res = rag.stop_sync()
    elif act in ("flush", "clear"):
        res = rag.flush_index()
    else:
        res = {"status": "ok", "sync_state": rag.get_sync_progress().get("state", "idle")}
    res["sync_progress"] = rag.get_sync_progress()
    res["stats"] = rag.get_index_stats()
    return res


@router.post(
    "/media/index/flush",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.post(
    "/ai/index/flush",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
async def flush_rag_index(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Flushes all indexed files, vector embeddings, chunks, and manifests from rag_index.db to start fresh."""
    rag = get_rag_engine()
    res = await asyncio.to_thread(rag.flush_index)
    res["acceleration"] = get_media_engine().get_status()["acceleration"]
    return res


class ForgetFolderRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)


@router.post(
    "/ai/index/forget",
    dependencies=[
        Depends(require_scope("system:config", "ai:manage")),
        Depends(require_confirmation("ai.index.forget")),
    ],
)
async def forget_rag_folder(
    req: ForgetFolderRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Deletes what the index learned from a folder and stops learning it (AI-20)."""
    path = _validate_media_path(req.path, principal, must_exist=False)
    try:
        return await asyncio.to_thread(get_rag_engine().forget_folder, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/media/folders",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.get(
    "/ai/folders",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
def get_watched_folders() -> dict[str, Any]:
    """Returns configured watched/excluded RAG folders and discovered NAS shares with live disk standby state."""
    rag = get_rag_engine()
    cfg = rag.get_config()
    return {
        "status": "ok",
        "scope_mode": cfg.get("scope_mode", "include"),
        "watched_paths": cfg.get("watched_paths", []),
        "excluded_paths": cfg.get("excluded_paths", []),
        "available_folders": rag.discover_available_folders(),
        "sleeping_disks": get_sleeping_disks_list(),
        "running_disks": get_running_disks_list(),
    }


@router.post(
    "/media/folders",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.post(
    "/ai/folders",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
def update_watched_folders(
    req: RagWatchedFoldersRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Adds, removes, or sets watched or excluded folders/shares for ZettAI RAG."""
    rag = get_rag_engine()
    cfg = rag.get_config()
    list_key = "excluded_paths" if req.target == "excluded" else "watched_paths"
    current: list[str] = [os.path.normpath(str(p)) for p in (cfg.get(list_key) or []) if str(p).strip()]
    act = req.action.strip().lower()
    added_vp: str | None = None

    if act == "add":
        if not req.path or not str(req.path).strip():
            raise HTTPException(status_code=400, detail="Folder path is required for 'add'.")
        vp = _validate_media_path(req.path, principal, must_exist=False)
        if vp not in current:
            current.append(vp)
        added_vp = vp
    elif act == "remove":
        if not req.path or not str(req.path).strip():
            raise HTTPException(status_code=400, detail="Folder path is required for 'remove'.")
        target_norm = os.path.normpath(str(req.path).strip())
        current = [p for p in current if p != target_norm]
        rag.remove_deferred_path(target_norm)
        if not current and list_key == "watched_paths":
            current = [POOL_PATH or "/mnt/user"]
    elif act == "set":
        raw_list = req.paths if req.paths is not None else ([req.path] if req.path else [])
        validated_list: list[str] = []
        for p in raw_list:
            if not str(p).strip():
                continue
            vp = _validate_media_path(str(p).strip(), principal, must_exist=False)
            if vp not in validated_list:
                validated_list.append(vp)
        if not validated_list and list_key == "watched_paths":
            raise HTTPException(status_code=400, detail="At least one valid folder path is required.")
        current = validated_list

    updated_cfg = rag.update_config({list_key: current})

    if added_vp and list_key == "watched_paths":
        if is_backing_disk_in_standby(added_vp):
            rag.enqueue_deferred_path(added_vp, reason="disk_standby", priority=1)
        elif (
            os.environ.get("TESTING") != "1"
            and os.environ.get("ZETTNAS_TEST_MODE") != "1"
            and updated_cfg.get("enabled", True)
            and updated_cfg.get("auto_learn_on_spinup", True)
        ):
            rag.start_background_sync(
                paths=[added_vp],
                respect_standby=bool(updated_cfg.get("respect_standby", True)),
                force_wake=False,
            )

    return {
        "status": "ok",
        "scope_mode": updated_cfg.get("scope_mode", "include"),
        "watched_paths": updated_cfg.get("watched_paths", []),
        "excluded_paths": updated_cfg.get("excluded_paths", []),
        "available_folders": rag.discover_available_folders(),
        "deferred_queue": rag.get_deferred_queue(),
        "sync_progress": rag.get_sync_progress(),
        "config": updated_cfg,
    }


@router.get(
    "/media/duplicates",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def get_duplicates(
    limit: int = Query(default=200, ge=1, le=1000),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Files kept more than once, photos that look the same included, that this person may open (AI-35)."""
    return await asyncio.to_thread(get_rag_engine().duplicates, principal, limit)


@router.get(
    "/media/models/recommendations",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
@router.get(
    "/ai/models/recommendations",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
async def get_model_recommendations(
    sort_by: str = Query(default="date", max_length=32),
    min_year: int | None = Query(default=None),
) -> dict[str, Any]:
    """Returns hardware-aware LLM & Multi-Modal model recommendations based on onboard NPU, GPU, and RAM."""
    status = get_media_engine().get_status()
    accel = status["acceleration"]
    ram_gb = status["total_ram_gb"]
    rag_cfg = get_rag_engine().get_config()
    from backend.services.media_engine import build_llm_recommendations

    recs = build_llm_recommendations(
        accel=accel,
        ram_gb=ram_gb,
        active_model=rag_cfg.get("active_model") or "qwen2.5:3b",
        custom_models=rag_cfg.get("custom_hf_models", []),
        sort_by=sort_by,
        min_release_year=min_year,
    )
    # Say which catalog models are actually installed in the runtime (AI-03)
    try:
        from backend.services.model_installer import installed_models, is_installed

        inst = await asyncio.to_thread(installed_models)
        if inst.get("reachable"):
            for m in recs.get("models", []):
                tag = str(m.get("ollama_tag") or m.get("id") or "")
                m["installed"] = tag == "builtin-npu" or is_installed(tag, inst["models"])
        recs["runtime_reachable"] = bool(inst.get("reachable"))
    except Exception:
        logger.debug("backend.api.media.get_model_recommendations: ignored error", exc_info=True)
    return {
        "status": "ok",
        "acceleration": status["acceleration"],
        "llm_recommendations": recs,
    }


@router.post(
    "/media/models/select",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.post(
    "/ai/models/select",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
def select_recommended_model(req: ModelSelectRequest) -> dict[str, Any]:
    """Selects and applies an LLM / multi-modal model for ZettAI, returning any hardware fit warnings."""
    rag = get_rag_engine()
    model_tag = str(req.model or req.model_id or "").strip()
    if not model_tag:
        raise HTTPException(status_code=400, detail="Model identifier is required.")

    status = get_media_engine().get_status()
    recs = status["llm_recommendations"]
    selected_entry = next(
        (
            m
            for m in recs.get("models", [])
            if str(m.get("id", "")).lower() == model_tag.lower()
            or str(m.get("model_key", "")).lower() == model_tag.lower()
            or str(m.get("hf_repo", "")).lower() == model_tag.lower()
        ),
        None,
    )

    if is_embedding_only_model(model_tag) or (selected_entry and is_embedding_only_model(selected_entry)):
        updated_cfg = rag.update_config({"embedding_model": model_tag})
        current_active = updated_cfg.get("active_model") or "qwen2.5:3b"
        return {
            "status": "ok",
            "active_model": current_active,
            "embedding_model": model_tag,
            "is_embedding": True,
            "fits_hardware": True,
            "hardware_warning": False,
            "warning_message": (
                f"'{model_tag}' is a dedicated vector embedding model. It has been activated as the embedding engine "
                f"for semantic search and RAG. Conversational chat remains '{current_active}'."
            ),
            "config": updated_cfg,
            "llm_recommendations": recs,
        }

    updated_cfg = rag.update_config({"active_model": model_tag, "llm_model": model_tag})
    return {
        "status": "ok",
        "active_model": updated_cfg.get("active_model"),
        "fits_hardware": bool(selected_entry.get("fits_hardware", True)) if selected_entry else True,
        "hardware_warning": bool(selected_entry.get("hardware_warning", False)) if selected_entry else False,
        "warning_message": selected_entry.get("warning_message") if selected_entry else None,
        "config": updated_cfg,
        "llm_recommendations": recs,
    }


@router.get(
    "/media/models/huggingface/search",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
@router.get(
    "/ai/models/huggingface/search",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
def search_hf_release_models(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=12, ge=1, le=30),
    sort_by: str = Query(default="date", max_length=32),
    min_year: int | None = Query(default=None),
) -> dict[str, Any]:
    """Searches https://huggingface.co release models and evaluates hardware fit against NAS NPU/GPU/RAM."""
    return search_huggingface_models(query=q, limit=limit, sort_by=sort_by, min_release_year=min_year)


@router.post(
    "/media/models/huggingface/pull",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.post(
    "/ai/models/huggingface/pull",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
def pull_hf_release_model(req: HuggingFacePullRequest) -> dict[str, Any]:
    """Pulls/registers a release model from https://huggingface.co and flags hardware fit warnings."""
    try:
        return pull_huggingface_model(repo_id=req.repo_id, activate=req.activate)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class ModelInstallRequest(BaseModel):
    model: str = Field(..., min_length=1, max_length=200)


@router.get("/ai/models/installed", dependencies=[Depends(require_scope("system:read", "ai:manage", "system:config"))])
async def list_installed_models() -> dict[str, Any]:
    """Models the Ollama runtime has installed, and copies of one model under another name (AI-16)."""
    from backend.services.model_installer import installed_models

    return await asyncio.to_thread(installed_models)


class BenchmarkApplyRequest(BaseModel):
    tier: str = Field(..., pattern="^(fast|balanced)$")


@router.get("/ai/models/benchmark", dependencies=[Depends(require_scope("system:read", "ai:manage", "system:config"))])
def get_model_benchmark() -> dict[str, Any]:
    """Last benchmark results, the recommended tiers and a running job (D2)."""
    from backend.services import model_benchmark

    return model_benchmark.status()


@router.post("/ai/models/benchmark", dependencies=[Depends(require_scope("system:config", "ai:manage"))])
def start_model_benchmark() -> dict[str, Any]:
    from backend.services import model_benchmark

    return model_benchmark.start()


@router.post("/ai/models/benchmark/apply", dependencies=[Depends(require_scope("system:config", "ai:manage"))])
def apply_model_tier(req: BenchmarkApplyRequest) -> dict[str, Any]:
    """Makes the recommended model of a tier Ask Zetty's chat model."""
    from backend.services import model_benchmark

    name = (model_benchmark.load_results().get("recommended") or {}).get(req.tier)
    if not name:
        raise HTTPException(status_code=409, detail="Run a benchmark first.")
    get_rag_engine().update_config({"active_model": name})
    return {"active_model": name, "tier": req.tier}


@router.post("/ai/models/install", dependencies=[Depends(require_scope("system:config", "ai:manage"))])
async def install_model(
    req: ModelInstallRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Downloads a model into Ollama in the background; poll the job for progress (AI-03)."""
    from backend.services.model_installer import start_install

    try:
        return start_install(req.model, requested_by=principal.username or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/ai/models/install/{job_id}", dependencies=[Depends(require_scope("system:config", "ai:manage"))])
def get_install_job(job_id: str) -> dict[str, Any]:
    from backend.services.model_installer import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="No such install job.")
    return job


@router.post("/ai/models/install/{job_id}/cancel", dependencies=[Depends(require_scope("system:config", "ai:manage"))])
def cancel_install_job(job_id: str) -> dict[str, Any]:
    from backend.services.model_installer import cancel_job

    return {"cancelled": cancel_job(job_id)}


@router.post(
    "/media/models/remove",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.post(
    "/ai/models/remove",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
def remove_model_post_endpoint(req: ModelRemoveRequest) -> dict[str, Any]:
    """Removes a model from the ZettAI catalog and local storage."""
    from backend.services.media_engine import remove_llm_model

    model_tag = str(req.model or req.model_id or "").strip()
    if not model_tag:
        raise HTTPException(status_code=400, detail="Model identifier is required.")
    try:
        return remove_llm_model(model_tag)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/media/models/remove",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.delete(
    "/ai/models/remove",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
def remove_model_delete_explicit_endpoint(
    model: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
    req: ModelRemoveRequest | None = None,
) -> dict[str, Any]:
    """Removes a model from the ZettAI catalog and local storage via DELETE /remove."""
    from backend.services.media_engine import remove_llm_model

    model_tag = str((req.model if req else None) or (req.model_id if req else None) or model or model_id or "").strip()
    if not model_tag:
        raise HTTPException(status_code=400, detail="Model identifier is required.")
    try:
        return remove_llm_model(model_tag)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/media/models/{model_id:path}",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.delete(
    "/ai/models/{model_id:path}",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
def delete_model_endpoint(model_id: str) -> dict[str, Any]:
    """Removes a model from the ZettAI catalog and local storage."""
    from backend.services.media_engine import remove_llm_model

    clean_id = str(model_id or "").strip()
    if not clean_id:
        raise HTTPException(status_code=400, detail="Model identifier is required.")
    try:
        return remove_llm_model(clean_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/media/learning/results",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
@router.get(
    "/ai/learning/results",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
def get_zettai_learning_results(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Returns ZettAI 6-state learning status, succeeded/failed counts, and failed file list."""
    return {"status": "ok", **get_rag_engine().get_learning_results(principal=principal)}


@router.post(
    "/media/learning/relearn-failed",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
@router.post(
    "/ai/learning/relearn-failed",
    dependencies=[Depends(require_scope("system:config", "ai:manage"))],
)
async def relearn_failed_items() -> dict[str, Any]:
    """Retries indexing failed files without waking sleeping drives."""
    rag = get_rag_engine()
    res = await asyncio.to_thread(rag.relearn_failed_files)
    return {"status": "ok", **res}


@router.post(
    "/media/favorites",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.post(
    "/ai/favorites",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
def toggle_favorite_item(
    req: FavoriteToggleRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Adds or removes a file path from ZettAI favorites."""
    vp = _validate_media_path(req.path, principal, must_exist=False)
    return get_rag_engine().toggle_favorite(vp)


async def _with_immich(res: Any, q: str | None, mode: str | None, principal: Any, limit: int) -> Any:
    """Adds this person's Immich photos to a photo search when they connected Immich (Batch 6)."""
    if (
        not isinstance(res, dict)
        or not (q or "").strip()
        or (mode or "all") not in ("all", "photos", "photo", "images")
    ):
        return res
    from backend.services.immich_photos import smart_search

    try:
        res["immich_results"] = await asyncio.to_thread(
            smart_search, principal.username if principal else "", q or "", min(limit, 24)
        )
    except Exception:
        logger.debug("immich search skipped", exc_info=True)
    return res


@router.get(
    "/media/search",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_search),
    ],
)
@router.get(
    "/ai/search",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_search),
    ],
)
async def search_multimodal_get(
    q: str = Query(default="", max_length=500),
    query: str | None = Query(default=None, max_length=500),
    mode: str = Query(default="all", max_length=32),
    modality: str | None = Query(default=None, max_length=32),
    match_tab: str = Query(default="semantic", max_length=32),
    sort_by: str = Query(default="relevance", max_length=32),
    colors: str | None = Query(default=None, max_length=256),
    color: str | None = Query(default=None, max_length=64),
    scenes: str | None = Query(default=None, max_length=256),
    scene: str | None = Query(default=None, max_length=64),
    path_prefix: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=24, ge=1, le=100),
    tags: str | None = Query(default=None, max_length=128),
    taken: str | None = Query(default=None, max_length=7),
    place: str | None = Query(default=None, max_length=120),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Zero-Disk-Touch Cross-Modal Visual & Document Search (GET)."""
    effective_q = query if query is not None else q
    effective_mode = modality if modality else mode
    raw_colors = colors or color
    raw_scenes = scenes or scene
    color_list = [c.strip() for c in raw_colors.split(",") if c.strip()] if raw_colors else None
    scene_list = [s.strip() for s in raw_scenes.split(",") if s.strip()] if raw_scenes else None

    validated_prefix = None
    if path_prefix and path_prefix.strip():
        validated_prefix = _validate_media_path(path_prefix, principal, must_exist=False)

    rag = get_rag_engine()
    res = await asyncio.to_thread(
        rag.search,
        effective_q,
        effective_mode,
        color_list,
        scene_list,
        validated_prefix,
        limit,
        principal,
        match_tab,
        sort_by,
        tags=[t for t in (tags or "").split(",") if t.strip()] or None,
        taken=taken,
        place=place,
    )
    ai_access.log_request(principal, "search", "", False, "answered")
    return await _with_immich(res, effective_q, effective_mode, principal, limit)


@router.post(
    "/media/search",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_search),
    ],
)
@router.post(
    "/ai/search",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_search),
    ],
)
async def search_multimodal_post(
    req: MultimodalSearchRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Zero-Disk-Touch Cross-Modal Visual & Document Search (POST)."""
    effective_q = req.q if req.q is not None else req.query
    if req.file_type and req.file_type.strip():
        effective_mode = req.file_type.strip().lower()
    else:
        effective_mode = req.modality if req.modality else req.mode
    color_list = list(req.colors) if req.colors else ([req.color] if req.color else None)

    scene_list = list(req.scenes) if req.scenes else ([req.scene] if req.scene else None)

    validated_prefix = None
    if req.path_prefix and req.path_prefix.strip():
        validated_prefix = _validate_media_path(req.path_prefix, principal, must_exist=False)

    rag = get_rag_engine()
    res = await asyncio.to_thread(
        rag.search,
        effective_q,
        effective_mode,
        color_list,
        scene_list,
        validated_prefix,
        req.limit,
        principal,
        req.match_tab,
        req.sort_by,
        tags=req.tags,
        taken=req.taken,
        place=req.place,
    )
    ai_access.log_request(principal, "search", "", False, "answered")
    return await _with_immich(res, effective_q, effective_mode, principal, req.limit)


@router.get("/ai/tags", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))])
def get_search_tags(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """The document filters: each auto-tag with how many files this person may see carry it (B8)."""
    from backend.services import rag_tags

    counts = get_rag_engine().tag_counts(principal)
    kinds = [{"tag": t, "count": counts[t]} for t in rag_tags.TAGS if counts.get(t)]
    years = sorted(
        ({"tag": t, "count": n} for t, n in counts.items() if t.startswith("year:")),
        key=lambda x: x["tag"],
        reverse=True,
    )
    return {"kinds": kinds, "years": years}


@router.get("/ai/photo-facets", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))])
def get_photo_facets(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """The photo filters: the years and places of the photos this person may see (AI-24)."""
    return get_rag_engine().photo_facets(principal)


@router.post(
    "/media/ask",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_access),
    ],
)
@router.post(
    "/ai/ask",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_access),
    ],
)
async def ask_knowledge_base(
    req: RagAskRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Grounded Conversational RAG & Structured Recipe/Document Synthesis."""
    validated_prefix = None
    if req.path_prefix and req.path_prefix.strip():
        validated_prefix = _validate_media_path(req.path_prefix, principal, must_exist=False)

    effective_top_k = min(12, max(1, int(req.limit if req.limit is not None else req.top_k)))
    rag = get_rag_engine()
    cfg = rag.get_config()
    active_model = str(cfg.get("active_model") or cfg.get("llm_model") or "qwen2.5:3b")

    status = get_media_engine().get_status()
    accel = status["acceleration"]
    runtime_accel = resolve_model_runtime_accelerator(active_model, host_accel=accel)
    target_accel = (
        "npu" if runtime_accel.get("active_tier") == 1 else ("gpu" if runtime_accel.get("active_tier") == 2 else "cpu")
    )

    with Z_STATE.lock:
        Z_STATE.ai_active = True
        Z_STATE.ai_accelerator = target_accel
        Z_STATE.ai_model = active_model

    started = time.monotonic()
    try:
        res = await asyncio.to_thread(
            rag.ask,
            req.query,
            req.scope,
            validated_prefix,
            effective_top_k,
            principal,
        )
    except Exception:
        ai_access.log_request(principal, "ask", active_model, False, "failed")
        raise
    else:
        ai_access.log_request(
            principal, "ask", active_model, False, "answered", int((time.monotonic() - started) * 1000)
        )
    finally:
        with Z_STATE.lock:
            Z_STATE.ai_active = False
            Z_STATE.ai_accelerator = ""
            Z_STATE.ai_model = ""

    res["hardware"] = runtime_accel
    res["active_model"] = active_model
    res["llm_telemetry"] = build_llm_execution_telemetry(
        active_model=active_model,
        accel=runtime_accel,
        elapsed_ms=float(res.get("elapsed_ms") or 12.0),
        answer_text=str(res.get("answer") or ""),
        tools_called=["search_nas_knowledge"],
    )
    return res


@router.get(
    "/media/folder/manifest",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.get(
    "/ai/folder/manifest",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def get_folder_manifest_endpoint(
    folder_path: str = Query(..., min_length=1),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Retrieves the recursive structure outline and topic inventory for a folder from NVMe SQLite WAL."""
    validated_path = _validate_media_path(folder_path, principal, must_exist=False)
    rag = get_rag_engine()
    manifest = await asyncio.to_thread(rag.get_folder_manifest, validated_path, principal)
    if not manifest:
        return {"status": "not_indexed", "folder_path": validated_path, "manifest": None}
    return {"status": "ok", "folder_path": validated_path, "manifest": manifest}


@router.get(
    "/media/manifests",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.get(
    "/ai/manifests",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def list_folder_manifests_endpoint(
    limit: int = Query(50, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Lists all indexed folder manifests and tree summaries across watched storage shares."""
    rag = get_rag_engine()
    manifests = await asyncio.to_thread(rag.list_folder_manifests, limit=limit)
    from backend.api.fs import user_can_access_path

    accessible = [m for m in manifests if user_can_access_path(m.get("folder_path", ""), principal)]
    return {"status": "ok", "count": len(accessible), "manifests": accessible}


@router.post(
    "/media/folder/audit",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_search),
    ],
)
@router.post(
    "/ai/folder/audit",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_search),
    ],
)
async def audit_folder_endpoint(
    req: FolderAuditRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """
    Executes hierarchical folder context aggregation (Mode A: targeted fact retrieval;
    Mode B: comprehensive folder audit with MMR diversification) with 0 disk wakeups.
    """
    validated_path = _validate_media_path(req.folder_path, principal, must_exist=False)
    rag = get_rag_engine()
    ai_access.log_request(principal, "search", "", False, "answered")
    res = await asyncio.to_thread(
        rag.aggregate_folder_context,
        folder_path=validated_path,
        query=req.query or "",
        mode=req.mode,
        max_tokens=int(req.max_tokens or 4000),
        principal=principal,
    )
    return res


@router.get(
    "/media/chat/tools",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
@router.get(
    "/ai/chat/tools",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
def get_ai_chat_tools() -> dict[str, Any]:
    """Returns the list of NAS hardware & web browsing tools available to the ZettAI Chatbot."""
    rag_cfg = get_rag_engine().get_config()
    return {
        "status": "ok",
        "active_model": rag_cfg.get("active_model") or "qwen2.5:3b",
        "tools": AVAILABLE_NAS_TOOLS,
    }


@router.post(
    "/media/chat",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_access),
        Depends(rate_limit("ai.chat", 20, 60)),
    ],
)
@router.post(
    "/ai/chat",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_access),
        Depends(rate_limit("ai.chat", 20, 60)),
    ],
)
async def chat_with_zettai_agent(
    req: AiChatRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """
    Conversational ZettAI Local Chatbot & NAS Hardware Copilot with live internet browsing
    and hardware/Docker/storage tool execution.
    """
    history = req.history
    uid = (principal.user_id or principal.username or "admin").strip().lower()
    focus = _checked_focus(req, principal)

    if req.conversation_id:
        try:
            from backend.services.ai_conversations_db import append_message, get_token_budgeted_history

            # The stored conversation is the only history trusted for a saved chat (AI-19).
            history = get_token_budgeted_history(req.conversation_id, uid, model_name=req.model)
            append_message(req.conversation_id, uid, "user", req.message)
        except Exception as _db_ex:
            history = []
            logger.warning(f"[AI Chat] Failed persisting user prompt: {_db_ex}")

    started = time.monotonic()
    try:
        res = await asyncio.to_thread(
            run_agentic_chat,
            req.message,
            history,
            req.allow_web_search,
            req.allow_nas_tools,
            req.model,
            principal,
            focus,
        )

        if req.conversation_id:
            res["conversation_id"] = req.conversation_id
            try:
                from backend.services.ai_conversations_db import append_message, update_auto_title_if_not_customized

                append_message(
                    conv_id=req.conversation_id,
                    user_id=uid,
                    role="assistant",
                    content=res.get("reply", ""),
                    telemetry=res.get("llm_telemetry"),
                    tools_called=res.get("tools_called"),
                    web_sources=res.get("web_sources"),
                    citations=res.get("citations"),
                    photos=res.get("photos"),
                )
                new_title = update_auto_title_if_not_customized(req.conversation_id, uid, req.message)
                if new_title:
                    res["conversation_title"] = new_title
            except Exception as _db_ex2:
                logger.warning(f"[AI Chat] Failed persisting assistant reply: {_db_ex2}")

        ai_access.log_request(
            principal,
            "chat",
            str(res.get("active_model") or req.model or ""),
            bool(req.allow_web_search),
            "answered",
            int((time.monotonic() - started) * 1000),
        )
        return res
    except ValueError as e:
        ai_access.log_request(principal, "chat", req.model or "", bool(req.allow_web_search), "failed")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/media/chat/stream",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_access),
        Depends(rate_limit("ai.chat", 20, 60)),
    ],
)
@router.post(
    "/ai/chat/stream",
    dependencies=[
        Depends(require_scope("shares:read", "storage:read", "system:read")),
        Depends(require_ai_access),
        Depends(rate_limit("ai.chat", 20, 60)),
    ],
)
async def chat_with_zettai_agent_stream(
    req: AiChatRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Response:
    """Streams real-time Server-Sent Events (SSE) tokens, tool activity traces, and thought chains from ZettAI."""
    from fastapi.responses import StreamingResponse

    history = req.history
    uid = (principal.user_id or principal.username or "admin").strip().lower()
    focus = _checked_focus(req, principal)

    if req.conversation_id:
        try:
            from backend.services.ai_conversations_db import append_message, get_token_budgeted_history

            # The stored conversation is the only history trusted for a saved chat (AI-19).
            history = get_token_budgeted_history(req.conversation_id, uid, model_name=req.model)
            append_message(req.conversation_id, uid, "user", req.message)
        except Exception as _stream_db_ex:
            history = []
            logger.warning(f"[AI Chat Stream] Failed user message prep: {_stream_db_ex}")

    ai_access.log_request(principal, "chat", req.model or "", bool(req.allow_web_search), "streamed")
    generator = stream_agentic_chat(
        message=req.message,
        history=history,
        allow_web_search=req.allow_web_search,
        allow_nas_tools=req.allow_nas_tools,
        model_override=req.model,
        principal=principal,
        conversation_id=req.conversation_id,
        focus_path=focus,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/ai/actions/{action_id}")
async def get_pending_ai_action(action_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.ai_actions import pending_summary

    res = pending_summary(action_id, principal)
    if not res:
        raise HTTPException(status_code=404, detail="This action has expired or isn't yours.")
    return res


@router.post(
    "/ai/actions/{action_id}/confirm",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def confirm_ai_action(
    action_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    """Runs an action ZettAI proposed, after the user clicked Confirm (AI-01)."""
    from backend.services.ai_actions import confirm_action

    res = await asyncio.to_thread(confirm_action, action_id, principal)
    if res.get("status") == "not_found":
        raise HTTPException(status_code=410, detail=res.get("error"))
    return res


@router.get(
    "/media/thumbnail/{file_id}",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.get(
    "/ai/thumbnail/{file_id}",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
def get_cached_thumbnail(
    file_id: int,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Response:
    """Streams the NVMe-cached WebP micro-thumbnail from rag_index.db with zero array disk I/O."""
    rag = get_rag_engine()
    try:
        blob, media_type = rag.get_thumbnail(file_id, principal=principal)
        return Response(
            content=blob,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=86400"},
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Thumbnail not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied to this file") from None


@router.get(
    "/media/config",
    dependencies=[Depends(require_scope("system:read", "storage:read"))],
)
@router.get(
    "/ai/config",
    dependencies=[Depends(require_scope("system:read", "storage:read"))],
)
def get_rag_config() -> dict[str, Any]:
    return get_rag_engine().get_config()


class AiAccessUpdate(BaseModel):
    roles: dict[str, bool] = Field(default_factory=dict)  # Ask Zetty
    search_roles: dict[str, bool] = Field(default_factory=dict)  # AI search (B11, AI-26)


@router.get("/ai/access", dependencies=[Depends(require_scope("system:config", "users:read"))])
def get_ai_access() -> dict[str, Any]:
    """Who may ask Zetty, per role (B8)."""
    return {"roles": ai_access.roles_with_access(), "log_days": ai_access.LOG_DAYS}


@router.put("/ai/access", dependencies=[Depends(require_scope("system:config"))])
def put_ai_access(req: AiAccessUpdate) -> dict[str, Any]:
    try:
        get_rag_engine().update_config(
            {
                "ai_role_access": ai_access.clean_switches(req.roles),
                "ai_search_role_access": ai_access.clean_switches(req.search_roles),
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return get_ai_access()


@router.get("/ai/access/me")
def get_my_ai_access(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    return {"allowed": ai_access.allowed(principal), "search": ai_access.allowed(principal, feature="search")}


@router.get("/ai/requests", dependencies=[Depends(require_scope("system:config", "audit:read"))])
def get_ai_requests(
    limit: int = Query(100, ge=1, le=500), user: str | None = Query(None, max_length=64)
) -> dict[str, Any]:
    """The assistant's request log: who asked when, the model, web search, the outcome; no text."""
    return {"requests": ai_access.recent(limit, user), "log_days": ai_access.LOG_DAYS}


@router.put(
    "/media/config",
    dependencies=[Depends(require_scope("system:config", "storage:admin"))],
)
@router.put(
    "/ai/config",
    dependencies=[Depends(require_scope("system:config", "storage:admin"))],
)
@router.post(
    "/ai/config",
    dependencies=[Depends(require_scope("system:config", "storage:admin"))],
)
def update_rag_config(req: RagConfigUpdateRequest) -> dict[str, Any]:
    if req.llm_endpoint is not None and req.llm_endpoint.strip():
        parsed = urllib.parse.urlparse(req.llm_endpoint.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HTTPException(status_code=400, detail="Invalid LLM endpoint URL scheme. Must be http or https.")
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if ip.is_link_local:
                raise HTTPException(
                    status_code=400, detail="Probing link-local or cloud metadata addresses is forbidden."
                )
        except ValueError:
            if parsed.hostname.lower() in ("metadata.google.internal",):
                raise HTTPException(status_code=400, detail="Cloud metadata endpoints are forbidden.") from None
    if req.rerank_endpoint:
        from backend.services.rag_rerank import endpoint_ok

        if not endpoint_ok(req.rerank_endpoint):
            raise HTTPException(status_code=400, detail="The reranker must be an http(s) URL.")
    if req.embedding_host:
        from backend.services.rag_rerank import endpoint_ok

        if not endpoint_ok(req.embedding_host):
            raise HTTPException(status_code=400, detail="The embedding host must be an http(s) URL.")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    return get_rag_engine().update_config(updates)


@router.get("/ai/vision/status", dependencies=[Depends(require_scope("system:read", "storage:read"))])
def get_vision_status() -> dict[str, Any]:
    """Photo captioning progress (AI-14)."""
    from backend.services.vision_queue import get_vision_queue

    return get_vision_queue().status()


_REINDEX_TASK: asyncio.Task | None = None
from backend.services.rag_reindex_status import REINDEX_STATUS as _REINDEX_STATUS  # noqa: E402
from backend.services.rag_reindex_status import get_reindex_status  # noqa: E402


@router.get("/ai/reindex/status", dependencies=[Depends(require_scope("system:read", "storage:read"))])
@router.get("/media/ai/reindex/status", dependencies=[Depends(require_scope("system:read", "storage:read"))])
def get_ai_reindex_status() -> dict[str, Any]:
    return get_reindex_status()


@router.post(
    "/media/ai/benchmark",
    dependencies=[Depends(require_scope("system:config", "storage:admin"))],
)
@router.post(
    "/ai/benchmark",
    dependencies=[Depends(require_scope("system:config", "storage:admin"))],
)
async def run_ai_benchmark() -> dict[str, Any]:
    """
    Executes a zero-disk synthetic embedding benchmark over 3 in-memory reference strings.
    Measures latency per chunk, throughput, tokens/sec, and detects active accelerator.
    Strictly zero-disk-touch on sleeping hard drives (AGENTS.md §1.2).
    """
    import time

    from backend.services.media_engine import detect_hardware_accelerator
    from backend.services.rag_embeddings import embedding_host
    from backend.services.rag_engine import compute_neural_embedding_via_ollama

    rag = get_rag_engine()
    cfg = rag.get_config()
    model = cfg.get("embedding_model") or "embeddinggemma"
    target_dim = cfg.get("embedding_dim") or 768

    test_strings = [
        "ZettNAS zero-spindown storage architecture with Btrfs RAID and ZFS topology.",
        "Container mutator performs atomic image recreation with automatic health check rollback.",
        "High performance hardware telemetry and acoustic fan curve management on Intel N100.",
    ]
    start_t = time.perf_counter()
    total_tokens = 0
    successful_runs = 0
    for s in test_strings:
        total_tokens += len(s.split())
        res = await asyncio.to_thread(
            compute_neural_embedding_via_ollama,
            text=s,
            model=model,
            host=embedding_host(cfg),
            target_dim=target_dim,
            is_query=False,
        )
        if res is not None:
            successful_runs += 1

    total_time = max(0.001, time.perf_counter() - start_t)
    count = max(1, successful_runs)
    latency_ms = round((total_time / count) * 1000.0, 2)
    throughput = round(count / total_time, 2)
    tok_sec = round(total_tokens / total_time, 2)

    accel_info = detect_hardware_accelerator()
    accel_name = accel_info.get("active_tier_name") or "CPU (AVX2)"
    if accel_info.get("has_npu"):
        accel_name = "NPU (Intel AI Boost / Hailo)"
    elif accel_info.get("has_gpu"):
        accel_name = "GPU (Intel Arc / iGPU)"

    return {
        "status": "ok",
        "latency_ms": latency_ms,
        "throughput_chunks_sec": throughput,
        "tokens_per_sec": tok_sec,
        "accelerator": accel_name,
        "model": model,
        "dimension": target_dim,
        "zero_disk_wakeups": True,
    }


@router.post(
    "/media/ai/reindex",
    dependencies=[Depends(require_scope("system:config", "storage:admin"))],
)
@router.post(
    "/ai/reindex",
    dependencies=[Depends(require_scope("system:config", "storage:admin"))],
)
async def trigger_ai_reindex(
    req: RagConfigUpdateRequest | None = None,
) -> dict[str, Any]:
    """Triggers background in-place re-embedding without waking sleeping hard drives."""
    global _REINDEX_TASK, _REINDEX_STATUS
    if _REINDEX_TASK and not _REINDEX_TASK.done():
        return {
            "status": "in_progress",
            "detail": "Re-indexing is already running",
            "progress": _REINDEX_STATUS,
        }

    rag = get_rag_engine()
    cfg = rag.get_config()
    target_model = (
        req.embedding_model if (req and req.embedding_model) else (cfg.get("embedding_model") or "embeddinggemma")
    )
    target_dim = req.embedding_dim if (req and req.embedding_dim) else (cfg.get("embedding_dim") or 768)
    target_host = req.embedding_host if (req and req.embedding_host is not None) else cfg.get("embedding_host")
    if target_host:
        from backend.services.rag_rerank import endpoint_ok

        if not endpoint_ok(target_host):
            raise HTTPException(status_code=400, detail="The embedding host must be an http(s) URL.")

    _REINDEX_STATUS.clear()  # shared with the status service: update in place
    _REINDEX_STATUS.update(
        {"status": "running", "completed": 0, "total": 0, "speed": 0.0, "eta_sec": 0.0, "percentage": 0.0}
    )

    def _on_progress(data: dict[str, Any]):
        global _REINDEX_STATUS
        _REINDEX_STATUS.update(data)

    async def _worker():
        global _REINDEX_STATUS
        try:
            res = await rag.in_place_reembed_collection(
                target_model=target_model,
                target_dim=target_dim,
                progress_callback=_on_progress,
                target_host=target_host or None,
            )
            _REINDEX_STATUS.update(res)
            _REINDEX_STATUS["status"] = "paused" if res.get("status") == "paused" else "complete"
        except Exception as e:
            logger.error("In-place re-index worker error: %s", e)
            _REINDEX_STATUS["status"] = "error"
            _REINDEX_STATUS["error"] = str(e)

    _REINDEX_TASK = asyncio.create_task(_worker())
    return {"status": "started", "model": target_model, "dimension": target_dim, "embedding_host": target_host or ""}


@router.post(
    "/media/organize/preview",
    dependencies=[Depends(require_scope("storage:read", "storage:admin"))],
)
async def preview_media_organization(
    req: MediaOrganizePreviewRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Analyzes source media files and calculates dry-run proposed Plex/Jellyfin renames."""
    src = _validate_media_path(req.source_dir, principal, must_exist=True)
    dst = _validate_media_path(req.target_dir, principal, must_exist=False) if req.target_dir else None
    try:
        return await asyncio.to_thread(
            preview_organize,
            src,
            dst,
            req.media_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/media/organize/apply",
    dependencies=[Depends(require_scope("storage:write", "storage:admin"))],
)
async def apply_media_organization(
    req: MediaOrganizeApplyRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Applies media renames and folder restructuring (move, copy, or hardlink)."""
    validated_items = []
    for it in req.items:
        clean_it = dict(it)
        src = clean_it.get("source_path") or clean_it.get("source")
        dst = clean_it.get("destination_path") or clean_it.get("target")
        if not src or not dst:
            raise HTTPException(status_code=400, detail="Missing source or destination path in organize item")
        clean_it["source_path"] = _validate_media_path(src, principal, must_exist=True)
        clean_it["destination_path"] = _validate_media_path(dst, principal, must_exist=False)
        validated_items.append(clean_it)

    try:
        return await asyncio.to_thread(
            apply_organize,
            validated_items,
            req.action,
            req.hardlink,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
