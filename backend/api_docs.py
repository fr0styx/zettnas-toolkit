"""Response schemas in the OpenAPI document for every API route (ARCH-11).

Routes declare a response_model where the response is validated on purpose. For all the
others, backend/models/responses.py (generated from what the routes return) documents the
response: the schema is attached to the route's OpenAPI entry only, so a response that
grows a field or returns null is never refused. The test suite checks the responses it
sees against these schemas (tests/response_contract.py).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi.routing import APIRoute
from fastapi.utils import create_model_field

API_PREFIXES = ("/api/v1", "/api")


def iter_routes(router: Any = None, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """(full path, route) for every API route, through included routers."""
    if router is None:
        from backend.main import app

        router = app.router
    for r in router.routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r
        elif hasattr(r, "original_router") and hasattr(r, "include_context"):
            yield from iter_routes(r.original_router, prefix + (r.include_context.prefix or ""))


def canonical_key(method: str, full_path: str) -> str | None:
    """'GET /lcd/page' for GET /api/v1/lcd/page or /api/lcd/page; None outside the API."""
    for prefix in API_PREFIXES:
        if full_path.startswith(prefix + "/"):
            return f"{method.upper()} {full_path[len(prefix) :]}"
    return None


def response_schema_for(method: str, full_path: str) -> Any:
    from backend.models.responses import ROUTE_RESPONSES

    key = canonical_key(method, full_path)
    return ROUTE_RESPONSES.get(key) if key else None


def document_responses(app: Any) -> int:
    """Attaches the documented response schemas to the routes. Returns how many routes got one."""
    from backend.models.responses import ROUTE_RESPONSES

    done: set[int] = set()
    for full, route in iter_routes(app.router):
        if id(route) in done or route.response_model is not None:
            continue
        code = route.status_code or 200
        if code in route.responses:
            continue
        for method in sorted((route.methods or set()) - {"HEAD"}):
            schema = ROUTE_RESPONSES.get(canonical_key(method, full) or "")
            if schema is None:
                continue
            route.responses = {**route.responses, code: {"model": schema, "description": "Successful Response"}}
            route.response_fields = {
                **route.response_fields,
                code: create_model_field(name=f"Response_{code}_{route.unique_id}", type_=schema, mode="serialization"),
            }
            done.add(id(route))
            break
    return len(done)
