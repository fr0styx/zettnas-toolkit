"""ARC-21: nothing waits forever. Short external commands have a time limit, the session lookup
runs off the event loop, and the pool for blocking routes has an explicit size."""

import ast
import pathlib
import sys

import anyio

from backend.proc import TIMED_OUT, run_bounded

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOUNDED = {"run", "check_output", "check_call", "call"}


def test_every_short_command_has_a_timeout():
    found = []
    for path in (ROOT / "backend").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for node in ast.walk(ast.parse(text)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in BOUNDED
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and not any(k.arg == "timeout" for k in node.keywords)
                and "runs until stopped" not in lines[node.lineno - 1]
            ):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not found, "give these a timeout (or use backend.proc.run_bounded):\n" + "\n".join(found)


def test_a_hang_counts_as_a_failure():
    r = run_bounded([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.3, capture_output=True)
    assert r.returncode == TIMED_OUT and r.stdout == b""
    r = run_bounded([sys.executable, "-c", "print('ok')"], timeout=10, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok"


def test_the_session_lookup_is_off_the_loop():
    src = (ROOT / "backend" / "auth.py").read_text(encoding="utf-8")
    middleware = src[src.index("async def auth_middleware") :]
    middleware = middleware[: middleware.index("\ndef ") if "\ndef " in middleware else len(middleware)]
    assert "await asyncio.to_thread(get_current_session, token)" in middleware
    assert "sess = get_current_session(token)" not in middleware


def test_blocking_routes_get_the_configured_pool(monkeypatch):
    from backend import config
    from backend.main import configure_thread_limits

    monkeypatch.setattr(config, "SYNC_ROUTE_THREADS", 24)

    async def main():
        assert configure_thread_limits() == 24
        assert anyio.to_thread.current_default_thread_limiter().total_tokens == 24

    anyio.run(main)
