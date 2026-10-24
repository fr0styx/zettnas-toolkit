"""Checks API responses in tests against the documented response schemas (ARCH-11).

tests/conftest.py sends every JSON response of the test client here. A response that no
longer fits the schema documented for its route fails the test: the code changed what the
route returns, so the documentation must follow (scripts/gen_response_models.py).
"""

from functools import cache, lru_cache

from pydantic import TypeAdapter, ValidationError
from starlette.routing import compile_path


@lru_cache(maxsize=1)
def _routes():
    from backend.api_docs import iter_routes, response_schema_for

    out = []
    for full, route in iter_routes():
        if route.response_model is not None:
            continue
        for method in route.methods:
            schema = response_schema_for(method, full)
            if schema is not None:
                out.append((method, compile_path(full)[0], full, schema))
    return out


@cache
def _adapter(schema):
    return TypeAdapter(schema)


def check_response(app, method: str, path: str, body) -> None:
    for m, regex, full, schema in _routes():
        if m == method and regex.match(path):
            try:
                _adapter(schema).validate_python(body)
            except ValidationError as exc:
                raise AssertionError(
                    f"{method} {full} returned a response that does not match its documented schema "
                    f"(backend/models/responses.py). If the change is intended, record the responses and "
                    f"run scripts/gen_response_models.py.\n{exc}"
                ) from None
            return
