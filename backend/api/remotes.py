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
from fastapi.responses import HTMLResponse
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


def _cleanup_old_oauth_sessions(force_all: bool = False):
    now = time.time()
    for sid, s in list(_ACTIVE_OAUTH_SESSIONS.items()):
        if force_all or (now - s.get("started_at", 0) > 600):
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
    _cleanup_old_oauth_sessions(force_all=True)

    # Force release of loopback port 53682 if any orphan rclone authorize processes exist
    try:
        await asyncio.to_thread(
            lambda: subprocess.run(["pkill", "-9", "-f", "rclone authorize"], capture_output=True, timeout=2)
        )
    except Exception:
        pass
    await asyncio.sleep(0.15)

    rclone_bin = shutil.which("rclone") or "/usr/bin/rclone"
    if not os.path.exists(rclone_bin):
        raise HTTPException(status_code=500, detail="rclone binary not found on system.")

    cmd = [rclone_bin, "authorize", "--auth-no-open-browser", req.provider_type]
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


async def _execute_code_exchange(session_id: str, redirect_url: str) -> Dict[str, Any]:
    """Helper that forwards redirect code to rclone loopback listener and waits for token resolution."""
    session = _ACTIVE_OAUTH_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(
            status_code=404, detail="OAuth authorization session expired or not found. Please restart authentication."
        )

    port = session.get("port", 53682)
    state = session.get("state", "")

    code = ""
    req_state = state
    raw_url = redirect_url.strip()

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
                "session_id": session_id,
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
            "session_id": session_id,
        }

    raise HTTPException(status_code=504, detail="Timed out waiting for Microsoft/Google token exchange.")


@router.post("/remotes/oauth/exchange", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def exchange_oauth_code(req: OAuthExchangeRequest):
    """Receives redirected URL or code, forwards it to rclone's loopback listener, and returns JSON token."""
    return await _execute_code_exchange(req.session_id, req.redirect_url)


@router.post("/remotes/oauth/mobile-exchange")
async def mobile_exchange_oauth_code(req: OAuthExchangeRequest):
    """Allows a mobile phone scanning the QR code to submit authorization code to the active session."""
    return await _execute_code_exchange(req.session_id, req.redirect_url)


@router.get("/remotes/oauth/mobile-page", response_class=HTMLResponse)
async def get_mobile_oauth_page(sid: str):
    """Serves a mobile-optimized authorization companion page when scanning the QR code."""
    session = _ACTIVE_OAUTH_SESSIONS.get(sid)
    if not session:
        return HTMLResponse(
            content="""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ZettNAS - Session Expired</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #090d16; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
        .card { background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 28px; max-width: 420px; width: 100%; text-align: center; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
        h2 { color: #f87171; margin-top: 0; font-size: 20px; }
        p { color: #94a3b8; line-height: 1.6; font-size: 14px; margin-bottom: 0; }
    </style>
</head>
<body>
    <div class="card">
        <h2>⚠️ Session Expired</h2>
        <p>This authorization session has expired or was already completed. Please click <strong>Refresh</strong> on your desktop screen to generate a new QR code.</p>
    </div>
</body>
</html>""",
            status_code=404,
        )

    provider = session.get("provider_type", "cloud")
    provider_name = (
        "Microsoft OneDrive"
        if provider == "onedrive"
        else ("Google Drive" if provider == "drive" else provider.capitalize())
    )
    auth_url = session.get("auth_url", "")
    safe_auth_url = auth_url.replace('"', "&quot;")
    safe_sid = urllib.parse.quote(sid)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ZettNAS - Connect {provider_name}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: #090d16;
            color: #f1f5f9;
            padding: 24px 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            padding: 26px 20px;
            max-width: 440px;
            width: 100%;
            box-shadow: 0 20px 40px rgba(0,0,0,0.6);
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 16px;
        }}
        .brand-badge {{
            background: linear-gradient(135deg, #0284c7, #0369a1);
            color: white;
            font-size: 11px;
            font-weight: 800;
            padding: 3px 8px;
            border-radius: 5px;
            letter-spacing: 0.5px;
        }}
        h1 {{
            font-size: 19px;
            margin-bottom: 6px;
            font-weight: 700;
        }}
        p.subtitle {{
            font-size: 13px;
            color: #94a3b8;
            margin-bottom: 20px;
            line-height: 1.5;
        }}
        .step {{
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 14px;
            margin-bottom: 14px;
        }}
        .step-title {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12.5px;
            font-weight: 700;
            color: #e2e8f0;
            margin-bottom: 10px;
        }}
        .step-num {{
            background: #0284c7;
            color: white;
            font-size: 10px;
            font-weight: 800;
            padding: 2px 7px;
            border-radius: 8px;
        }}
        .btn {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            width: 100%;
            padding: 13px;
            border-radius: 8px;
            font-size: 13.5px;
            font-weight: 700;
            border: none;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
            color: white;
            box-shadow: 0 4px 14px rgba(2, 132, 199, 0.4);
        }}
        .btn-success {{
            background: #22c55e;
            color: white;
            box-shadow: 0 4px 14px rgba(34, 197, 94, 0.4);
        }}
        .btn-secondary {{
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: white;
            padding: 10px 14px;
            font-size: 12px;
        }}
        .hint {{
            font-size: 11.5px;
            color: #94a3b8;
            margin-top: 8px;
            line-height: 1.45;
        }}
        .input-row {{
            display: flex;
            gap: 6px;
            margin-top: 8px;
        }}
        input.text-input {{
            flex: 1;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: white;
            padding: 11px 12px;
            border-radius: 8px;
            font-size: 12px;
            font-family: monospace;
            outline: none;
        }}
        input.text-input:focus {{
            border-color: #0284c7;
        }}
        #status-box {{
            display: none;
            padding: 12px;
            border-radius: 8px;
            font-size: 12.5px;
            line-height: 1.45;
            margin-top: 14px;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="brand">
            <span class="brand-badge">ZETTNAS</span>
            <span style="font-size: 12px; color: #64748b; font-weight: 600;">Mobile Remote Auth</span>
        </div>
        <h1>Connect {provider_name}</h1>
        <p class="subtitle">Complete sign-in on this device to automatically link your cloud remote on your NAS desktop.</p>

        <!-- Step 1 -->
        <div class="step">
            <div class="step-title">
                <span class="step-num">Step 1</span>
                <span>Sign in & Authorize:</span>
            </div>
            <a href="{safe_auth_url}" target="_blank" class="btn btn-primary" id="btn-login">
                <span>🌐 Sign In with {provider_name}</span>
            </a>
            <div class="hint">
                📌 When sign-in completes, the browser will say <em>"This site can't be reached (localhost:53682)"</em>. <strong>This is normal!</strong>
            </div>
        </div>

        <!-- Step 2 -->
        <div class="step">
            <div class="step-title">
                <span class="step-num">Step 2</span>
                <span>Paste address bar from that tab:</span>
            </div>
            <div class="input-row">
                <input type="text" id="url-input" class="text-input" placeholder="http://localhost:53682/?code=..." />
                <button type="button" class="btn btn-secondary" id="btn-paste" style="width: auto;">📋 Paste</button>
            </div>
            <div style="margin-top: 12px;">
                <button type="button" class="btn btn-success" id="btn-submit">
                    <span>🚀 Submit to NAS</span>
                </button>
            </div>
        </div>

        <div id="status-box"></div>
    </div>

    <script>
        const sid = "{safe_sid}";
        const urlInput = document.getElementById('url-input');
        const pasteBtn = document.getElementById('btn-paste');
        const submitBtn = document.getElementById('btn-submit');
        const statusBox = document.getElementById('status-box');

        pasteBtn.onclick = async () => {{
            try {{
                if (navigator.clipboard && navigator.clipboard.readText) {{
                    const text = await navigator.clipboard.readText();
                    if (text && text.trim()) {{
                        urlInput.value = text.trim();
                        return;
                    }}
                }}
            }} catch(_) {{}}
            const m = prompt('Paste redirect URL here:');
            if (m && m.trim()) urlInput.value = m.trim();
        }};

        submitBtn.onclick = async () => {{
            const raw = urlInput.value.trim();
            if (!raw) {{
                alert('Please paste the redirect URL first.');
                return;
            }}
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span>⏳ Sending to NAS...</span>';
            statusBox.style.display = 'block';
            statusBox.style.background = 'rgba(14, 165, 233, 0.15)';
            statusBox.style.border = '1px solid rgba(14, 165, 233, 0.3)';
            statusBox.style.color = '#38bdf8';
            statusBox.innerHTML = '🔄 Exchanging authorization code with NAS...';

            try {{
                const res = await fetch('/api/remotes/oauth/mobile-exchange', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ session_id: sid, redirect_url: raw }})
                }});
                const data = await res.json();
                if (res.ok && data.status === 'ok') {{
                    statusBox.style.background = 'rgba(34, 197, 94, 0.2)';
                    statusBox.style.border = '1px solid rgba(34, 197, 94, 0.4)';
                    statusBox.style.color = '#4ade80';
                    statusBox.innerHTML = '✅ <strong>Successfully Connected!</strong><br>Credentials sent to your ZettNAS desktop. You can now close this tab.';
                    submitBtn.style.display = 'none';
                }} else {{
                    throw new Error(data.detail || data.error || 'Exchange failed');
                }}
            }} catch (err) {{
                statusBox.style.background = 'rgba(239, 68, 68, 0.2)';
                statusBox.style.border = '1px solid rgba(239, 68, 68, 0.4)';
                statusBox.style.color = '#f87171';
                statusBox.innerHTML = '❌ ' + (err.message || 'Error sending code to NAS');
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<span>🚀 Submit to NAS</span>';
            }}
        }};
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


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
