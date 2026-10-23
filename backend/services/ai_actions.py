"""
Click-to-confirm for ZettAI actions that change the system (AI-01).

The chat agent never runs a mutating tool on its own, whether a regex,
a "yes, do it" follow-up or the model picked it. It returns a proposal
instead; the action runs only when the same user clicks Confirm in the
chat, which calls confirm_action().
"""

import secrets
import threading
import time
from typing import Any, Optional

MUTATING_TOOLS = frozenset({"control_docker_container", "set_fan_profile", "trigger_ai_sync"})
PROPOSAL_TTL_SECS = 10 * 60
_MAX_PENDING = 500

_pending: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _principal_id(principal: Any) -> str:
    return str(getattr(principal, "user_id", "") or getattr(principal, "username", "") or "").strip().lower()


def describe(tool: str, args: dict[str, Any]) -> str:
    if tool == "control_docker_container":
        name = str(args.get("container") or args.get("container_name") or args.get("name") or "").strip()
        act = str(args.get("action") or "restart").strip().lower()
        return f"{act.capitalize()} container '{name}'"
    if tool == "set_fan_profile":
        prof = args.get("profile") or args.get("fan_profile") or args.get("new_profile") or "auto"
        return f"Switch fan profile to '{prof}'"
    if tool == "trigger_ai_sync":
        return f"{str(args.get('action') or 'start').capitalize()} AI sync"
    return tool


def propose_action(tool: str, args: dict[str, Any] | None, principal: Any) -> dict[str, Any]:
    args = dict(args or {})
    summary = describe(tool, args)
    owner = _principal_id(principal)
    if not owner:
        return {"tool": tool, "status": "blocked", "error": "Sign in to run actions from the assistant."}

    now = time.time()
    action_id = secrets.token_urlsafe(16)
    with _lock:
        for key in [k for k, v in _pending.items() if now - v["created_at"] > PROPOSAL_TTL_SECS]:
            del _pending[key]
        if len(_pending) >= _MAX_PENDING:
            oldest = min(_pending, key=lambda k: _pending[k]["created_at"])
            del _pending[oldest]
        _pending[action_id] = {"tool": tool, "args": args, "owner": owner, "created_at": now}

    return {
        "tool": tool,
        "status": "confirmation_required",
        "action_id": action_id,
        "summary": summary,
        "args": args,
        "message": f"NOT executed yet: '{summary}' needs the user to click Confirm in the chat.",
    }


def confirm_action(action_id: str, principal: Any) -> dict[str, Any]:
    """Runs a proposed action once, for the user it was proposed to, within the TTL."""
    owner = _principal_id(principal)
    raw = getattr(principal, "raw_data", None) or {}
    if (
        getattr(principal, "is_api_token", False)
        or getattr(principal, "is_system", False)
        or raw.get("is_stream_ticket")
        or raw.get("is_console_ticket")
    ):
        # A person confirms in ZettNAS; the token or ticket that proposed it cannot.
        return {"status": "not_found", "error": "Confirm this action in ZettNAS while signed in."}
    with _lock:
        entry = _pending.get(action_id)
        if not entry or not owner or entry["owner"] != owner:
            return {"status": "not_found", "error": "This action has expired or isn't yours."}
        del _pending[action_id]
    if time.time() - entry["created_at"] > PROPOSAL_TTL_SECS:
        return {"status": "not_found", "error": "This action has expired. Ask again."}

    from backend.services.ai_chat_agent import execute_nas_tool

    result = execute_nas_tool(entry["tool"], entry["args"], principal=principal, confirmed=True)
    result.setdefault("tool", entry["tool"])
    result["summary"] = describe(entry["tool"], entry["args"])
    return result


def pending_summary(action_id: str, principal: Any) -> dict[str, Any] | None:
    """What a pending action would do, for its owner only (confirm links from MCP, D1)."""
    owner = _principal_id(principal)
    with _lock:
        entry = _pending.get(action_id)
    if not entry or not owner or entry["owner"] != owner or time.time() - entry["created_at"] > PROPOSAL_TTL_SECS:
        return None
    return {"action_id": action_id, "tool": entry["tool"], "summary": describe(entry["tool"], entry["args"])}


def _reset_for_tests() -> None:
    with _lock:
        _pending.clear()
