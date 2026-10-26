"""The background file tasks: list, live stream, pause, resume, cancel, clear.

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.files.common import _assert_task_owner, _task_owner_filter
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope

router = APIRouter()


@router.get(
    "/fs/transfers",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
def fs_list_transfers(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    return {"status": "ok", "tasks": transfer_manager.list_tasks(owner=_task_owner_filter(principal))}


@router.get("/fs/transfers/stream")
async def fs_transfers_stream(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    from backend.services.fs_transfer import transfer_manager

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=100)
    transfer_manager.register_listener(queue, loop)

    async def event_generator():
        try:
            owner = _task_owner_filter(principal)
            initial_data = json.dumps({"event": "snapshot", "tasks": transfer_manager.list_tasks(owner=owner)})
            yield f"event: snapshot\ndata: {initial_data}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    if owner is not None and (payload.get("task") or {}).get("owner") != owner:
                        continue
                    evt_type = payload.get("event", "update")
                    data_str = json.dumps(payload)
                    yield f"event: {evt_type}\ndata: {data_str}\n\n"
                except TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            transfer_manager.unregister_listener(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/fs/transfers/{task_id}/pause",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def fs_pause_transfer(task_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    _assert_task_owner(task_id, principal)
    ok = transfer_manager.pause_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found or cannot be paused")
    return {"status": "ok", "paused": True}


@router.post(
    "/fs/transfers/{task_id}/resume",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def fs_resume_transfer(task_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    _assert_task_owner(task_id, principal)
    ok = transfer_manager.resume_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found or cannot be resumed")
    return {"status": "ok", "resumed": True}


@router.post(
    "/fs/transfers/{task_id}/cancel",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def fs_cancel_transfer(task_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    _assert_task_owner(task_id, principal)
    ok = transfer_manager.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found or cannot be cancelled")
    return {"status": "ok", "cancelled": True}


@router.delete(
    "/fs/transfers/completed",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
def fs_clear_completed_transfers(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.fs_transfer import transfer_manager

    cleared = transfer_manager.clear_completed_tasks()
    return {"status": "ok", "cleared_count": cleared}
