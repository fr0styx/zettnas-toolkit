"""ARC-25: /openapi.json says what the server does: one error body, how to authenticate,
which operations are public, the scopes and the 401/403/404/422/429 answers."""

import ast
import inspect
import os
import re
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import api_reference  # noqa: E402

from app import app  # noqa: E402
from backend import __version__  # noqa: E402
from backend.api_docs import OWN_RATE_LIMITS, canonical_key, finish_schema, iter_routes, route_facts  # noqa: E402
from backend.auth import is_public_path  # noqa: E402

SCHEMA = app.openapi()
REF = "#/components/responses/"


def _ops():
    for path, ops in SCHEMA["paths"].items():
        for method, op in ops.items():
            yield path, method, op


def test_the_document_carries_the_running_version():
    assert SCHEMA["info"]["version"] == __version__


def test_one_error_body_and_no_fastapi_default_422():
    schemas = SCHEMA["components"]["schemas"]
    assert "HTTPValidationError" not in schemas and "ValidationError" not in schemas
    assert schemas["Error"]["required"] == ["error", "detail", "code"]
    for path, method, op in _ops():
        if "422" in op["responses"]:
            assert op["responses"]["422"] == {"$ref": REF + "ValidationFailed"}, (method, path)


def test_security_schemes_match_what_the_server_reads():
    from backend import auth

    schemes = SCHEMA["components"]["securitySchemes"]
    assert schemes["bearerAuth"] == {**schemes["bearerAuth"], "type": "http", "scheme": "bearer"}
    src = inspect.getsource(auth.extract_token)
    assert f'cookies.get("{schemes["cookieAuth"]["name"]}"' in src
    assert set(schemes) == {"bearerAuth", "cookieAuth"}  # extract_token reads nothing else (URL tickets are single-use)
    assert SCHEMA["security"]


def test_public_operations_are_exactly_the_ones_the_middleware_lets_through():
    for path, method, op in _ops():
        api = path.startswith(("/api/", "/redfish"))
        if api and not is_public_path(path):
            assert "security" not in op, (method, path)
            assert {"401", "403"} <= set(op["responses"]), (method, path)
        else:
            assert op.get("security") == [], (method, path)
    publics = {p for p, _, op in _ops() if op.get("security") == [] and p.startswith("/api/v1/")}
    assert "/api/v1/auth/login" in publics and "/api/v1/health" in publics
    assert "/api/v1/auth/me" not in publics


def test_scopes_come_from_the_routes_dependencies():
    op = SCHEMA["paths"]["/api/v1/invites"]["post"]
    assert op["x-required-scopes"] == ["users:write"]
    scoped = sum(1 for _, _, op in _ops() if op.get("x-required-scopes"))
    assert scoped > 400


def test_path_parameters_can_be_not_found():
    for path, method, op in _ops():
        if "{" in path:
            assert "404" in op["responses"], (method, path)


# --- 429: from rate_limit() or from the operation's own code ---

_ANSWERS_429 = re.compile(
    r"status_code=429|error_response\(429|_rate_limited\(|_lockout_remaining\(|login_lockout\.remaining\(|\b429,"
)


def _src(fn) -> str:
    try:
        return textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return ""


def _answers_429(fn, depth: int = 2) -> bool:
    """The function, or a function of its own module it calls (two levels), can answer 429."""
    src = _src(fn)
    if _ANSWERS_429.search(src):
        return True
    if depth == 0 or not src:
        return False
    mod = sys.modules.get(fn.__module__)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            other = getattr(mod, node.func.id, None)
            if (
                inspect.isfunction(other)
                and other is not fn
                and other.__module__ == fn.__module__
                and _answers_429(other, depth - 1)
            ):
                return True
    return False


def test_every_operation_that_can_answer_429_says_so():
    facts = route_facts(app)
    found = set()
    for full, route in iter_routes(app.router):
        if not full.startswith("/api/v1/"):
            continue
        for method in sorted((route.methods or set()) - {"HEAD"}):
            if not facts.get((method, full), {}).get("limit") and _answers_429(route.endpoint):
                found.add(canonical_key(method, full))
    assert found == set(OWN_RATE_LIMITS), (
        "Add the operation to OWN_RATE_LIMITS in backend/api_docs.py (or remove a stale one): "
        f"missing {sorted(found - set(OWN_RATE_LIMITS))}, stale {sorted(set(OWN_RATE_LIMITS) - found)}"
    )
    for path, method, op in _ops():
        key = canonical_key(method, path)
        if key in OWN_RATE_LIMITS or facts.get((method.upper(), path), {}).get("limit"):
            assert op["responses"]["429"] == {"$ref": REF + "TooManyRequests"}, (method, path)
            assert op["x-rate-limit"], (method, path)
        else:
            assert "429" not in op["responses"], (method, path)


def test_rate_limit_dependency_gives_its_numbers():
    limited = [op for _, _, op in _ops() if "requests" in op.get("x-rate-limit", {})]
    assert limited
    assert all(op["x-rate-limit"]["requests"] > 0 and op["x-rate-limit"]["seconds"] > 0 for op in limited)


def test_finish_schema_on_a_small_app():
    from fastapi import Depends, FastAPI

    from backend.auth import require_scope
    from backend.rate_limit import rate_limit

    small = FastAPI()

    @small.get(
        "/api/v1/things/{tid}", dependencies=[Depends(require_scope("things:read")), Depends(rate_limit("t", 5, 60))]
    )
    def thing(tid: int):
        return {}

    @small.get("/api/v1/health")
    def health():
        return {}

    from fastapi.openapi.utils import get_openapi

    doc = finish_schema(get_openapi(title="t", version="1", routes=small.routes), small)
    op = doc["paths"]["/api/v1/things/{tid}"]["get"]
    assert set(op["responses"]) == {"200", "401", "403", "404", "422", "429"}
    assert op["x-required-scopes"] == ["things:read"]
    assert op["x-rate-limit"] == {"requests": 5, "seconds": 60}
    assert doc["paths"]["/api/v1/health"]["get"]["security"] == []


# --- the answers really have the documented body ---


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _is_error(body: dict, code: int) -> None:
    assert set(SCHEMA["components"]["schemas"]["Error"]["required"]) <= set(body)
    assert body["code"] == code and isinstance(body["error"], str) and isinstance(body["detail"], str)
    assert set(body) <= set(SCHEMA["components"]["schemas"]["Error"]["properties"])


def test_a_401_has_the_error_body(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    _is_error(r.json(), 401)


def test_a_422_has_the_error_body_with_fields(client):
    r = client.post("/api/v1/auth/login", json={"remember_me": "not a bool"})
    assert r.status_code == 422
    body = r.json()
    _is_error(body, 422)
    assert body["errors"] and {"field", "message"} == set(body["errors"][0])


# --- docs/API.md ---


def test_api_md_endpoint_list_is_generated_from_this_schema():
    doc = api_reference.current_doc()
    assert api_reference.updated(doc, api_reference.render(SCHEMA)) == doc, (
        "docs/API.md is out of date: python scripts/api_reference.py --update"
    )


def test_api_md_lists_every_documented_operation():
    doc = api_reference.current_doc()
    for path, method, _op in _ops():
        if path.startswith(("/api/v1/", "/redfish")):
            assert f"| `{method.upper()}` | `{path}` |" in doc, (method, path)
