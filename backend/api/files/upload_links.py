"""'Send me files' links (NFEAT-2): someone without an account drops files into one folder.

A share link of kind "upload" on a folder. Its page (under /api/fs/shared, so public links reach it
through Funnel too) has a file picker and nothing else: the folder's contents are never listed or
served. Each file is streamed to disk (no temporary copy elsewhere) as a hidden part file, then
gets its own name, never overwriting one that is there. Limits: the link's total size, enough free
disk, a per-address rate, its expiry and password like any share link, and the person who made it
must still be able to write to the folder. Each file that arrives is noted in the activity log.
"""

import asyncio
import base64
import hashlib
import html
import os
import re
import secrets
import shutil
import time
from typing import Any
from urllib.parse import unquote

import aiofiles
from fastapi import HTTPException, Request
from fastapi.responses import Response

from backend.config import logger

DEFAULT_LIMIT_MB = 5 * 1024
FREE_MARGIN = 1024**3  # leave at least this much free on the disk
CHUNK = 1 << 20

_SCRIPT = r"""
const page = document.getElementById('drop');
const pick = document.getElementById('files');
const pw = document.getElementById('pw');
const list = document.getElementById('list');
const token = page.dataset.token;
function row(name) {
  const li = document.createElement('li');
  li.textContent = name + ' … ';
  const s = document.createElement('span');
  li.append(s);
  list.append(li);
  return s;
}
function send(file) {
  return new Promise((done) => {
    const state = row(file.name);
    const x = new XMLHttpRequest();
    x.open('POST', token + '/upload');
    x.setRequestHeader('X-File-Name', encodeURIComponent(file.name));
    if (pw && pw.value) x.setRequestHeader('X-Share-Password', pw.value);
    x.upload.onprogress = (e) => { if (e.lengthComputable) state.textContent = Math.round(100 * e.loaded / e.total) + '%'; };
    x.onload = () => {
      let msg = 'sent';
      if (x.status !== 200) { try { msg = JSON.parse(x.responseText).detail; } catch (err) { msg = 'failed (' + x.status + ')'; } }
      state.textContent = msg;
      done();
    };
    x.onerror = () => { state.textContent = 'failed: the connection dropped'; done(); };
    x.send(file);
  });
}
async function sendAll(files) { for (const f of files) await send(f); pick.value = ''; }
pick.addEventListener('change', () => sendAll([...pick.files]));
page.addEventListener('dragover', (e) => { e.preventDefault(); page.classList.add('over'); });
page.addEventListener('dragleave', () => page.classList.remove('over'));
page.addEventListener('drop', (e) => { e.preventDefault(); page.classList.remove('over'); sendAll([...e.dataTransfer.files]); });
"""
_SCRIPT_HASH = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()
CSP = (
    f"default-src 'none'; script-src 'sha256-{_SCRIPT_HASH}'; style-src 'unsafe-inline'; "
    "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
)


def page(token: str, item: dict[str, Any]) -> Response:
    """The drop page: who asks, the limit, a password field when the link has one."""
    label = html.escape(str(item.get("label") or "a folder"))
    limit = int(item.get("max_upload_mb") or DEFAULT_LIMIT_MB)
    pw = '<input type="password" id="pw" autocomplete="off" placeholder="Password">' if item.get("has_password") else ""
    body = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>Send files</title><style>body{{font-family:system-ui;background:#0b0f14;
color:#e5e7eb;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}#drop{{background:#111827;
padding:24px;border-radius:12px;width:min(420px,90vw);border:2px dashed #374151}}#drop.over{{border-color:#0ea5e9}}
input{{width:100%;box-sizing:border-box;padding:10px;margin-top:10px;border-radius:8px;border:1px solid #374151;
background:#0b0f14;color:#fff}}small{{color:#9ca3af}}ul{{padding-left:18px;word-break:break-all}}</style></head><body>
<main id="drop" data-token="{html.escape(token)}"><div>Send files to <strong>{label}</strong>.</div>
<small>Choose files or drop them here. You can't see what is in the folder. Up to {limit:,} MB in all.</small>
{pw}<input type="file" id="files" multiple><ul id="list"></ul></main><script>{_SCRIPT}</script></body></html>"""
    return Response(
        content=body,
        media_type="text/html",
        headers={"Content-Security-Policy": CSP, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def safe_name(raw: str) -> str:
    """The sender's file name as a plain name in the folder: no path, no control characters, not
    hidden, not one of Kiboto's own part files."""
    name = unquote(raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if name.startswith((".", "~")):
        name = "_" + name.lstrip(".~")
    name = name.rstrip(". ")  # Windows can't open a name ending in a dot or a space
    if name in ("", "_"):
        name = "file"
    return name[:200]


def unique_path(folder: str, name: str) -> str:
    stem, ext = os.path.splitext(name)
    for n in range(1, 10000):
        candidate = os.path.join(folder, name if n == 1 else f"{stem} ({n}){ext}")
        if not os.path.lexists(candidate):
            return candidate
    raise HTTPException(status_code=409, detail="Too many files with that name.")


async def receive(item: dict[str, Any], folder: str, request: Request) -> tuple[str, int]:
    """Streams the request body into the folder; returns (the name it got, its size)."""
    declared = request.headers.get("content-length")
    if not declared or not declared.isdigit():
        raise HTTPException(status_code=411, detail="The upload needs its size (Content-Length).")
    size = int(declared)
    left = int(item.get("max_upload_mb") or DEFAULT_LIMIT_MB) * 1024**2 - int(item.get("received_bytes") or 0)
    if size > left:
        raise HTTPException(status_code=413, detail="This link has no room left for that file.")
    free = await asyncio.to_thread(lambda: shutil.disk_usage(folder).free)
    if size + FREE_MARGIN > free:
        raise HTTPException(status_code=507, detail="The NAS doesn't have room for that file.")
    name = safe_name(request.headers.get("x-file-name") or "")
    part = os.path.join(folder, f".zn-upload-{secrets.token_hex(6)}.part")
    written = 0
    try:
        async with aiofiles.open(part, "wb") as f:
            async for chunk in request.stream():
                written += len(chunk)
                if written > size:
                    raise HTTPException(status_code=400, detail="The file was bigger than it said.")
                await f.write(chunk)
        if written != size:
            raise HTTPException(status_code=400, detail="The upload stopped before the end.")
        final = await asyncio.to_thread(unique_path, folder, name)
        await asyncio.to_thread(os.replace, part, final)
        part = ""
        return os.path.basename(final), written
    finally:
        if part and await asyncio.to_thread(os.path.exists, part):
            await asyncio.to_thread(os.remove, part)


def note(item: dict[str, Any], name: str, size: int, ip: str) -> None:
    from backend.state import add_event

    label = item.get("label") or os.path.basename(str(item.get("path") or ""))
    add_event("info", "Files received", f"{name} ({size:,} bytes) arrived in {label} through a send-me-files link")
    logger.info("[UploadLink] %s (%s bytes) into %s from %s", name, size, label, ip)


def counted(item: dict[str, Any], size: int) -> dict[str, Any]:
    item["received_bytes"] = int(item.get("received_bytes") or 0) + size
    item["received_count"] = int(item.get("received_count") or 0) + 1
    item["last_received_at"] = time.time()
    return item
