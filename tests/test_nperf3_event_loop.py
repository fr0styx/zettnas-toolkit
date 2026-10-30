"""NPERF-3: async routes don't call known blocking work directly on the event loop.

A path check that resolves symlinks, a users.db read, Argon2, the activity log's SQLite write or a
big gzip can each hold the loop for milliseconds to seconds (a FUSE lookup waits for a disk to spin
up), freezing every other request and the live updates. In an `async def` they go through
asyncio.to_thread. This counts the direct calls per file; a file may only go down.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCKING_NAMES = {
    "check_user_path_access",
    "record_activity",
    "_observe",
    "hash_password",
    "get_user_by_username",
    "create_user",
}
BLOCKING_ATTRS = {
    ("os.path", "realpath"),
    ("os.path", "isdir"),
    ("os.path", "exists"),
    ("gzip", "compress"),
    ("users_db", None),
}
# direct calls left in async functions, per file (lower these as they are moved off the loop)
BASELINE = {
    "backend/api/auth.py": 3,
    "backend/api/backup.py": 1,
    "backend/api/docker.py": 1,
    "backend/api/encrypted_folders.py": 1,
    "backend/api/files/details.py": 2,
    "backend/api/files/operations.py": 1,
    "backend/api/files/preview.py": 3,
    "backend/api/files/search.py": 2,
    "backend/api/files/share_links.py": 2,
    "backend/api/files/uploads.py": 8,
    "backend/api/media.py": 2,
    "backend/api/remotes.py": 1,
    "backend/api/system.py": 1,
    "backend/api/vms.py": 6,
    "backend/api/webdav.py": 5,
    "backend/auth.py": 1,
    "backend/docker_proxy.py": 1,
    "backend/services/console_proxy.py": 1,
    "backend/services/copy_engine.py": 1,
    "backend/services/docker_terminal.py": 1,
    "backend/services/vm_engine.py": 1,
}


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def blocking_calls(src):
    """(line, name) of each known blocking call made directly in an async function."""
    out = []

    def walk(node, in_async):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AsyncFunctionDef):
                walk(child, True)
                continue
            if isinstance(child, (ast.FunctionDef, ast.Lambda)):
                walk(child, False)
                continue
            if in_async and isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Name) and f.id in BLOCKING_NAMES:
                    out.append((child.lineno, f.id))
                elif isinstance(f, ast.Attribute):
                    owner = _dotted(f.value)
                    if (owner, f.attr) in BLOCKING_ATTRS or (owner, None) in BLOCKING_ATTRS:
                        out.append((child.lineno, f"{owner}.{f.attr}"))
            walk(child, in_async)

    walk(ast.parse(src), False)
    return out


def counts():
    found = {}
    for path in sorted((ROOT / "backend").rglob("*.py")):
        n = len(blocking_calls(path.read_text(encoding="utf-8")))
        if n:
            found[str(path.relative_to(ROOT))] = n
    return found


def test_no_file_calls_more_blocking_work_on_the_loop():
    now = counts()
    worse = {f: (n, BASELINE.get(f, 0)) for f, n in now.items() if n > BASELINE.get(f, 0)}
    assert not worse, "blocking calls in async functions (use asyncio.to_thread): " + ", ".join(
        f"{f}: {n} (was {b})" for f, (n, b) in worse.items()
    )


def test_the_baseline_is_tight():
    now = counts()
    loose = {f: b for f, b in BASELINE.items() if now.get(f, 0) < b}
    assert not loose, f"lower BASELINE in this test: {loose}"


def test_the_scanner():
    src = (
        "import os\nasync def a():\n    check_user_path_access(p, u)\n    os.path.realpath(p)\n"
        "    await asyncio.to_thread(check_user_path_access, p, u)\n    def inner():\n        record_activity(x)\n"
        "def b():\n    record_activity(x)\n"
    )
    assert [n for _, n in blocking_calls(src)] == ["check_user_path_access", "os.path.realpath"]
