"""SET-00: every address a page calls exists on the server.

The pages and the server were tested apart, each against hand-made answers, so a page could ask an
address the server never had (the people list of the share dialog, "My alerts", the self-test
schedule in Drive Health) and every test stayed green. This test reads the calls out of the page
code and looks each one up among the server's routes, with its method.

KNOWN_MISSING holds the calls that are wrong today. It may only shrink: a call that is fixed must
leave the list, and a new miss fails the test.
"""

import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "frontend", "src")
CALL = re.compile(r"\bapi\.(get|post|put|patch|delete|postRaw|upload)\(\s*(['\"`])(/api/[^'\"`]*)\2")
METHODS = {"postraw": "POST", "upload": "POST"}

# (method, address as the page writes it): calls that reach no route today
KNOWN_MISSING: set[tuple[str, str]] = set()


def _page_calls():
    calls = {}
    for path in glob.glob(os.path.join(SRC, "**", "*.js"), recursive=True):
        if "__tests__" in path:
            continue
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for m in CALL.finditer(src):
            method = METHODS.get(m.group(1).lower(), m.group(1).upper())
            address = re.sub(r"\$\{[^}]*\}", "{}", m.group(3)).split("?")[0].rstrip("/")
            line = src.count("\n", 0, m.start()) + 1
            calls.setdefault((method, address), f"{os.path.relpath(path, ROOT)}:{line}")
    return calls


def _matches(address, route):
    """A page address with {} placeholders against a route template such as /api/x/{id}."""
    a, r = address.strip("/").split("/"), route.strip("/").split("/")
    for i, seg in enumerate(r):
        if seg.startswith("{") and seg.endswith(":path}"):
            return len(a) > i  # the rest of the address is the path
        if i >= len(a):
            return False
        if seg.startswith("{") or "{}" in a[i]:
            continue
        if seg != a[i]:
            return False
    return len(a) == len(r)


def _server_routes(app):
    """Method -> route templates, from the API description (the routes under /api/v1 are the same
    ones the pages reach under /api)."""
    out = {}
    for path, item in app.openapi()["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        for method in item:
            out.setdefault(method.upper(), []).append("/api/" + path[len("/api/v1/") :])
    return out


def test_every_address_a_page_calls_exists(client):
    routes = _server_routes(client.app)
    calls = _page_calls()
    assert len(calls) > 300, "the page calls were not found; has the api helper changed?"
    missing = {
        key: where
        for key, where in calls.items()
        if not any(_matches(key[1], route) for route in routes.get(key[0], ()))
    }
    new = {k: v for k, v in missing.items() if k not in KNOWN_MISSING}
    assert not new, "pages call addresses the server does not have:\n" + "\n".join(
        f"  {m} {a}  ({where})" for (m, a), where in sorted(new.items())
    )
    fixed = sorted(KNOWN_MISSING - set(missing))
    assert not fixed, f"these calls reach a route now; take them out of KNOWN_MISSING: {fixed}"
