"""B11 (SEC-33): every API write needs a write scope. The exceptions are listed with their
reason: a person's own things, sign-in, links, and POSTs that only read. A new write that a
read-only scope can reach fails this test until it gets a write scope or a line here."""

from fastapi.routing import APIRoute

# no scope at all: the route acts on the signed-in person's own account, or is a sign-in step
OWN_OR_SIGN_IN = {
    "/api/v1/auth/login": "signing in",
    "/api/v1/auth/logout": "signing out",
    "/api/v1/auth/mfa/challenge": "signing in",
    "/api/v1/auth/mfa/setup": "their own two-factor",
    "/api/v1/auth/mfa/enable": "their own two-factor",
    "/api/v1/auth/mfa/disable": "their own two-factor (password and code)",
    "/api/v1/auth/sessions": "their own sessions",
    "/api/v1/auth/sessions/{session_id_hash}": "their own sessions",
    "/api/v1/auth/ticket": "a ticket for their own session",
    "/api/v1/confirmations": "a confirm token for their own request",
    "/api/v1/auth/me/preferences": "their own settings (Advanced)",
    "/api/v1/users/{user_id}": "their own profile; others need users:write (checked in the route)",
    "/api/v1/users/{user_id}/password": "their own password; others need users:write (checked in the route)",
    "/api/v1/users/{user_id}/erase-data": "their own data; others need users:delete and a confirmation",
    "/api/v1/fs/shared/{token}": "a public link; the token (and password) is the credential",
    "/api/v1/shared/{token}": "a public link; the token (and password) is the credential",
    "/api/v1/invite/{token}/accept": "an invite; the token is the credential",
    "/api/v1/remotes/oauth/mobile-exchange": "cloud sign-in on a phone; the state is the credential",
    "/api/v1/immich/me": "their own Immich link",
    "/api/v1/immich/phone": "their own phone backup",
    "/api/v1/jobs/{job_id}/cancel": "their own job (checked in the route)",
    "/api/v1/mcp": "MCP calls; each tool checks the caller's scopes",
    "/api/v1/notifications/notifications/me": "their own alert route",
    "/api/v1/push/subscribe": "their own phone",
    "/api/v1/push/unsubscribe": "their own phone",
    "/api/v1/{unmatched_path:path}": "answers 404",
}

# a read scope is enough: the request reads, or changes only the person's own things
READ_LIKE = {
    "/api/v1/push/test": "a test message to their own devices",
    "/api/v1/docker/updates/check": "looks up newer images; changes nothing",
    "/api/v1/fs/checksum": "reads a file",
    "/api/v1/fs/folder-size": "reads a folder (asks before waking a drive)",
    "/api/v1/fs/favorites": "their own favourites",
    "/api/v1/network/mesh-vpn/tailscale/ping": "a ping; changes nothing",
    "/api/v1/media/organize/preview": "a preview; changes nothing",
    "/api/v1/ai/actions/{action_id}/confirm": "their own proposed action; the tool checks its own scope",
}
for _p in (
    "favorites",
    "search",
    "ask",
    "folder/audit",
    "chat",
    "chat/stream",
    "conversations",
    "conversations/{conv_id}",
    "conversations/{conv_id}/messages",
):
    for _base in ("/api/v1/ai/", "/api/v1/media/"):
        READ_LIKE[_base + _p] = "their own search, chats and favourites (AI access is checked per role)"
READ_LIKE.pop("/api/v1/media/conversations/{conv_id}/messages")  # only under /ai/


def _scope_args(fn):
    """The scopes a require_scope(...) dependency asks for."""
    if "require_scope" not in getattr(fn, "__qualname__", "") or not fn.__closure__:
        return []
    found = []
    for cell in fn.__closure__:
        if isinstance(cell.cell_contents, tuple):
            found.extend(cell.cell_contents)
    return found


def _scopes(dependant, out):
    for d in dependant.dependencies:
        out.extend(_scope_args(d.call))
        _scopes(d, out)
    return out


def _routes(routes, prefix="", extra=()):
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r, list(extra)
        elif hasattr(r, "include_context") and hasattr(r, "original_router"):
            ctx = r.include_context
            more = [s for d in (ctx.dependencies or []) for s in _scope_args(d.dependency)]
            yield from _routes(r.original_router.routes, prefix + (ctx.prefix or ""), (*extra, *more))


def _writes():
    from app import app

    out: dict[str, list[str]] = {}
    for path, route, extra in _routes(app.routes):
        if path.startswith("/api/v1/") and "/_test/" not in path and route.methods - {"GET", "HEAD", "OPTIONS"}:
            out.setdefault(path, []).extend(_scopes(route.dependant, []) + extra)
    return out


def _read_only(scopes):
    return any(s.endswith((":read", ":view")) or s == "*:read" for s in scopes)


def test_every_write_needs_a_write_scope_or_has_a_reason():
    writes = _writes()
    assert len(writes) > 200  # the walk found the app's routes
    unscoped = sorted(p for p, s in writes.items() if not s and p not in OWN_OR_SIGN_IN)
    assert not unscoped, "writes with no scope:\n" + "\n".join(unscoped)
    weak = sorted(p for p, s in writes.items() if s and _read_only(s) and p not in READ_LIKE)
    assert not weak, "writes a read-only scope reaches (give them a write scope, or a reason):\n" + "\n".join(weak)


def test_the_lists_hold_no_stale_routes():
    writes = _writes()
    assert not [p for p in {**OWN_OR_SIGN_IN, **READ_LIKE} if p not in writes]
