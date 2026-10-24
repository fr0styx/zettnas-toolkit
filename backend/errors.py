"""
Consistent API error schema.

Every error response from the API has the shape::

    {"error": "<machine_slug>", "detail": "<human readable message>", "code": <http status>}

Validation failures additionally include ``"errors": [{"field": ..., "message": ...}]``.
The frontend can show ``detail`` directly and branch on ``error``.

A 500 never carries exception text (it can reveal paths, settings or internals): the
response says something went wrong and gives a ``reference``; the original message is
logged under that reference (ARCH-8).
"""

import secrets
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


GENERIC_500 = "Something went wrong on the server. The details are in the server log under this reference."


class ShownServerError(StarletteHTTPException):
    """A server-side failure whose message is meant for the user (e.g. why a VM didn't start).
    Unlike other 500s, its detail is returned as written. Never put raw exception text in it."""

    expose = True

    def __init__(self, detail: str, status_code: int = 500, error: str | None = None):
        super().__init__(status_code=status_code, detail=detail)
        self.error = error


def _hide_internal(status: int, detail: str, extra: dict[str, Any], shown: bool = False) -> str:
    """500s: log the original message under a reference and return a generic one."""
    if status != 500 or shown:
        return detail
    ref = extra.setdefault("reference", secrets.token_hex(4))
    if detail and detail not in (GENERIC_500, "Internal server error."):
        logger.error(f"[API] 500 (reference {ref}): {detail}")
    return GENERIC_500


def error_body(status: int, detail: str, error: str | None = None, shown: bool = False, **extra: Any) -> dict[str, Any]:
    detail = _hide_internal(status, detail, extra, shown)
    body = {"error": error or ERROR_SLUGS.get(status, "error"), "detail": detail, "code": status}
    body.update(extra)
    return body


def error_response(
    status: int,
    detail: str,
    error: str | None = None,
    headers: dict[str, str] | None = None,
    shown: bool = False,
    **extra: Any,
) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(status, detail, error, shown, **extra), headers=headers)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    shown = bool(getattr(exc, "expose", False))
    return error_response(
        exc.status_code, detail, error=getattr(exc, "error", None), headers=getattr(exc, "headers", None), shown=shown
    )


def _format_loc(loc) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) or "body"


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"field": _format_loc(e.get("loc", ())), "message": e.get("msg", "Invalid value")} for e in exc.errors()]
    first = errors[0] if errors else {"field": "body", "message": "Invalid request"}
    detail = f"Invalid {first['field']}: {first['message']}"
    return error_response(422, detail, errors=errors)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    ref = secrets.token_hex(4)
    logger.exception(f"Unhandled error on {request.method} {request.url.path} (reference {ref}): {exc}")
    return error_response(500, GENERIC_500, reference=ref)


def register_error_handlers(app) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    from backend.confirmations import ConfirmationRequired, confirmation_required_handler

    app.add_exception_handler(ConfirmationRequired, confirmation_required_handler)
