"""The app's per-request middleware as plain ASGI (NPERF-4).

Starlette's @app.middleware("http") (BaseHTTPMiddleware) runs the rest of the app in a task
group and passes every body chunk through a memory stream: three of them meant three extra hops
per chunk for every file download, video stream and the live event stream. These do the same
work on the response's start message only, and leave the body alone.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.requests import Request

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class SecurityHeaders:
    """nosniff, frame and referrer rules, the CSP on HTML pages, HSTS over HTTPS."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from backend.auth import request_is_https

        https = request_is_https(Request(scope))

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "SAMEORIGIN"
                h["Referrer-Policy"] = "strict-origin-when-cross-origin"
                h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                # Enforced CSP for the UI pages (FE-06); user files keep their own sandbox policy (SEC-05)
                if "content-security-policy" not in h and h.get("content-type", "").startswith("text/html"):
                    from backend.csp import policy

                    h["Content-Security-Policy"] = policy()
                if https:
                    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        await self.app(scope, receive, send_with_headers)


class CorrelationId:
    """An id per request (from X-Correlation-ID or a new one), on the response and in the logs,
    and request metrics by route (ARCH-10)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from backend.logging_config import correlation_id_ctx, correlation_id_from
        from backend.request_metrics import REQUEST_METRICS, route_template

        headers = dict((k.decode("latin-1").lower(), v.decode("latin-1")) for k, v in scope.get("headers") or [])
        corr_id = correlation_id_from(headers.get("x-correlation-id"))
        token = correlation_id_ctx.set(corr_id)
        started = time.perf_counter()
        status = [500]

        async def send_with_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status[0] = message["status"]
                MutableHeaders(scope=message)["X-Correlation-ID"] = corr_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            correlation_id_ctx.reset(token)
            path = scope.get("path", "")
            if path.startswith(("/api", "/redfish")):  # static files and the SPA aren't API calls
                REQUEST_METRICS.observe(
                    scope["method"], route_template(scope), status[0], time.perf_counter() - started
                )


class Passthrough:
    """What call_next gives a middleware function run by HttpFunction: the rest of the app,
    plus any headers the function adds to it."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


def http_function(fn: Callable[[Request, Callable[[Request], Awaitable[Any]]], Awaitable[Any]]) -> type:
    """Runs an @app.middleware("http")-style function as plain ASGI: call_next returns a
    Passthrough (headers may be added to it); any other response the function returns is sent
    instead of calling the rest of the app."""

    class HttpFunction:
        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            passthrough = Passthrough()

            async def call_next(_request: Request) -> Passthrough:
                return passthrough

            result = await fn(Request(scope, receive), call_next)
            if result is not passthrough:
                await result(scope, receive, send)
                return
            extra = passthrough.headers

            async def send_with_extra(message: dict[str, Any]) -> None:
                if extra and message["type"] == "http.response.start":
                    h = MutableHeaders(scope=message)
                    for k, v in extra.items():
                        h[k] = v
                await send(message)

            await self.app(scope, receive, send_with_extra)

    HttpFunction.__name__ = f"HttpFunction[{getattr(fn, '__name__', 'fn')}]"
    return HttpFunction
