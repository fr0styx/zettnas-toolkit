"""
ZettNAS Toolkit - Remote & Cloud Storage API
REST endpoints for multi-cloud integration, FUSE mounts, and backup sync.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services.rclone_engine import get_rclone_engine

logger = logging.getLogger("ZettNAS.RemotesApi")

router = APIRouter(tags=["Remote Storage"])


class RemoteCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., min_length=1, max_length=32)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class RemoteTestRequest(BaseModel):
    type: str = Field(..., min_length=1, max_length=32)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class RemoteMountRequest(BaseModel):
    remote_path: str = ""
    vfs_cache: str = "writes"
    read_only: bool = False


class RemoteSyncRequest(BaseModel):
    src: str = Field(..., min_length=1)
    dst: str = Field(..., min_length=1)
    action: str = Field("sync", pattern="^(sync|copy|move)$")
    dry_run: bool = False
    ignore_errors: bool = False
    retries: int = 3
    verbose: bool = False
    notify: bool = True


@router.get("/remotes", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
async def list_cloud_remotes():
    """Lists all configured cloud and network storage remotes."""
    engine = get_rclone_engine()
    return await asyncio.to_thread(engine.list_remotes)


@router.get("/remotes/providers", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
async def get_storage_providers():
    """Returns curated list of cloud and network storage providers."""
    engine = get_rclone_engine()
    return engine.get_providers()


@router.post("/remotes", dependencies=[Depends(require_scope("storage:admin"))])
async def create_cloud_remote(req: RemoteCreateRequest):
    """Creates or updates a remote cloud storage backend."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(
            engine.create_remote,
            req.name,
            req.type,
            req.parameters,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remotes/test", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def test_candidate_remote(req: RemoteTestRequest):
    """Tests connectivity and credentials of a remote configuration candidate before saving."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(engine.test_remote_config, req.type, req.parameters)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remotes/{name}/test", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def test_existing_remote(name: str):
    """Tests connectivity and credentials of an existing configured remote."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(engine.test_remote, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/remotes/{name}", dependencies=[Depends(require_scope("storage:admin"))])
async def delete_cloud_remote(name: str):
    """Deletes a remote cloud storage backend."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(engine.delete_remote, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remotes/{name}/mount", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def mount_cloud_remote(name: str, req: Optional[RemoteMountRequest] = None):
    """Mounts remote cloud storage into /mnt/remotes/{name} via FUSE."""
    engine = get_rclone_engine()
    r_path = req.remote_path if req else ""
    vfs = req.vfs_cache if req else "writes"
    ro = req.read_only if req else False
    try:
        return await asyncio.to_thread(engine.mount_remote, name, r_path, vfs, ro)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remotes/{name}/unmount", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def unmount_cloud_remote(name: str):
    """Unmounts /mnt/remotes/{name}."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(engine.unmount_remote, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/remotes/{name}/files", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
async def list_remote_files(name: str, path: str = ""):
    """Lists files and folders inside a remote storage location."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(engine.list_remote_files, name, path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remotes/sync", dependencies=[Depends(require_scope("backup:write", "storage:write", "storage:admin"))])
async def start_remote_sync(req: RemoteSyncRequest):
    """Triggers an asynchronous cloud sync/copy/move operation."""
    engine = get_rclone_engine()
    try:
        return engine.start_sync_job(
            src=req.src,
            dst=req.dst,
            action=req.action,
            dry_run=req.dry_run,
            ignore_errors=req.ignore_errors,
            retries=req.retries,
            verbose=req.verbose,
            notify=req.notify,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/remotes/sync/jobs", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
async def list_sync_jobs():
    """Lists recent and active cloud sync jobs."""
    engine = get_rclone_engine()
    return engine.get_sync_jobs()


@router.get("/remotes/sync/jobs/{job_id}", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
async def get_sync_job_status(job_id: str):
    """Returns detailed real-time telemetry for a specific sync job."""
    engine = get_rclone_engine()
    job = engine.get_sync_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Sync job not found")
    return job


class OAuthStartRequest(BaseModel):
    provider_type: str = Field(..., pattern="^[a-zA-Z0-9_\\-]+$")
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class OAuthExchangeRequest(BaseModel):
    session_id: str
    redirect_url: str


_ACTIVE_OAUTH_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _cleanup_old_oauth_sessions():
    now = time.time()
    for sid, s in list(_ACTIVE_OAUTH_SESSIONS.items()):
        if now - s.get("started_at", 0) > 600:
            proc = s.get("proc")
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            _ACTIVE_OAUTH_SESSIONS.pop(sid, None)


@router.post("/remotes/oauth/start", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def start_oauth_session(req: OAuthStartRequest):
    """Initiates an OAuth authorization session via rclone authorize, capturing the cloud login URL."""
    _cleanup_old_oauth_sessions()

    rclone_bin = shutil.which("rclone") or "/usr/bin/rclone"
    if not os.path.exists(rclone_bin):
        raise HTTPException(status_code=500, detail="rclone binary not found on system.")

    cmd = [rclone_bin, "authorize", req.provider_type]
    if req.client_id and req.client_secret:
        cmd.extend([req.client_id, req.client_secret])

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start rclone authorize: {e}")

    auth_url = ""
    local_url = ""
    port = 53682
    state_param = ""

    start_t = time.time()
    raw_stderr = ""
    while time.time() - start_t < 4.0:
        if proc.poll() is not None:
            _, err = proc.communicate()
            raise HTTPException(status_code=500, detail=f"rclone authorize exited prematurely: {err}")
        try:
            line = proc.stderr.readline()
            if line:
                raw_stderr += line
                m = re.search(r"http://127\.0\.0\.1:(\d+)/auth\?state=([a-zA-Z0-9_\-]+)", line)
                if m:
                    port = int(m.group(1))
                    state_param = m.group(2)
                    local_url = m.group(0)
                    break
        except Exception:
            pass
        await asyncio.sleep(0.1)

    if not local_url:
        proc.kill()
        raise HTTPException(status_code=500, detail=f"Failed to capture OAuth listener URL from rclone: {raw_stderr}")

    try:

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(local_url)
        except urllib.error.HTTPError as e:
            auth_url = e.headers.get("Location") or ""
    except Exception as e:
        logger.warning(f"[OAuth] Could not resolve provider redirect: {e}")

    if not auth_url:
        auth_url = local_url

    session_id = f"zos_{uuid.uuid4().hex[:12]}"
    session_data = {
        "proc": proc,
        "provider_type": req.provider_type,
        "auth_url": auth_url,
        "local_url": local_url,
        "port": port,
        "state": state_param,
        "started_at": time.time(),
        "token": None,
        "error": None,
        "completed": False,
    }
    _ACTIVE_OAUTH_SESSIONS[session_id] = session_data

    def _read_stdout():
        try:
            out, err = proc.communicate(timeout=600)
            token_match = re.search(r"\{[\s\S]*\"access_token\"[\s\S]*\}", out)
            if token_match:
                session_data["token"] = token_match.group(0).strip()
                session_data["completed"] = True
            elif err:
                session_data["error"] = err
        except Exception as e:
            session_data["error"] = str(e)

    t = threading.Thread(target=_read_stdout, daemon=True)
    t.start()

    return {
        "status": "ok",
        "session_id": session_id,
        "provider_type": req.provider_type,
        "auth_url": auth_url,
        "redirect_port": port,
    }


def _resolve_onedrive_drive_details(token_json_str: str) -> tuple[str, str]:
    """Queries Microsoft Graph API to resolve drive_id and drive_type."""
    try:
        tok = json.loads(token_json_str) if isinstance(token_json_str, str) else token_json_str
        acc = tok.get("access_token")
        if not acc:
            return "", "personal"
        req = urllib.request.Request(
            "https://graph.microsoft.com/v1.0/me/drive",
            headers={"Authorization": f"Bearer {acc}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("id", ""), data.get("driveType", "personal")
    except Exception as e:
        logger.warning(f"[OAuth] Could not query Microsoft Graph for drive details: {e}")
    return "", "personal"


@router.post("/remotes/oauth/exchange", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def exchange_oauth_code(req: OAuthExchangeRequest):
    """Receives redirected URL or code, forwards it to rclone's loopback listener, and returns JSON token."""
    session = _ACTIVE_OAUTH_SESSIONS.get(req.session_id)
    if not session:
        raise HTTPException(
            status_code=404, detail="OAuth authorization session expired or not found. Please restart authentication."
        )

    port = session.get("port", 53682)
    state = session.get("state", "")

    code = ""
    req_state = state
    raw_url = req.redirect_url.strip()

    if "?" in raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            code = params["code"][0]
        if "state" in params:
            req_state = params["state"][0]
    elif "&" in raw_url or "code=" in raw_url:
        params = urllib.parse.parse_qs(raw_url)
        if "code" in params:
            code = params["code"][0]
        if "state" in params:
            req_state = params["state"][0]
    else:
        code = raw_url

    if not code:
        raise HTTPException(status_code=400, detail="Could not find 'code' parameter in provided URL.")

    fwd_url = f"http://127.0.0.1:{port}/?code={urllib.parse.quote(code)}&state={urllib.parse.quote(req_state)}"
    try:
        await asyncio.to_thread(lambda: urllib.request.urlopen(fwd_url, timeout=5))
    except Exception as e:
        logger.info(f"[OAuth] Forwarding to local rclone completed with: {e}")

    for _ in range(25):
        if session.get("completed") and session.get("token"):
            drive_id, drive_type = "", "personal"
            if session.get("provider_type") == "onedrive":
                drive_id, drive_type = _resolve_onedrive_drive_details(session["token"])
            return {
                "status": "ok",
                "token": session["token"],
                "drive_id": drive_id,
                "drive_type": drive_type or "personal",
                "session_id": req.session_id,
            }
        if session.get("error"):
            raise HTTPException(status_code=400, detail=f"Authentication failed: {session['error']}")
        await asyncio.sleep(0.2)

    if session.get("token"):
        drive_id, drive_type = "", "personal"
        if session.get("provider_type") == "onedrive":
            drive_id, drive_type = _resolve_onedrive_drive_details(session["token"])
        return {
            "status": "ok",
            "token": session["token"],
            "drive_id": drive_id,
            "drive_type": drive_type or "personal",
            "session_id": req.session_id,
        }

    raise HTTPException(status_code=504, detail="Timed out waiting for Microsoft/Google token exchange.")


@router.get(
    "/remotes/oauth/status/{session_id}", dependencies=[Depends(require_scope("storage:admin", "storage:write"))]
)
async def get_oauth_session_status(session_id: str):
    session = _ACTIVE_OAUTH_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session expired or not found")
    drive_id, drive_type = "", "personal"
    if session.get("completed") and session.get("token") and session.get("provider_type") == "onedrive":
        drive_id, drive_type = _resolve_onedrive_drive_details(session["token"])
    return {
        "session_id": session_id,
        "completed": bool(session.get("completed")),
        "token": session.get("token"),
        "drive_id": drive_id,
        "drive_type": drive_type or "personal",
        "error": session.get("error"),
    }


@router.delete("/remotes/oauth/{session_id}", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def cancel_oauth_session(session_id: str):
    session = _ACTIVE_OAUTH_SESSIONS.pop(session_id, None)
    if session:
        proc = session.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
    return {"status": "ok"}
