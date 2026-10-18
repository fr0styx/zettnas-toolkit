"""
ZettNAS Toolkit - Smart Media, Multi-Modal Local RAG & Visual Search API Router
Exposes hardware-accelerated (NPU -> GPU -> CPU) document/recipe RAG,
12-color perceptual + scene photo search, spindown-safe incremental indexing,
cached NVMe WebP thumbnails, and FileBot-style automated media organizing.
"""

import asyncio
import ipaddress
import os
from typing import Any, Dict, List, Optional
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from backend.api.system import check_user_path_access
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import ALLOWED_BROWSE_ROOTS, POOL_PATH
from backend.fsutil import resolve_within
from backend.services.ai_chat_agent import (
    AVAILABLE_NAS_TOOLS,
    build_llm_execution_telemetry,
    run_agentic_chat,
    stream_agentic_chat,
)
from backend.services.media_engine import (
    get_media_engine,
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

router = APIRouter(tags=["Smart Media & AI RAG Engine"])


def _validate_media_path(path: str, principal: Optional[AuthenticatedPrincipal], must_exist: bool = True) -> str:
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
    media_path: Optional[str] = Field(default="/mnt/storage/media", max_length=512)


class RagIndexSyncRequest(BaseModel):
    path: Optional[str] = Field(default=None, max_length=512)
    media_path: Optional[str] = Field(default=None, max_length=512)
    paths: Optional[List[str]] = None
    recursive: bool = True
    respect_standby: bool = True
    force_wake: bool = False
    background: bool = False
    max_files: int = Field(default=5000, ge=1, le=50000)


class RagSyncControlRequest(BaseModel):
    action: str = Field(..., pattern="^(pause|resume|stop|status)$")


class RagWatchedFoldersRequest(BaseModel):
    action: str = Field(default="set", pattern="^(add|remove|set)$")
    target: str = Field(default="watched", pattern="^(watched|excluded)$")
    path: Optional[str] = Field(default=None, max_length=512)
    paths: Optional[List[str]] = None


class MultimodalSearchRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    q: Optional[str] = Field(default=None, max_length=500)
    mode: str = Field(default="all", max_length=32)
    modality: Optional[str] = Field(default=None, max_length=32)
    file_type: Optional[str] = Field(default=None, max_length=32)
    match_tab: str = Field(default="semantic", max_length=32)
    sort_by: str = Field(default="relevance", max_length=32)
    colors: Optional[List[str]] = None
    color: Optional[str] = Field(default=None, max_length=64)
    scenes: Optional[List[str]] = None
    scene: Optional[str] = Field(default=None, max_length=64)
    path_prefix: Optional[str] = Field(default=None, max_length=512)
    limit: int = Field(default=24, ge=1, le=100)


class RagAskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    scope: str = Field(default="all", max_length=32)
    path_prefix: Optional[str] = Field(default=None, max_length=512)
    top_k: int = Field(default=5, ge=1, le=12)
    limit: Optional[int] = Field(default=None, ge=1, le=20)


class RagConfigUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    scope_mode: Optional[str] = None
    respect_standby: Optional[bool] = None
    auto_learn_on_spinup: Optional[bool] = None
    compute_preference: Optional[str] = None
    watched_paths: Optional[List[str]] = None
    excluded_paths: Optional[List[str]] = None
    schedule_enabled: Optional[bool] = None
    schedule_start: Optional[str] = None
    schedule_end: Optional[str] = None
    active_model: Optional[str] = None
    llm_endpoint: Optional[str] = None
    llm_model: Optional[str] = None
    idle_unload_minutes: Optional[int] = None


class ModelSelectRequest(BaseModel):
    model: Optional[str] = Field(default=None, max_length=256)
    model_id: Optional[str] = Field(default=None, max_length=256)


class ModelRemoveRequest(BaseModel):
    model: Optional[str] = Field(default=None, max_length=256)
    model_id: Optional[str] = Field(default=None, max_length=256)


class HuggingFacePullRequest(BaseModel):
    repo_id: str = Field(..., min_length=1, max_length=256)
    activate: bool = True


class AiChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: Optional[List[Dict[str, Any]]] = None
    allow_web_search: bool = True
    allow_nas_tools: bool = True
    model: Optional[str] = Field(default=None, max_length=256)


class FavoriteToggleRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)


class MediaOrganizePreviewRequest(BaseModel):
    source_dir: str = Field(..., min_length=1)
    target_dir: Optional[str] = None
    media_type: str = "auto"  # "auto", "tv", "movie"


class MediaOrganizeApplyRequest(BaseModel):
    items: List[Dict[str, Any]] = Field(..., min_length=1)
    action: str = Field("move", pattern="^(move|copy)$")
    hardlink: bool = False


class FolderAuditRequest(BaseModel):
    folder_path: str = Field(..., min_length=1, max_length=1024)
    query: Optional[str] = Field(default=None, max_length=1000)
    mode: str = Field("comprehensive", pattern="^(comprehensive|targeted)$")
    max_tokens: int = Field(default=4000, ge=500, le=16000)


@router.get("/media/status", dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))])
@router.get("/ai/status", dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))])
def get_media_status() -> Dict[str, Any]:
    engine = get_media_engine()
    status = engine.get_status()
    status["config"] = get_rag_engine().get_config()
    return status


@router.post("/media/scan", dependencies=[Depends(require_scope("system:config"))])
def trigger_media_scan(
    req: MediaScanRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> Dict[str, Any]:
    engine = get_media_engine()
    raw_target = req.media_path or "/mnt/storage/media"
    if raw_target == "/mnt/storage/media" and not os.path.exists(raw_target) and os.path.exists(POOL_PATH):
        raw_target = POOL_PATH
    validated_path = _validate_media_path(raw_target, principal, must_exist=True)
    try:
        return engine.trigger_scan(media_path=validated_path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    req: RagIndexSyncRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> Dict[str, Any]:
    """
    Runs incremental, spindown-safe multi-modal indexing on the requested directory or watched folders.
    Respects `smartctl -n standby` / `Z_STATE.cached_smart_data` / Unraid `disks.ini` by default so sleeping HDDs are never woken.
    Supports synchronous or background execution with Pause/Resume/Stop controls.
    """
    if req.force_wake and not principal.has_any_scope("storage:admin", "system:config", "*"):
        raise HTTPException(status_code=403, detail="Forcing wake on sleeping disks requires storage:admin scope.")

    rag = get_rag_engine()
    raw_targets: List[str] = []
    if req.paths and len(req.paths) > 0:
        raw_targets = [str(p).strip() for p in req.paths if str(p).strip()]
    elif req.path or req.media_path:
        raw_targets = [str(req.path or req.media_path).strip()]
    else:
        cfg_watched = rag.get_config().get("watched_paths") or []
        raw_targets = [str(p).strip() for p in cfg_watched if str(p).strip()]
        if not raw_targets:
            raw_targets = [POOL_PATH or "/mnt/user"]

    validated_paths: List[str] = []
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
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin", "system:config"))],
)
@router.post(
    "/ai/index/control",
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin", "system:config"))],
)
def control_rag_index(req: RagSyncControlRequest) -> Dict[str, Any]:
    """Pause, resume, stop, or query the active RAG & Visual Search indexing sync job."""
    rag = get_rag_engine()
    act = req.action.strip().lower()
    if act == "pause":
        res = rag.pause_sync()
    elif act == "resume":
        res = rag.resume_sync()
    elif act == "stop":
        res = rag.stop_sync()
    else:
        res = {"status": "ok", "sync_state": rag.get_sync_progress().get("state", "idle")}
    res["sync_progress"] = rag.get_sync_progress()
    res["stats"] = rag.get_index_stats()
    return res


@router.get(
    "/media/folders",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
@router.get(
    "/ai/folders",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
def get_watched_folders() -> Dict[str, Any]:
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
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin", "system:config"))],
)
@router.post(
    "/ai/folders",
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin", "system:config"))],
)
def update_watched_folders(
    req: RagWatchedFoldersRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Dict[str, Any]:
    """Adds, removes, or sets watched or excluded folders/shares for ZettAI RAG."""
    rag = get_rag_engine()
    cfg = rag.get_config()
    list_key = "excluded_paths" if req.target == "excluded" else "watched_paths"
    current: List[str] = [os.path.normpath(str(p)) for p in (cfg.get(list_key) or []) if str(p).strip()]
    act = req.action.strip().lower()
    added_vp: Optional[str] = None

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
        validated_list: List[str] = []
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
    "/media/models/recommendations",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
@router.get(
    "/ai/models/recommendations",
    dependencies=[Depends(require_scope("system:read", "shares:read", "storage:read"))],
)
def get_model_recommendations(
    sort_by: str = Query(default="date", max_length=32),
    min_year: Optional[int] = Query(default=2026),
) -> Dict[str, Any]:
    """Returns hardware-aware LLM & Multi-Modal model recommendations based on onboard NPU, GPU, and RAM."""
    status = get_media_engine().get_status()
    accel = status["acceleration"]
    ram_gb = status["total_ram_gb"]
    rag_cfg = get_rag_engine().get_config()
    from backend.services.media_engine import build_llm_recommendations

    recs = build_llm_recommendations(
        accel=accel,
        ram_gb=ram_gb,
        active_model=rag_cfg.get("active_model") or "hf.co/Kujira/Underdog-Saluki-27B-1.0-MTP-Abliterated-GGUF",
        custom_models=rag_cfg.get("custom_hf_models", []),
        sort_by=sort_by,
        min_release_year=min_year,
    )
    return {
        "status": "ok",
        "acceleration": status["acceleration"],
        "llm_recommendations": recs,
    }


@router.post(
    "/media/models/select",
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
@router.post(
    "/ai/models/select",
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
def select_recommended_model(req: ModelSelectRequest) -> Dict[str, Any]:
    """Selects and applies an LLM / multi-modal model for ZettAI, returning any hardware fit warnings."""
    rag = get_rag_engine()
    model_tag = str(req.model or req.model_id or "").strip()
    if not model_tag:
        raise HTTPException(status_code=400, detail="Model identifier is required.")
    updated_cfg = rag.update_config({"active_model": model_tag, "llm_model": model_tag})
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
    min_year: Optional[int] = Query(default=2026),
) -> Dict[str, Any]:
    """Searches https://huggingface.co release models and evaluates hardware fit against NAS NPU/GPU/RAM."""
    return search_huggingface_models(query=q, limit=limit, sort_by=sort_by, min_release_year=min_year)


@router.post(
    "/media/models/huggingface/pull",
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
@router.post(
    "/ai/models/huggingface/pull",
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
def pull_hf_release_model(req: HuggingFacePullRequest) -> Dict[str, Any]:
    """Pulls/registers a release model from https://huggingface.co and flags hardware fit warnings."""
    try:
        return pull_huggingface_model(repo_id=req.repo_id, activate=req.activate)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/media/models/remove",
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
@router.post(
    "/ai/models/remove",
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
def remove_model_post_endpoint(req: ModelRemoveRequest) -> Dict[str, Any]:
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
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
@router.delete(
    "/ai/models/remove",
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
def remove_model_delete_explicit_endpoint(
    model: Optional[str] = Query(default=None),
    model_id: Optional[str] = Query(default=None),
    req: Optional[ModelRemoveRequest] = None,
) -> Dict[str, Any]:
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
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
@router.delete(
    "/ai/models/{model_id:path}",
    dependencies=[Depends(require_scope("system:config", "storage:admin", "shares:user_write"))],
)
def delete_model_endpoint(model_id: str) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
    """Returns ZettAI 6-state learning status, succeeded/failed counts, and failed file list."""
    return {"status": "ok", **get_rag_engine().get_learning_results(principal=principal)}


@router.post(
    "/media/learning/relearn-failed",
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin", "system:config"))],
)
@router.post(
    "/ai/learning/relearn-failed",
    dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin", "system:config"))],
)
async def relearn_failed_items() -> Dict[str, Any]:
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
) -> Dict[str, Any]:
    """Adds or removes a file path from ZettAI favorites."""
    vp = _validate_media_path(req.path, principal, must_exist=False)
    return get_rag_engine().toggle_favorite(vp)


@router.get(
    "/media/search",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.get(
    "/ai/search",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def search_multimodal_get(
    q: str = Query(default="", max_length=500),
    query: Optional[str] = Query(default=None, max_length=500),
    mode: str = Query(default="all", max_length=32),
    modality: Optional[str] = Query(default=None, max_length=32),
    match_tab: str = Query(default="semantic", max_length=32),
    sort_by: str = Query(default="relevance", max_length=32),
    colors: Optional[str] = Query(default=None, max_length=256),
    color: Optional[str] = Query(default=None, max_length=64),
    scenes: Optional[str] = Query(default=None, max_length=256),
    scene: Optional[str] = Query(default=None, max_length=64),
    path_prefix: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=24, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Dict[str, Any]:
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
    return await asyncio.to_thread(
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
    )


@router.post(
    "/media/search",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.post(
    "/ai/search",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def search_multimodal_post(
    req: MultimodalSearchRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Dict[str, Any]:
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
    return await asyncio.to_thread(
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
    )


@router.post(
    "/media/ask",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.post(
    "/ai/ask",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def ask_knowledge_base(
    req: RagAskRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Dict[str, Any]:
    """Grounded Conversational RAG & Structured Recipe/Document Synthesis."""
    validated_prefix = None
    if req.path_prefix and req.path_prefix.strip():
        validated_prefix = _validate_media_path(req.path_prefix, principal, must_exist=False)

    effective_top_k = min(12, max(1, int(req.limit if req.limit is not None else req.top_k)))
    rag = get_rag_engine()
    res = await asyncio.to_thread(
        rag.ask,
        req.query,
        req.scope,
        validated_prefix,
        effective_top_k,
        principal,
    )
    status = get_media_engine().get_status()
    accel = status["acceleration"]
    cfg = rag.get_config()
    active_model = str(cfg.get("active_model") or cfg.get("llm_model") or "qwen2.5:3b")
    res["hardware"] = accel
    res["active_model"] = active_model
    res["llm_telemetry"] = build_llm_execution_telemetry(
        active_model=active_model,
        accel=accel,
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
) -> Dict[str, Any]:
    """Retrieves the recursive structure outline and topic inventory for a folder from NVMe SQLite WAL."""
    validated_path = _validate_media_path(folder_path, principal, must_exist=False)
    rag = get_rag_engine()
    manifest = await asyncio.to_thread(rag.get_folder_manifest, validated_path)
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
) -> Dict[str, Any]:
    """Lists all indexed folder manifests and tree summaries across watched storage shares."""
    rag = get_rag_engine()
    manifests = await asyncio.to_thread(rag.list_folder_manifests, limit=limit)
    from backend.api.fs import user_can_access_path

    accessible = [m for m in manifests if user_can_access_path(m.get("folder_path", ""), principal)]
    return {"status": "ok", "count": len(accessible), "manifests": accessible}


@router.post(
    "/media/folder/audit",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.post(
    "/ai/folder/audit",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def audit_folder_endpoint(
    req: FolderAuditRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Dict[str, Any]:
    """
    Executes hierarchical folder context aggregation (Mode A: targeted fact retrieval;
    Mode B: comprehensive folder audit with MMR diversification) with 0 disk wakeups.
    """
    validated_path = _validate_media_path(req.folder_path, principal, must_exist=False)
    rag = get_rag_engine()
    res = await asyncio.to_thread(
        rag.aggregate_folder_context,
        folder_path=validated_path,
        query=req.query,
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
def get_ai_chat_tools() -> Dict[str, Any]:
    """Returns the list of NAS hardware & web browsing tools available to the ZettAI Chatbot."""
    rag_cfg = get_rag_engine().get_config()
    return {
        "status": "ok",
        "active_model": rag_cfg.get("active_model") or "qwen2.5:3b",
        "tools": AVAILABLE_NAS_TOOLS,
    }


@router.post(
    "/media/chat",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.post(
    "/ai/chat",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def chat_with_zettai_agent(
    req: AiChatRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Dict[str, Any]:
    """
    Conversational ZettAI Local Chatbot & NAS Hardware Copilot with live internet browsing
    and hardware/Docker/storage tool execution.
    """
    try:
        return await asyncio.to_thread(
            run_agentic_chat,
            req.message,
            req.history,
            req.allow_web_search,
            req.allow_nas_tools,
            req.model,
            principal,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/media/chat/stream",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
@router.post(
    "/ai/chat/stream",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:read"))],
)
async def chat_with_zettai_agent_stream(
    req: AiChatRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Response:
    """Streams real-time Server-Sent Events (SSE) tokens, tool activity traces, and thought chains from ZettAI."""
    from fastapi.responses import StreamingResponse

    generator = stream_agentic_chat(
        message=req.message,
        history=req.history,
        allow_web_search=req.allow_web_search,
        allow_nas_tools=req.allow_nas_tools,
        model_override=req.model,
        principal=principal,
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
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied to this file")


@router.get(
    "/media/config",
    dependencies=[Depends(require_scope("system:read", "storage:read"))],
)
@router.get(
    "/ai/config",
    dependencies=[Depends(require_scope("system:read", "storage:read"))],
)
def get_rag_config() -> Dict[str, Any]:
    return get_rag_engine().get_config()


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
def update_rag_config(req: RagConfigUpdateRequest) -> Dict[str, Any]:
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
                raise HTTPException(status_code=400, detail="Cloud metadata endpoints are forbidden.")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    return get_rag_engine().update_config(updates)


@router.post(
    "/media/organize/preview",
    dependencies=[Depends(require_scope("storage:read", "storage:admin"))],
)
async def preview_media_organization(
    req: MediaOrganizePreviewRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> Dict[str, Any]:
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
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/media/organize/apply",
    dependencies=[Depends(require_scope("storage:write", "storage:admin"))],
)
async def apply_media_organization(
    req: MediaOrganizeApplyRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> Dict[str, Any]:
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
        raise HTTPException(status_code=500, detail=str(e))
