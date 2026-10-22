# ZettNAS Toolkit - Docker App Catalog API Router
import asyncio
import json
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.auth import require_scope
from backend.config import logger

router = APIRouter(tags=["Docker App Catalog"])


class AppSourceCreateRequest(BaseModel):
    name: str
    url: str


class AppSourceToggleRequest(BaseModel):
    enabled: bool


class AppSideloadRequest(BaseModel):
    url: str | None = None
    manifest_content: str | None = None


class AppComposeRequest(BaseModel):
    host_port: int | None = None
    storage_root: str = "/mnt/user/appdata"
    container_name: str | None = None
    env_overrides: dict[str, str] | None = None
    volume_overrides: dict[str, str] | None = None
    stack_services: dict[str, Any] | None = None


class ContainerExecRequest(BaseModel):
    cmd: str


@router.get("/docker/catalog")
async def get_docker_catalog():
    from backend.services.app_catalog import get_all_catalog_apps

    return await asyncio.to_thread(get_all_catalog_apps)


@router.get("/docker/catalog/sources")
async def get_docker_catalog_sources():
    from backend.services.app_catalog import get_catalog_sources

    return await asyncio.to_thread(get_catalog_sources)


@router.post("/docker/catalog/sources", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_sources(req: AppSourceCreateRequest):
    from backend.services.app_catalog import add_catalog_source

    try:
        res = await asyncio.to_thread(add_catalog_source, req.name, req.url)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[AppCatalog] Failed to add source: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/docker/catalog/sources/{source_id}", dependencies=[Depends(require_scope("containers:manage"))])
async def delete_docker_catalog_source(source_id: str):
    if not source_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", source_id):
        raise HTTPException(status_code=400, detail="Invalid source ID")

    from backend.services.app_catalog import delete_catalog_source

    try:
        deleted = await asyncio.to_thread(delete_catalog_source, source_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Source not found")
        return {"status": "ok", "deleted": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[AppCatalog] Failed to delete source: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/docker/catalog/sources/{source_id}/sync", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_source_sync(source_id: str):
    if not source_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", source_id):
        raise HTTPException(status_code=400, detail="Invalid source ID")

    from backend.services.app_catalog import sync_catalog_source

    try:
        updated = await asyncio.to_thread(sync_catalog_source, source_id)
        return {"status": "ok", "source": updated}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[AppCatalog] Failed to sync source: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/docker/catalog/sources/{source_id}/toggle", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_source_toggle(source_id: str, req: AppSourceToggleRequest):
    if not source_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", source_id):
        raise HTTPException(status_code=400, detail="Invalid source ID")

    from backend.services.app_catalog import toggle_catalog_source

    try:
        updated = await asyncio.to_thread(toggle_catalog_source, source_id, req.enabled)
        return {"status": "ok", "source": updated}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[AppCatalog] Failed to toggle source: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/docker/catalog/sideload", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_sideload(req: AppSideloadRequest):
    """Sideloads an application from a URL (e.g. GitHub raw zett-app.json / compose) or direct manifest content."""
    from backend.services.app_catalog import sideload_app_manifest

    try:
        res = await asyncio.to_thread(sideload_app_manifest, req.url, req.manifest_content)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[AppCatalog] Failed to sideload manifest: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/docker/catalog/{app_id}/resolve")
async def get_docker_catalog_resolve(app_id: str):
    if not app_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", app_id):
        raise HTTPException(status_code=400, detail="Invalid application ID")
    from backend.services.app_catalog import resolve_app_port_conflict

    res = await asyncio.to_thread(resolve_app_port_conflict, app_id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.post("/docker/catalog/{app_id}/compose", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_compose(app_id: str, req: AppComposeRequest | None = None):
    if not app_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", app_id):
        raise HTTPException(status_code=400, detail="Invalid application ID")
    from backend.services.app_catalog import generate_compose_for_app

    host_port = req.host_port if req else None
    storage_root = req.storage_root if req else "/mnt/user/appdata"
    container_name = req.container_name if req else None
    env_overrides = req.env_overrides if req else None
    volume_overrides = req.volume_overrides if req else None
    stack_services = req.stack_services if req else None
    res = await asyncio.to_thread(
        generate_compose_for_app,
        app_id,
        host_port=host_port,
        storage_root=storage_root,
        container_name=container_name,
        env_overrides=env_overrides,
        volume_overrides=volume_overrides,
        stack_services=stack_services,
    )
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


class AppDeployRequest(BaseModel):
    host_port: int | None = None
    storage_root: str = "/mnt/user/appdata"
    container_name: str | None = None
    replace_existing: bool = False


@router.get("/docker/check_container_name")
async def get_check_container_name(name: str):
    from backend.services.container_mutator import _docker_request

    clean_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name.strip())
    st, c_info = await asyncio.to_thread(_docker_request, "GET", f"/containers/{clean_name}/json")
    exists = st == 200
    running = False
    if exists and isinstance(c_info, dict):
        running = bool(c_info.get("State", {}).get("Running", False))
    return {"name": clean_name, "exists": exists, "running": running}


@router.post("/docker/catalog/{app_id}/deploy", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_catalog_deploy(app_id: str, req: AppDeployRequest | None = None):
    if not app_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", app_id):
        raise HTTPException(status_code=400, detail="Invalid application ID")

    from fastapi.responses import StreamingResponse

    from backend.services.app_catalog import stream_deploy_catalog_app

    host_port = req.host_port if req else None
    storage_root = req.storage_root if req else "/mnt/user/appdata"
    container_name = req.container_name if req else None
    replace_existing = req.replace_existing if req else False

    def event_stream():
        for event in stream_deploy_catalog_app(
            app_id,
            host_port=host_port,
            storage_root=storage_root,
            container_name=container_name,
            replace_existing=replace_existing,
        ):
            yield json.dumps(event) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
