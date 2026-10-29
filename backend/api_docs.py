"""Response schemas in the OpenAPI document for every API route (ARCH-11).

Routes declare a response_model where the response is validated on purpose. For all the
others, backend/models/responses.py (generated from what the routes return) documents the
response: the schema is attached to the route's OpenAPI entry only, so a response that
grows a field or returns null is never refused. The test suite checks the responses it
sees against these schemas (tests/response_contract.py).

install_openapi() finishes the document so it says what the server does (ARC-25): the one
error body every failure has, how to authenticate, which operations are public, which scopes
an operation needs, and the 401/403/404/422/429 answers.
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


# Operations that answer 429 from their own code rather than through rate_limit()
# (tests/test_arc25_openapi_truth.py finds them in the source and fails when one is missing).
OWN_RATE_LIMITS = {
    "POST /auth/login": "Failed sign-ins lock the address and the account for a while; Retry-After says how long.",
    "POST /auth/mfa/challenge": "Failed second steps lock the address and the account for a while.",
    "POST /auth/mfa/enable": "Wrong passwords lock MFA changes for this account for a while.",
    "POST /auth/mfa/disable": "Wrong passwords lock MFA changes for this account for a while.",
    "POST /security": "Wrong current passwords lock password changes from this address for a while.",
    "POST /users/{user_id}/password": "Wrong current passwords lock this account's password changes for a while.",
    "GET /invite/{token}": "20 attempts an hour per address.",
    "POST /invite/{token}/accept": "20 attempts an hour per address.",
    "GET /fs/shared/{token}": "120 requests a minute per address; 5 wrong passwords in 10 minutes block the address.",
    "POST /fs/shared/{token}": "120 requests a minute per address; 5 wrong passwords in 10 minutes block the address.",
    "GET /shared/{token}": "120 requests a minute per address; 5 wrong passwords in 10 minutes block the address.",
    "POST /shared/{token}": "120 requests a minute per address; 5 wrong passwords in 10 minutes block the address.",
    "GET /stats/stream": "At most 32 live telemetry streams at once.",
    "GET /fs/download-zip": "At most two archives are prepared at once.",
}

ERROR_SCHEMA = {
    "title": "Error",
    "type": "object",
    "description": "Every error has this body. Branch on `error`, show `detail`.",
    "required": ["error", "detail", "code"],
    "properties": {
        "error": {
            "type": "string",
            "description": "Stable slug, e.g. unauthorized, forbidden, not_found, rate_limited",
        },
        "detail": {"type": "string", "description": "Message for a person"},
        "code": {"type": "integer", "description": "The HTTP status"},
        "reference": {"type": "string", "description": "500 only: the server log has the full error under it"},
        "errors": {
            "type": "array",
            "description": "422 only: one entry per invalid field",
            "items": {"$ref": "#/components/schemas/FieldError"},
        },
    },
}
FIELD_ERROR_SCHEMA = {
    "title": "FieldError",
    "type": "object",
    "required": ["field", "message"],
    "properties": {"field": {"type": "string"}, "message": {"type": "string"}},
}


def _error(description: str, retry_after: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }
    if retry_after:
        out["headers"] = {"Retry-After": {"description": "Seconds to wait", "schema": {"type": "integer"}}}
    return out


RESPONSES = {
    "ValidationFailed": _error("The request body, query or path is invalid; `errors` names each field."),
    "Unauthorized": _error("No session or token, or it has expired or been revoked."),
    "Forbidden": _error(
        "The session or token lacks the scope, the password must be changed first, the address is blocked,"
        " or a browser request came from another site."
    ),
    "NotFound": _error("Nothing with that id or name."),
    "TooManyRequests": _error("Too many requests; wait as long as Retry-After says.", retry_after=True),
}

SECURITY_SCHEMES = {
    "bearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "description": "An API token (zat_…) from Settings › API tokens, or a session token from POST /api/v1/auth/login.",
    },
    "cookieAuth": {
        "type": "apiKey",
        "in": "cookie",
        "name": "zettnas_session",
        "description": "The web UI's session cookie.",
    },
}
SECURITY = [{"bearerAuth": []}, {"cookieAuth": []}]


def _walk(dependant: Any) -> Iterator[Any]:
    for dep in dependant.dependencies:
        yield dep.call
        yield from _walk(dep)


def route_facts(app: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """{(METHOD, full path): {"scopes": (...), "limit": (requests, seconds)}} from the routes' dependencies."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for full, route in iter_routes(app.router):
        facts: dict[str, Any] = {}
        for call in _walk(route.dependant):
            scopes = getattr(call, "required_scopes", None)
            if scopes:
                facts["scopes"] = tuple(facts.get("scopes", ())) + tuple(
                    s for s in scopes if s not in facts.get("scopes", ())
                )
            limit = getattr(call, "rate_limit", None)
            if limit:
                facts["limit"] = limit
        for method in route.methods or ():
            out[(method.upper(), full)] = facts
    return out


def is_protected(path: str) -> bool:
    from backend.auth import is_public_path

    return path.startswith(("/api/", "/redfish")) and not is_public_path(path)


def finish_schema(schema: dict[str, Any], app: Any) -> dict[str, Any]:
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    for name in ("HTTPValidationError", "ValidationError"):  # FastAPI's default 422 body, which this API never sends
        schemas.pop(name, None)
    schemas["Error"] = ERROR_SCHEMA
    schemas["FieldError"] = FIELD_ERROR_SCHEMA
    components["responses"] = RESPONSES
    components["securitySchemes"] = SECURITY_SCHEMES
    schema["security"] = SECURITY
    schema.setdefault("info", {})["description"] = (
        "The documented ZettNAS API. Every error has the Error body. Operations list the scopes they need"
        " in x-required-scopes; a public operation has an empty security list. See docs/API.md."
    )
    facts = route_facts(app)
    ref = "#/components/responses/"
    for path, ops in schema.get("paths", {}).items():
        protected = is_protected(path)
        for method, op in ops.items():
            responses = op.setdefault("responses", {})
            if "422" in responses:
                responses["422"] = {"$ref": ref + "ValidationFailed"}
            f = facts.get((method.upper(), path), {})
            if protected:
                responses.setdefault("401", {"$ref": ref + "Unauthorized"})
                responses.setdefault("403", {"$ref": ref + "Forbidden"})
            else:
                op["security"] = []
            if f.get("scopes"):
                op["x-required-scopes"] = list(f["scopes"])
            if "{" in path:
                responses.setdefault("404", {"$ref": ref + "NotFound"})
            own = OWN_RATE_LIMITS.get(canonical_key(method, path) or "")
            if f.get("limit") or own:
                responses.setdefault("429", {"$ref": ref + "TooManyRequests"})
                requests, seconds = f.get("limit") or (None, None)
                op["x-rate-limit"] = {"requests": requests, "seconds": seconds} if requests else {"description": own}
            op["responses"] = dict(sorted(responses.items()))
    return schema


def install_openapi(app: Any) -> None:
    """Builds /openapi.json once, finished by finish_schema()."""
    from fastapi.openapi.utils import get_openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            base = get_openapi(
                title=app.title, version=app.version, openapi_version=app.openapi_version, routes=app.routes
            )
            app.openapi_schema = finish_schema(base, app)
        return app.openapi_schema

    app.openapi = openapi
