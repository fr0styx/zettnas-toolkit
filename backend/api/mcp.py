"""
Model Context Protocol server (D1): lets AI clients such as Claude Desktop, Cursor or
Open WebUI use Ask Zetty's tools.

Streamable HTTP transport, JSON responses: POST /api/mcp with JSON-RPC 2.0. It
authenticates like the REST API (an API token as `Authorization: Bearer …`), offers
only the tools that account may run (the same registry and policy as the chat), and
never web tools. Tools that change the system are not run: the call returns a link to
confirm the action in ZettNAS, so a person always decides. Every call is written to the
security audit log.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from backend import __version__
from backend.auth import AuthenticatedPrincipal, get_current_principal

router = APIRouter(tags=["MCP"])
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def _result(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _mcp_tools(principal: Any) -> list[dict[str, Any]]:
    from backend.services.ai_chat_agent import TOOL_REGISTRY

    out = []
    for d in TOOL_REGISTRY.for_principal(principal, web_allowed=False):
        fn = d["function"]
        tool = TOOL_REGISTRY.get(fn["name"])
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", "")
                + (
                    " Changes the system: returns a link for the user to confirm in ZettNAS."
                    if tool and tool.mutating
                    else ""
                ),
                "inputSchema": fn.get("parameters") or {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": not (tool and tool.mutating), "openWorldHint": False},
            }
        )
    return out


def _call_tool(name: str, args: dict[str, Any], principal: Any, base_url: str) -> dict[str, Any]:
    from backend.services.ai_chat_agent import execute_nas_tool

    res = execute_nas_tool(name, args, principal=principal, confirmed=False, source="mcp")
    if res.get("status") == "confirmation_required":
        link = f"{base_url}/?confirm-action={res['action_id']}"
        text = f"Not run yet: '{res.get('summary', name)}' needs confirmation. Ask the user to open {link} and click Confirm."
        return {"content": [{"type": "text", "text": text}], "isError": False}
    if res.get("status") in ("forbidden", "blocked", "error"):
        return {"content": [{"type": "text", "text": res.get("error") or res.get("status")}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(res, default=str, ensure_ascii=False)}], "isError": False}


def handle_message(msg: Any, principal: Any, base_url: str) -> dict[str, Any] | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid request")
    method, req_id, params = msg["method"], msg.get("id"), msg.get("params") or {}
    if "id" not in msg:
        return None  # a notification, e.g. notifications/initialized
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(
            req_id,
            {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "zettnas", "title": "ZettNAS", "version": __version__},
                "instructions": "Tools that change the NAS return a link; the user confirms them in ZettNAS.",
            },
        )
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": _mcp_tools(principal)})
    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(req_id, -32602, "arguments must be an object")
        if name not in {t["name"] for t in _mcp_tools(principal)}:
            return _error(req_id, -32602, f"Unknown or not allowed tool: {name}")
        return _result(req_id, _call_tool(name, args, principal, base_url))
    return _error(req_id, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_endpoint(request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    import asyncio

    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    base = str(request.base_url).rstrip("/")
    if isinstance(body, list):
        replies = [r for r in [await asyncio.to_thread(handle_message, m, principal, base) for m in body] if r]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await asyncio.to_thread(handle_message, body, principal, base)
    return JSONResponse(reply) if reply else Response(status_code=202)


@router.get("/mcp")
async def mcp_no_stream():
    # No server-initiated messages: the spec allows 405 here
    return Response(status_code=405, headers={"Allow": "POST"})
