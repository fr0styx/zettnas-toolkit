"""Which tools a person may use, their schemas, running them and the audit trail (split out of ai_chat_agent.py, ARCH-1)."""

import json
import re
from typing import (  # noqa: F401
    Any,
)

from backend.config import (  # noqa: F401
    logger,
)
from backend.services.chat_context import (  # noqa: F401
    _grounding_label,
)


def _core():
    """backend.services.ai_chat_agent, read at call time: it holds the shared state, and tests patch names there."""
    from backend.services import ai_chat_agent

    return ai_chat_agent


def _safe_parse_tool_call_json(raw_args: Any) -> dict[str, Any]:
    """
    Robust multi-stage JSON parser with fuzzy repair for Small Language Models (SLMs).
    Strips markdown code blocks, removes trailing commas, fixes single quotes,
    and extracts outermost JSON objects.
    """
    if isinstance(raw_args, dict):
        return raw_args
    if not isinstance(raw_args, str) or not raw_args.strip():
        return {}
    s = raw_args.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:
        logger.debug("backend.services.ai_chat_agent._safe_parse_tool_call_json: ignored error", exc_info=True)
    # Strip trailing commas before } or ]
    s_fixed = re.sub(r",\s*([}\]])", r"\1", s)
    try:
        return json.loads(s_fixed)
    except Exception:
        logger.debug("backend.services.ai_chat_agent._safe_parse_tool_call_json: ignored error", exc_info=True)
    # Extract outermost JSON object if wrapped in explanatory prose
    match = re.search(r"(\{.*\})", s_fixed, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            logger.debug("backend.services.ai_chat_agent._safe_parse_tool_call_json: ignored error", exc_info=True)
    return {}


def _has_write_permission(principal: Any, required_scopes: tuple[str, ...]) -> bool:
    """No principal means no write access; scopes use the same wildcard rules as the API."""
    if principal is None:
        return False
    # Effective scopes only: an API token gets what it was given, not its owner's role.
    from backend.auth import has_scope

    scopes = list(getattr(principal, "scopes", None) or [])
    return any(has_scope(scopes, s) for s in required_scopes)


def tool_allowed(tool_name: str, principal: Any) -> bool:
    """Whether this user may have the AI run this tool. Unknown tools are refused."""
    return _core().TOOL_REGISTRY.allowed(tool_name, principal)


def tools_for_principal(principal: Any, web_allowed: bool) -> list[dict[str, Any]]:
    """The tool definitions offered to the model: only what this user may run (AI-04)."""
    return _core().TOOL_REGISTRY.for_principal(principal, web_allowed)


def _is_math_or_calculation_query(text: str) -> bool:
    clean = str(text or "").strip().lower().rstrip("?.! ")
    if re.search(r"\d+\s*%\s*(?:of|\*)\s*\d+", clean):
        return True
    stripped = re.sub(
        r"^(?:what(?:'s|s|\s+is)?|calculate|compute|solve|how\s+much\s+is|evaluate|can\s+you\s+calculate|please\s+calculate)\s+",
        "",
        clean,
    ).strip()
    if (
        re.match(r"^[\d\s+\-*/%^().,x÷]+$", stripped)
        and re.search(r"[\d]", stripped)
        and re.search(r"[+\-*/%^x÷]", stripped)
    ):
        return True
    if re.match(r"^(?:sqrt|cbrt|abs|round|floor|ceil|log|log2|log10)\s*\([\d\s.,+\-*/]+\)$", stripped):
        return True
    return bool(
        any(k in clean for k in ("calculate", "solve", "math", "arithmetic", "convert"))
        and (re.search(r"\d+\s*[+\-*/x÷]\s*\d+", clean) or re.search(r"\d+\s*(?:tb|gb)\s*(?:to\s*tib|in\s*tib)", clean))
    )


def _arg(args: dict[str, Any], *keys: str, default: str = "") -> str:
    for k in keys:
        if args.get(k):
            return str(args[k]).strip()
    return default


def _build_tool_registry():
    from backend.services.ai_actions import MUTATING_TOOLS
    from backend.services.chat_tools import Tool, ToolRegistry

    reg = ToolRegistry(_has_write_permission)
    for d in _core().OPENAI_TOOL_DEFINITIONS:
        name = d["function"]["name"]
        reg.register(
            Tool(
                name=name,
                definition=d,
                handler=_core()._TOOL_HANDLERS[name],
                scopes=_core().TOOL_REQUIRED_SCOPES[name],
                web=name in _core()._WEB_TOOLS,
                mutating=name in MUTATING_TOOLS,
            )
        )
    return reg


def execute_nas_tool(
    tool_name: str, args: dict[str, Any], principal: Any = None, confirmed: bool = False, source: str = "chat"
) -> dict[str, Any]:
    """
    Runs a tool call through the registry: permission check, then a proposal for tools
    that change the system unless confirmed=True (the user clicked Confirm, AI-01).
    Hardware safety rules (standby, CPU fan, container self-stop) live in the tools.
    """
    from backend.services.ai_actions import propose_action

    clean_name = str(tool_name or "").strip()
    if not isinstance(args, dict):
        args = _safe_parse_tool_call_json(args)
    result = _core().TOOL_REGISTRY.dispatch(clean_name, args, principal, confirmed, propose_action)
    _audit_tool_call(clean_name, args, principal, confirmed, source, result)
    return result


def _audit_tool_call(
    name: str, args: dict[str, Any], principal: Any, confirmed: bool, source: str, result: Any
) -> None:
    """Every tool the assistant (or an MCP client) uses lands in the security audit log (D1): the
    tool and the names of its arguments, never their values, which can hold the question (SEC-32)."""
    try:
        from backend.users_db import log_security_event

        status = str((result or {}).get("status") or "ok") if isinstance(result, dict) else "ok"
        log_security_event(
            "ai.tool." + ("confirmed" if confirmed else "call"),
            "failure" if status in ("forbidden", "blocked", "error") else "success",
            actor_id=getattr(principal, "user_id", None) or getattr(principal, "id", None),
            actor_username=getattr(principal, "username", None),
            details={
                "tool": name,
                "source": source,
                "status": status,
                "arg_names": sorted(str(k)[:40] for k in (args or {}))[:20],
            },
        )
    except Exception:
        logger.debug("ai_chat_agent._audit_tool_call: audit log unavailable", exc_info=True)


def _format_tool_trace_summary(tr: dict[str, Any], tool_name: str) -> str:
    """Produces a concise 1-line telemetry summary for a completed tool call."""
    tname = str(tr.get("tool") or tool_name)
    if tname == "get_system_telemetry":
        return f"CPU {tr.get('cpu_load_pct')}% ({tr.get('cpu_temp_c')}°C), RAM {tr.get('ram_used_gb')}/{tr.get('ram_total_gb')} GB"
    elif tname == "get_disks_and_standby_status":
        return f"{tr.get('running_disks_count', 0)} active, {tr.get('sleeping_disks_count', 0)} sleeping in standby (0 wakeups)"
    elif tname == "get_fan_and_thermal_status":
        return f"Profile: {tr.get('profile')} ({tr.get('temp_min_c')}°C–{tr.get('temp_max_c')}°C)"
    elif tname == "set_fan_profile":
        return str(tr.get("message") or f"Set profile to {tr.get('new_profile')}")
    elif tname == "list_docker_containers":
        return f"{tr.get('running', 0)}/{tr.get('total', 0)} containers running"
    elif tname == "control_docker_container":
        return str(tr.get("message") or f"{tr.get('action')} {tr.get('container')}")
    elif tname == "search_nas_knowledge":
        f_str = f" in {tr.get('folder_path')}" if tr.get("folder_path") else ""
        return f"{tr.get('citations_count', 0)} doc citations, {tr.get('photos_count', 0)} photos{f_str} ({_grounding_label(tr.get('grounding_confidence_score'))})"
    elif tname == "trigger_ai_sync":
        return f"Sync {tr.get('action', 'start')} (Standby Safe)"
    elif tname == "browse_internet":
        return f"{len(tr.get('sources') or [])} web source(s) verified"
    elif tname == "calculate":
        return str(tr.get("summary") or f"{tr.get('expression')} = {tr.get('formatted')}")
    elif tname == "get_storage_status":
        return str(tr.get("summary") or f"{tr.get('free_tib')} TiB free")
    elif tname == "get_network_status":
        return str(tr.get("summary") or f"IP: {tr.get('ip_address')}")
    elif tname == "get_weather":
        if tr.get("is_ambiguous"):
            return f"Ambiguous: {tr.get('location')} ({len(tr.get('candidates', []))} countries available)"
        return str(tr.get("summary") or f"{tr.get('location')}: {tr.get('temperature_c')}°C, {tr.get('condition')}")
    else:
        return str(tr.get("status", "ok"))
