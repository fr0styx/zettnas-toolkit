"""B11 (SEC-33): every API read needs a scope, unless it is one of the reads below that any
signed-in person (or, for sign-in and links, anyone) may make, each with its reason.
A new GET route fails this test until it gets a scope or a line here."""

from fastapi.routing import APIRoute

from backend.users_db import create_user

ANY_SIGNED_IN = {
    # their own account, sign-in and devices
    "/api/v1/auth/me": "their own account",
    "/api/v1/auth/mfa/status": "their own two-factor state",
    "/api/v1/auth/sessions": "their own sessions",
    "/api/v1/users/{user_id}": "their own profile; others need users:read (checked in the route)",
    "/api/v1/users/{user_id}/export": "their own data; others need users:write and a confirmation",
    "/api/v1/ai/access/me": "what they may ask Zetty",
    "/api/v1/ai/actions/{action_id}": "an action they started",
    "/api/v1/notifications/notifications/me": "their own alert route",
    "/api/v1/push/devices": "their own phones",
    "/api/v1/push/vapid-public-key": "the key their phone subscribes with",
    "/api/v1/immich": "their own Immich link",
    "/api/v1/jobs": "their own jobs",
    "/api/v1/calendar/events": "their own and shared calendars",
    "/api/v1/calendar/export": "their own calendars",
    "/api/v1/calendar/feeds": "their own calendar feeds",
    "/api/v1/setup/checklist": "Getting started for them",
    # files: every path is checked against what they may open (share access)
    "/api/v1/browse": "folders they may open",
    "/api/v1/fs/download": "files they may open",
    "/api/v1/fs/download-zip": "files they may open",
    "/api/v1/fs/stream": "files they may open",
    "/api/v1/fs/transfers/stream": "their own transfers",
    # the desktop everyone sees
    "/api/v1/stats": "the desktop (a reduced view for family roles is still open)",
    "/api/v1/stats/stream": "the desktop (a reduced view for family roles is still open)",
    "/api/v1/layout": "the desktop layout, clock and time zone",
    "/api/v1/system/client-preferences": "the desktop look",
    "/api/v1/system/about": "the version",
    "/api/v1/system/identity": "the server name and time zone",
    "/api/v1/wallpaper_url": "the desktop background",
    "/api/v1/wallpapers": "the desktop backgrounds",
    "/api/v1/wallpapers/thumb/{filename}": "the desktop backgrounds",
    # no data
    "/api/v1/mcp": "answers 405 (the MCP endpoint is POST)",
    "/api/v1/{unmatched_path:path}": "answers 404",
}

# Anyone, before or without signing in (the auth middleware lets these through)
PUBLIC = {
    "/api/v1/health": "health check",
    "/api/v1/auth/users-list": "the sign-in page",
    "/api/v1/auth/oidc/config": "the sign-in page",
    "/api/v1/auth/oidc/login": "single sign-on",
    "/api/v1/auth/oidc/callback": "single sign-on",
    "/api/v1/fs/shared/{token}": "a public link; the token (and password) is the credential",
    "/api/v1/shared/{token}": "a public link; the token (and password) is the credential",
    "/api/v1/invite/{token}": "an invite; the token is the credential",
    "/api/v1/wallpapers/download/{filename}": "the sign-in page background",
    "/api/v1/remotes/oauth/mobile-page": "cloud sign-in on a phone; the state is the credential",
}


def _deps(dependant, out):
    for d in dependant.dependencies:
        out.append(getattr(d.call, "__qualname__", ""))
        _deps(d, out)
    return out


def _routes(routes, prefix="", extra=()):
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r, list(extra)
        elif hasattr(r, "include_context") and hasattr(r, "original_router"):
            ctx = r.include_context
            more = [getattr(d.dependency, "__qualname__", "") for d in (ctx.dependencies or [])]
            yield from _routes(r.original_router.routes, prefix + (ctx.prefix or ""), (*extra, *more))


def _get_routes():
    from app import app

    out = {}
    for path, route, extra in _routes(app.routes):
        if path.startswith("/api/v1/") and "/_test/" not in path and "GET" in route.methods:
            out[path] = any("require_scope" in n for n in _deps(route.dependant, []) + extra)
    return out


def test_every_read_has_a_scope_or_a_reason():
    routes = _get_routes()
    assert len(routes) > 150  # the walk found the app's routes
    missing = sorted(p for p, scoped in routes.items() if not scoped and p not in ANY_SIGNED_IN and p not in PUBLIC)
    assert not missing, "GET routes with no scope (add require_scope, or a reason above):\n" + "\n".join(missing)


def test_the_lists_hold_no_stale_or_scoped_routes():
    routes = _get_routes()
    listed = {**ANY_SIGNED_IN, **PUBLIC}
    assert not [p for p in listed if p not in routes], "remove routes that no longer exist"
    assert not [p for p in listed if routes.get(p)], "a scoped route needs no exception"


def test_public_reads_are_the_ones_the_middleware_lets_through():
    from backend.auth import _PUBLIC_API_PATHS

    for path in PUBLIC:
        if "{" not in path:
            assert path in _PUBLIC_API_PATHS or path.replace("/api/v1/", "/api/") in _PUBLIC_API_PATHS, path


def _login(client, username, role_id, password="GoodPass123!"):
    create_user(username, username, password, role_id=role_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_a_kid_keeps_the_desktop_but_not_the_admin_reads(client):
    kid = _login(client, "scope_kid", "kid")
    for path in ("/api/stats", "/api/layout", "/api/system/about"):
        assert client.get(path, headers=kid).status_code == 200, path
    for path in (
        "/api/samba/shares",
        "/api/ups/events",
        "/api/fans",
        "/api/chassis/config",
        "/api/docker/catalog",
        "/api/history",
        "/api/disk/smart_tests",
        "/api/webdav/status",
    ):
        assert client.get(path, headers=kid).status_code == 403, path


def test_an_admin_still_reads_them(client, auth_headers):
    for path in ("/api/fans", "/api/ups/events", "/api/chassis/config", "/api/history"):
        assert client.get(path, headers=auth_headers).status_code != 403, path
