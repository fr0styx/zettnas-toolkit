"""
One registry for Ask Zetty's tools: definition, permission and handler together (AI-21).

Each tool states the scopes a user needs (the same ones its REST endpoint asks for),
whether it reaches the internet (only offered when the chat has Web on) and whether it
changes the system (then it only runs after the user confirms; otherwise it returns a
proposal). The model is offered, and may call, only what the user is allowed to run.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Handler = Callable[[dict[str, Any], Any], dict[str, Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    definition: dict[str, Any]  # OpenAI function-calling schema
    handler: Handler
    scopes: tuple[str, ...] | None = None  # None: any signed-in user
    web: bool = False
    mutating: bool = False


class ToolRegistry:
    def __init__(self, has_permission: Callable[[Any, tuple[str, ...]], bool]):
        self._tools: dict[str, Tool] = {}
        self._has_permission = has_permission

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} registered twice")
        if tool.definition.get("function", {}).get("name") != tool.name:
            raise ValueError(f"tool {tool.name}: definition name does not match")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def allowed(self, name: str, principal: Any) -> bool:
        """Unknown tools are refused. No principal means an internal call (scheduler, tests);
        mutating tools still need confirmation and check again inside."""
        tool = self._tools.get(name)
        if tool is None:
            return False
        if tool.scopes is None or principal is None:
            return True
        return self._has_permission(principal, tool.scopes)

    def for_principal(self, principal: Any, web_allowed: bool) -> list[dict[str, Any]]:
        return [
            t.definition for t in self._tools.values() if (web_allowed or not t.web) and self.allowed(t.name, principal)
        ]

    def dispatch(
        self,
        name: str,
        args: dict[str, Any],
        principal: Any,
        confirmed: bool,
        propose: Callable[[str, dict[str, Any], Any], dict[str, Any]],
    ) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None or not self.allowed(name, principal):
            return {
                "tool": name,
                "status": "forbidden",
                "error": f"Your account doesn't have permission to use '{name}'.",
            }
        if tool.mutating and not confirmed:
            return propose(name, args, principal)
        return tool.handler(args, principal)
