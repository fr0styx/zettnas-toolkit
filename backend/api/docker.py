# ZettNAS Toolkit - Docker Container & Stack Management API Router
import asyncio
import json
import os
import re
import socket
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.hardware.docker_stats import container_action, read_docker_containers
from backend.models.schemas import DockerActionRequest

router = APIRouter(tags=["Docker Containers & Stacks"])


def _resolve_read_docker_containers():
    import backend.api.system as sys_mod

    if hasattr(sys_mod, "read_docker_containers") and sys_mod.read_docker_containers != read_docker_containers:
        return sys_mod.read_docker_containers
    return read_docker_containers


def _resolve_container_action():
    import backend.api.system as sys_mod

    if hasattr(sys_mod, "container_action") and sys_mod.container_action != container_action:
        return sys_mod.container_action
    return container_action


@router.get("/docker/containers")
async def get_docker_containers():
    fn = _resolve_read_docker_containers()
    return await asyncio.to_thread(fn)


@router.post(
    "/docker/containers/{container_id}/action",
    dependencies=[Depends(require_scope("containers:write", "containers:manage"))],
)
async def post_docker_container_action(container_id: str, req: DockerActionRequest):
    fn = _resolve_container_action()
    res = await asyncio.to_thread(fn, container_id, req.action)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Action failed"))
    return res


@router.get("/docker/containers/{container_id}/compose")
async def get_docker_container_compose(container_id: str, request: Request, unmask: bool = False):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.compose_synthesizer import get_container_compose_data

    # Only unmask if explicitly requested AND caller has containers:manage or superadmin
    allow_unmasked = False
    if unmask:
        sess = getattr(request.state, "session", None)
        if not sess:
            from backend.auth import extract_token, get_current_session

            tok = extract_token(request)
            sess = get_current_session(tok) if tok else None
        if sess:
            principal = AuthenticatedPrincipal(sess)
            allow_unmasked = (
                principal.role_id in ("superadmin", "storage_admin")
                or principal.has_scope("containers:manage")
                or principal.has_scope("*")
            )

    data = await asyncio.to_thread(get_container_compose_data, container_id, allow_unmasked=allow_unmasked)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


@router.get("/docker/containers/{container_id}/details")
async def get_docker_container_details(container_id: str, request: Request, unmask: bool = False):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.compose_synthesizer import get_container_full_details

    # Only unmask if explicitly requested AND caller has containers:manage or superadmin
    allow_unmasked = False
    if unmask:
        sess = getattr(request.state, "session", None)
        if not sess:
            from backend.auth import extract_token, get_current_session

            tok = extract_token(request)
            sess = get_current_session(tok) if tok else None
        if sess:
            principal = AuthenticatedPrincipal(sess)
            allow_unmasked = (
                principal.role_id in ("superadmin", "storage_admin")
                or principal.has_scope("containers:manage")
                or principal.has_scope("*")
            )

    data = await asyncio.to_thread(get_container_full_details, container_id, allow_unmasked=allow_unmasked)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


@router.get("/docker/containers/{container_id}/logs")
async def get_docker_container_logs(container_id: str, tail: int = 200):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.compose_synthesizer import get_container_logs_chunk

    return await asyncio.to_thread(get_container_logs_chunk, container_id, tail)


class DockerResourceUpdateRequest(BaseModel):
    memory_mb: Optional[int] = None
    nano_cpus: Optional[float] = None
    cpu_shares: Optional[int] = None
    restart_policy: Optional[str] = None


@router.post("/docker/containers/{container_id}/resources", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_container_resources(container_id: str, req: DockerResourceUpdateRequest):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.container_mutator import update_container_resources

    try:
        res = await asyncio.to_thread(
            update_container_resources,
            container_id,
            memory_mb=req.memory_mb,
            nano_cpus=req.nano_cpus,
            cpu_shares=req.cpu_shares,
            restart_policy=req.restart_policy,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Docker] Resource update failed for {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PortMappingItem(BaseModel):
    container_port: int
    host_port: Optional[int] = None
    proto: str = "tcp"
    host_ip: str = "0.0.0.0"


class DockerPortRecreateRequest(BaseModel):
    ports: List[PortMappingItem]
    keep_backup: bool = False


@router.post("/docker/containers/{container_id}/ports", dependencies=[Depends(require_scope("containers:manage"))])
async def post_docker_container_ports(container_id: str, req: DockerPortRecreateRequest):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.container_mutator import recreate_container_ports

    try:
        ports_dicts = [p.model_dump() for p in req.ports]
        res = await asyncio.to_thread(
            recreate_container_ports,
            container_id,
            new_port_bindings=ports_dicts,
            keep_backup=req.keep_backup,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Docker] Port recreate failed for {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class DockerContainerRecreateRequest(BaseModel):
    name: Optional[str] = None
    image: Optional[str] = None
    env: Optional[List[str]] = None
    binds: Optional[List[str]] = None
    port_bindings: Optional[List[PortMappingItem]] = None
    network_mode: Optional[str] = None
    restart_policy: Optional[str] = None
    pull_image: bool = False
    keep_backup: bool = False
    grace_period_seconds: float = 3.0


@router.post(
    "/docker/containers/{container_id}/recreate",
    dependencies=[Depends(require_scope("containers:manage"))],
)
async def post_docker_container_recreate(container_id: str, req: DockerContainerRecreateRequest):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.container_mutator import recreate_container

    try:
        ports_dicts = [p.model_dump() for p in req.port_bindings] if req.port_bindings is not None else None
        res = await asyncio.to_thread(
            recreate_container,
            cid=container_id,
            name=req.name,
            image=req.image,
            env=req.env,
            binds=req.binds,
            port_bindings=ports_dicts,
            network_mode=req.network_mode,
            restart_policy=req.restart_policy,
            pull_image=req.pull_image,
            keep_backup=req.keep_backup,
            grace_period_seconds=req.grace_period_seconds,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Docker] Container recreate failed for {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/docker/updates/status", dependencies=[Depends(require_scope("containers:read", "system:view"))])
async def get_docker_updates_status():
    from backend.services.docker_updates import get_cached_update_status

    return await asyncio.to_thread(get_cached_update_status)


@router.post("/docker/updates/check", dependencies=[Depends(require_scope("containers:read", "system:view"))])
async def post_docker_updates_check():
    from backend.services.docker_updates import check_all_container_updates

    return await asyncio.to_thread(check_all_container_updates, force=True)


@router.post(
    "/docker/containers/{container_id}/update-image",
    dependencies=[Depends(require_scope("containers:manage"))],
)
async def post_docker_container_update_image(container_id: str):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.docker_updates import update_single_container

    try:
        res = await asyncio.to_thread(update_single_container, container_id)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Docker] Update image failed for {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/docker/updates/apply-all",
    dependencies=[Depends(require_scope("containers:manage"))],
)
async def post_docker_updates_apply_all():
    from backend.services.docker_updates import update_all_containers

    try:
        res = await asyncio.to_thread(update_all_containers)
        return res
    except Exception as e:
        logger.error(f"[Docker] Batch update all failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class StackSaveRequest(BaseModel):
    compose_yaml: str
    env_content: Optional[str] = None


class StackActionRequest(BaseModel):
    action: str  # "restart", "stop", "start", "redeploy"


@router.get(
    "/docker/stacks",
    dependencies=[Depends(require_scope("containers:read", "containers:manage"))],
)
async def get_docker_stacks():
    from backend.services.docker_stacks import list_all_stacks

    return await asyncio.to_thread(list_all_stacks)


@router.get(
    "/docker/stacks/{stack_name}",
    dependencies=[Depends(require_scope("containers:read", "containers:manage"))],
)
async def get_docker_stack_details(
    stack_name: str,
    unmask: bool = False,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    if not stack_name or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", stack_name):
        raise HTTPException(status_code=400, detail="Invalid stack name")
    from backend.services.docker_stacks import get_stack_details

    details = await asyncio.to_thread(get_stack_details, stack_name)
    if not details.get("containers") and not details.get("has_real_file"):
        raise HTTPException(status_code=404, detail=f"Stack '{stack_name}' not found")

    can_unmask = principal and (
        principal.role_id in ("superadmin", "admin")
        or principal.has_scope("containers:manage")
        or principal.has_scope("*")
    )
    if not (unmask and can_unmask):
        if details.get("env_content"):
            masked_lines = []
            for line in details["env_content"].splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    if any(s in k.lower() for s in ("pass", "secret", "token", "key", "auth", "pwd")):
                        masked_lines.append(f"{k}=••••••••")
                        continue
                masked_lines.append(line)
            details["env_content"] = "\n".join(masked_lines)

    return details


@router.post(
    "/docker/stacks/{stack_name}/save",
    dependencies=[Depends(require_scope("containers:manage"))],
)
async def post_docker_stack_save(stack_name: str, req: StackSaveRequest):
    if not stack_name or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", stack_name):
        raise HTTPException(status_code=400, detail="Invalid stack name")
    from backend.services.docker_stacks import save_stack_config

    res = await asyncio.to_thread(save_stack_config, stack_name, req.compose_yaml, req.env_content)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed saving stack configuration"))
    return res


@router.post(
    "/docker/stacks/{stack_name}/action",
    dependencies=[Depends(require_scope("containers:write", "containers:manage"))],
)
async def post_docker_stack_action(stack_name: str, req: StackActionRequest):
    if not stack_name or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", stack_name):
        raise HTTPException(status_code=400, detail="Invalid stack name")
    from backend.services.docker_stacks import execute_stack_action

    res = await asyncio.to_thread(execute_stack_action, stack_name, req.action)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", f"Stack action '{req.action}' failed"))
    return res


@router.get("/docker/check_port")
async def get_check_port(port: int, proto: str = "tcp"):
    from backend.services.container_mutator import check_port_available_detailed

    available, in_use_by = await asyncio.to_thread(check_port_available_detailed, port, proto)
    return {"port": port, "proto": proto, "available": available, "in_use_by": in_use_by}


class ContainerExecRequest(BaseModel):
    cmd: str


@router.post("/docker/containers/{container_id}/exec", dependencies=[Depends(require_scope("containers:exec"))])
async def post_docker_container_exec(container_id: str, req: ContainerExecRequest):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.compose_synthesizer import execute_in_container

    res = await asyncio.to_thread(execute_in_container, container_id, req.cmd)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Execution failed"))
    return res


async def _authenticate_ws(websocket: WebSocket) -> bool:
    token = (
        websocket.query_params.get("token")
        or websocket.query_params.get("ticket")
        or websocket.cookies.get("zettnas_session")
        or websocket.cookies.get("session_token")
        or websocket.cookies.get("zat_token")
    )
    if not token:
        return False
    from backend.auth import get_current_session, validate_session
    from backend.users_db import validate_scoped_api_token, validate_user_session

    if get_current_session(token) or validate_session(token) or validate_user_session(token):
        return True
    if validate_scoped_api_token(token):
        return True
    return False


@router.websocket("/docker/containers/{container_id}/terminal/ws")
@router.websocket("/docker/containers/{container_id}/exec/ws")
async def websocket_docker_terminal(websocket: WebSocket, container_id: str):
    """
    Interactive bidirectional WebSocket PTY terminal.
    Streams ANSI stdout/stderr directly from container shell and pipes user keystrokes to stdin.
    Supports resize control messages: {"type": "resize", "cols": 120, "rows": 40}.
    """
    if not await _authenticate_ws(websocket):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await websocket.accept()
    from backend.services.docker_terminal import stream_container_terminal

    shell = websocket.query_params.get("shell") or "/bin/sh"
    await stream_container_terminal(websocket, container_id, shell=shell)


class DockerContainerDeleteRequest(BaseModel):
    force: bool = False
    remove_volumes: bool = True
    remove_image: bool = False
    archive_data: bool = True


@router.delete("/docker/containers/{container_id}", dependencies=[Depends(require_scope("containers:manage"))])
async def delete_docker_container(
    container_id: str,
    force: bool = False,
    remove_volumes: bool = True,
    remove_image: bool = False,
    archive_data: bool = True,
):
    if not container_id or not re.match(r"^[a-zA-Z0-9_.-]{1,128}$", container_id):
        raise HTTPException(status_code=400, detail="Invalid container ID or name")
    from backend.services.docker_cleanup import destroy_container

    try:
        res = await asyncio.to_thread(
            destroy_container,
            container_id,
            force=force,
            remove_volumes=remove_volumes,
            remove_image=remove_image,
            archive_data=archive_data,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Docker Cleanup] Failed to delete container {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/docker/system/df")
async def get_system_df():
    from backend.services.docker_cleanup import get_docker_system_df

    try:
        return await asyncio.to_thread(get_docker_system_df)
    except Exception as e:
        logger.error(f"[Docker Cleanup] Failed to get system df: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class DockerPruneRequest(BaseModel):
    prune_containers: bool = True
    prune_images: bool = True
    all_images: bool = False
    prune_volumes: bool = False
    prune_networks: bool = True
    prune_build_cache: bool = True


@router.post("/docker/system/prune", dependencies=[Depends(require_scope("containers:manage"))])
async def post_system_prune(req: Optional[DockerPruneRequest] = None):
    from backend.services.docker_cleanup import prune_docker_system

    payload = req or DockerPruneRequest()
    try:
        res = await asyncio.to_thread(
            prune_docker_system,
            prune_containers=payload.prune_containers,
            prune_images=payload.prune_images or payload.all_images,
            all_images=payload.all_images,
            prune_volumes=payload.prune_volumes,
            prune_networks=payload.prune_networks,
            prune_build_cache=payload.prune_build_cache,
        )
        return res
    except Exception as e:
        logger.error(f"[Docker Cleanup] Prune failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
