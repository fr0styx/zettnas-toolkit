"""Each family member's own way in from outside (NFEAT-1): the owner's card and the invite page."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise
from backend.rate_limit import rate_limit
from backend.services import family_access

router = APIRouter(tags=["Network"])


def _actor(principal: AuthenticatedPrincipal) -> str:
    return getattr(principal, "username", "") or ""


# the invite links and people's Tailscale sign-in names: for someone who may change settings (SET-02)
@router.get("/network/family-access", dependencies=[Depends(require_scope("system:config"))])
async def get_family_access() -> dict[str, Any]:
    """Who was invited, who joined and who is online; whether a Tailscale API key is kept and how long it lasts."""
    await asyncio.to_thread(family_access.refresh)
    return await asyncio.to_thread(family_access.status)


class KeyIn(BaseModel):
    key: str = Field(min_length=10, max_length=200)


@router.put("/network/family-access/key", dependencies=[Depends(require_scope("system:config"))])
async def put_family_key(
    req: KeyIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Checks a Tailscale API access key against this machine, then keeps it sealed."""
    try:
        return await asyncio.to_thread(family_access.save_key, req.key, _actor(principal))
    except family_access.FamilyAccessError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.delete("/network/family-access/key", dependencies=[Depends(require_scope("system:config"))])
async def delete_family_key(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """Forgets the Tailscale API key; invites already made keep working."""
    return await asyncio.to_thread(family_access.forget_key, _actor(principal))


class InviteIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)


@router.post("/network/family-access/invites", dependencies=[Depends(require_scope("system:config"))])
async def post_family_invite(
    req: InviteIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """A single-use invite to reach this NAS (and nothing else) from anywhere (confirmed first: 428 until then)."""
    from backend.users_db import get_user_by_id

    user = get_user_by_id(req.user_id)
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=404, detail="No active Kiboto user with that id.")
    confirm_or_raise(request, principal, "network.family_invite", str(user.get("username") or ""))
    name = str(user.get("display_name") or user.get("username") or "")
    try:
        return await asyncio.to_thread(
            family_access.invite, req.user_id, str(user.get("username") or ""), name, _actor(principal)
        )
    except family_access.FamilyAccessError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.delete("/network/family-access/invites/{user_id}", dependencies=[Depends(require_scope("system:config"))])
async def delete_family_invite(
    user_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Withdraws the person's invite; for one already accepted, says where to remove the share in Tailscale."""
    try:
        return await asyncio.to_thread(family_access.revoke, user_id, _actor(principal))
    except KeyError:
        raise HTTPException(status_code=404, detail="That person has no invite.") from None


_SCRIPT = r"""
const box = document.getElementById('join');
const ua = navigator.userAgent;
const kind = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ? 'ios'
  : /Android/.test(ua) ? 'android' : /Windows/.test(ua) ? 'windows' : /Macintosh/.test(ua) ? 'mac' : 'other';
for (const a of document.querySelectorAll('[data-store]')) a.hidden = a.dataset.store !== kind && !(kind === 'other' && a.dataset.store === 'other');
async function check() {
  try {
    const r = await fetch(box.dataset.token + '/state', { cache: 'no-store' });
    if (r.ok && (await r.json()).accepted) { box.classList.add('done'); return; }
  } catch (e) { /* offline for a moment */ }
  setTimeout(check, 5000);
}
if (!box.classList.contains('done')) setTimeout(check, 5000);
"""
_SCRIPT_HASH = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()
CSP = (
    f"default-src 'none'; script-src 'sha256-{_SCRIPT_HASH}'; style-src 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
)
STORES = {
    "ios": ("App Store", "https://apps.apple.com/app/tailscale/id1470499037"),
    "android": ("Google Play", "https://play.google.com/store/apps/details?id=com.tailscale.ipn"),
    "windows": ("Windows", "https://tailscale.com/download/windows"),
    "mac": ("Mac App Store", "https://apps.apple.com/app/tailscale/id1475387142"),
    "other": ("tailscale.com", "https://tailscale.com/download"),
}
_STYLE = """body{font-family:system-ui,sans-serif;background:#0b0f14;color:#e5e7eb;margin:0;display:flex;
min-height:100vh;align-items:center;justify-content:center}main{background:#111827;border-radius:14px;padding:24px;
width:min(440px,92vw);box-sizing:border-box}h1{font-size:20px;margin:0 0 6px}p{color:#9ca3af;margin:0 0 16px}
ol{list-style:none;padding:0;margin:0}li{display:flex;gap:12px;margin:0 0 16px;align-items:flex-start}
li b{flex:0 0 28px;height:28px;border-radius:50%;background:#0ea5e9;color:#fff;display:flex;align-items:center;
justify-content:center}a.btn{display:block;text-align:center;background:#0ea5e9;color:#fff;text-decoration:none;
padding:12px;border-radius:10px;margin-top:8px;font-weight:600}a.alt{color:#9ca3af;font-size:13px}
[hidden]{display:none!important}.after{display:none}.done .before{display:none}.done .after{display:block}small{color:#9ca3af}"""


def _page(token: str, info: dict[str, Any]) -> Response:
    esc = html.escape
    stores = "".join(
        f'<a class="btn" data-store="{k}" href="{esc(url)}" target="_blank" rel="noopener">Get Tailscale ({esc(label)})</a>'
        for k, (label, url) in STORES.items()
    )
    open_kiboto = (
        f'<a class="btn" href="{esc(info["kiboto_url"])}">Open Kiboto</a>'
        if info["kiboto_url"]
        else "<small>Ask the person who invited you for Kiboto's address.</small>"
    )
    accept = (
        f'<a class="btn" href="{esc(info["invite_url"])}" target="_blank" rel="noopener">Accept the invite</a>'
        if info["invite_url"]
        else ""
    )
    done = " done" if info["accepted"] else ""
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>Join Kiboto</title>
<style>{_STYLE}</style></head><body><main id="join" class="{done.strip()}" data-token="{esc(token)}">
<h1>Hi {esc(info["name"])}, you're invited</h1>
<div class="before"><p>Three steps and your family's Kiboto opens on this device from anywhere.
It's free, and you'll only see Kiboto, nothing else on their network.</p><ol>
<li><b>1</b><div>Install the Tailscale app.{stores}</div></li>
<li><b>2</b><div>Open it and sign in with your Google, Apple or Microsoft account (or make a Tailscale account).</div></li>
<li><b>3</b><div>Come back here and accept.{accept}<br><small>This page notices when you're in.</small></div></li>
</ol></div>
<div class="after"><p>You're in. Keep the Tailscale app connected, then open Kiboto and sign in with the name
and password you were given.</p>{open_kiboto}<p><small>Tip: add Kiboto to your home screen from the browser's
Share or menu button.</small></p></div>
</main><script>{_SCRIPT}</script></body></html>"""
    return Response(
        content=body,
        media_type="text/html",
        headers={"Content-Security-Policy": CSP, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


_GONE = (
    "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>Invite</title><p style='font-family:system-ui;padding:24px'>This invite has expired or was "
    "withdrawn. Ask for a new one.</p>"
)


@router.get("/fs/shared/join/{token}", dependencies=[Depends(rate_limit("family.join", 60, 60, per="ip"))])
async def family_join_page(token: str) -> Response:
    """The invite page a family member opens: get the Tailscale app, sign in, accept (public; the token is the credential)."""
    info = await asyncio.to_thread(family_access.page_info, token)
    if info is None:
        return Response(
            content=_GONE, media_type="text/html", status_code=404, headers={"Content-Security-Policy": CSP}
        )
    return _page(token, info)


@router.get("/fs/shared/join/{token}/state", dependencies=[Depends(rate_limit("family.join", 60, 60, per="ip"))])
async def family_join_state(token: str) -> Response:
    """Whether the invite was accepted yet (the page asks every few seconds)."""
    await asyncio.to_thread(family_access.refresh)
    info = await asyncio.to_thread(family_access.page_info, token)
    if info is None:
        raise HTTPException(status_code=404, detail="This invite has expired or was withdrawn.")
    return Response(content=json.dumps({"accepted": info["accepted"]}), media_type="application/json")
