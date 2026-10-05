"""
Consistent API error schema.

Every error response from the API has the shape::

    {"error": "<machine_slug>", "detail": "<human readable message>", "code": <http status>}

Validation failures additionally include ``"errors": [{"field": ..., "message": ...}]``.
The frontend can show ``detail`` directly and branch on ``error``.
"""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.config import logger

ERROR_SLUGS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
}


def error_body(status: int, detail: str, error: str | None = None, **extra: Any) -> dict[str, Any]:
    body = {"error": error or ERROR_SLUGS.get(status, "error"), "detail": detail, "code": status}
    body.update(extra)
    return body


def error_response(
    status: int, detail: str, error: str | None = None, headers: dict[str, str] | None = None, **extra: Any
) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(status, detail, error, **extra), headers=headers)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return error_response(exc.status_code, detail, headers=getattr(exc, "headers", None))


def _format_loc(loc) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) or "body"


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": _format_loc(e.get("loc", ())), "message": e.get("msg", "Invalid value")} for e in exc.errors()]
    first = errors[0] if errors else {"field": "body", "message": "Invalid request"}
    detail = f"Invalid {first['field']}: {first['message']}"
    return error_response(422, detail, errors=errors)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    return error_response(500, "Internal server error.")


def register_error_handlers(app) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
