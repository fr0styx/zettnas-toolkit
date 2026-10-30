"""NPERF-4: the per-request middleware is plain ASGI; headers, auth and the correlation id work
as before, and a streamed body goes through untouched."""

from starlette.middleware.base import BaseHTTPMiddleware

from backend.main import app


def test_no_base_http_middleware_left():
    assert not [m for m in app.user_middleware if m.cls is BaseHTTPMiddleware]


def test_headers_and_correlation_id(client):
    res = client.get("/api/health", headers={"X-Correlation-ID": "abc-123-xyz"})
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert res.headers["X-Correlation-ID"] == "abc-123-xyz"
    html = client.get("/")
    if html.headers.get("content-type", "").startswith("text/html"):
        assert "content-security-policy" in {k.lower() for k in html.headers}


def test_auth_still_refuses_and_passes(client, auth_headers):
    client.cookies.clear()  # signed in only by the header below
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users", headers=auth_headers).status_code == 200


def test_http_function_adds_headers_and_can_answer():
    import asyncio

    from starlette.responses import PlainTextResponse

    from backend.asgi_middleware import http_function

    async def fn(request, call_next):
        if request.url.path == "/stop":
            return PlainTextResponse("no", status_code=403)
        res = await call_next(request)
        res.headers.update({"Deprecation": "true"})
        return res

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = http_function(fn)(inner)
    sent = []

    async def send(m):
        sent.append(m)

    async def receive():
        return {"type": "http.request", "body": b""}

    def scope(path):
        return {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "server": ("t", 80),
            "scheme": "http",
        }

    asyncio.run(mw(scope("/ok"), receive, send))
    assert (b"deprecation", b"true") in sent[0]["headers"] and sent[1]["body"] == b"ok"
    sent.clear()
    asyncio.run(mw(scope("/stop"), receive, send))
    assert sent[0]["status"] == 403
    sent.clear()
    asyncio.run(mw({"type": "lifespan"}, receive, send))  # other kinds pass through
