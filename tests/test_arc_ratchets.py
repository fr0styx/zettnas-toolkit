"""Ratchets for the v1.10 audit (ARC-2, ARC-3): the counts may only go down.

ARC-3: an `async def` route that never awaits runs on the event loop, so one slow call (a
password hash, a SQLite lock wait, a sleeping disk) freezes every user. Make it `def` (FastAPI
runs it in the threadpool) or await the slow part with asyncio.to_thread.

ARC-2: a function that reads a JSON settings file and writes it back must hold the file's lock
(`@json_locked(...)` or `with locked_json(path):` from backend.fsutil), or two writers undo each
other's changes.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "api_route", "websocket"}
ASYNC_ROUTES_WITHOUT_AWAIT_BASELINE = 21
UNLOCKED_JSON_RMW_BASELINE = 7


def _async_routes_without_await() -> list[str]:
    out = []
    for p in sorted((ROOT / "backend" / "api").glob("*.py")):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            is_route = any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ROUTE_METHODS for d in node.decorator_list
            )
            awaits = any(isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith)) for n in ast.walk(node))
            if is_route and not awaits:
                out.append(f"{p.name}:{node.lineno}:{node.name}")
    return out


def _unlocked_json_rmw() -> list[str]:
    readers = {"read_json", "read_json_cached", "load_config", "get_backup_jobs"}
    out = []
    for p in sorted((ROOT / "backend").rglob("*.py")):
        if p.name == "fsutil.py" or "fuse_hidden" in p.name:
            continue
        for fn in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = {
                getattr(c.func, "id", getattr(c.func, "attr", "")) for c in ast.walk(fn) if isinstance(c, ast.Call)
            }
            if "atomic_write_json" not in calls or not calls & readers:
                continue
            decorated = any(getattr(getattr(d, "func", d), "id", "") == "json_locked" for d in fn.decorator_list)
            in_with = any(
                isinstance(w, ast.With)
                and any(getattr(getattr(i.context_expr, "func", None), "id", "") == "locked_json" for i in w.items)
                for w in ast.walk(fn)
            )
            if not (decorated or in_with):
                out.append(f"{p.relative_to(ROOT)}:{fn.lineno}:{fn.name}")
    return out


def test_no_new_blocking_async_routes():
    found = _async_routes_without_await()
    assert len(found) <= ASYNC_ROUTES_WITHOUT_AWAIT_BASELINE, "\n".join(found)


def test_no_new_unlocked_json_read_modify_write():
    found = _unlocked_json_rmw()
    assert len(found) <= UNLOCKED_JSON_RMW_BASELINE, "\n".join(found)


def test_locked_json_serialises_writers(tmp_path):
    import threading

    from backend.fsutil import atomic_write_json, json_locked, read_json

    path = str(tmp_path / "counter.json")
    atomic_write_json(path, {"n": 0})

    @json_locked(lambda: path)
    def bump():
        data = read_json(path, {"n": 0})
        data["n"] += 1
        atomic_write_json(path, data)

    threads = [threading.Thread(target=lambda: [bump() for _ in range(25)]) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert read_json(path)["n"] == 200
