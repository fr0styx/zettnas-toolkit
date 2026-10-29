"""ARC-33: the SMART caches and the event log change only through the locked accessors in
backend/state.py, so the pollers, Drive Health and the API never write past each other."""

import ast
import pathlib
import threading

from backend.state import Z_STATE, SmartState, clear_events, events_snapshot

ROOT = pathlib.Path(__file__).resolve().parents[1] / "backend"
FLAT = {
    "cached_smart_data",
    "cached_smart_time",
    "disk_risk",
    "last_smart_scan",
    "active_smart_tests",
    "drive_verdicts",
}
FIELDS = {"cached_data", "cached_time", "disk_risk", "last_scan", "active_tests", "verdicts"}
MUTATORS = {"pop", "update", "clear", "setdefault", "popitem", "__setitem__", "__delitem__"}


def _is_state_map(node: ast.AST) -> bool:
    """Z_STATE.cached_smart_data, Z_STATE.smart.cached_data (or a subscript of either)."""
    while isinstance(node, ast.Subscript):
        node = node.value
    if not isinstance(node, ast.Attribute):
        return False
    if node.attr in FLAT and isinstance(node.value, ast.Name) and node.value.id == "Z_STATE":
        return True
    return (
        node.attr in FIELDS
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "smart"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "Z_STATE"
    )


def _writes(tree: ast.AST):
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        elif isinstance(node, ast.Delete):
            targets = node.targets
        for t in targets:
            if isinstance(t, ast.Subscript) and _is_state_map(t):
                yield node.lineno
            if isinstance(t, ast.Attribute) and t.attr == "event_log":
                yield node.lineno
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in MUTATORS:
            if _is_state_map(node.func.value):
                yield node.lineno


def test_no_module_writes_the_shared_maps_directly():
    found = []
    for path in ROOT.rglob("*.py"):
        if path.name == "state.py" and path.parent == ROOT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found += [f"{path.relative_to(ROOT.parent)}:{line}" for line in _writes(tree)]
    assert not found, (
        "write through Z_STATE.smart.set_*/start_test/end_test or the event helpers instead:\n" + "\n".join(found)
    )


def test_accessors_write_under_the_lock_and_snapshots_are_copies():
    s = SmartState()
    s.set_reading("sda", 35, "ok")
    s.set_time("sda", 1.0)
    s.set_scanned("sda", 2.0)
    s.set_risk("sda", {"risk": "low"})
    s.set_verdict("sda", {"verdict": "ok"})
    s.start_test("sda", {"last_pct": 0})
    s.update_test("sda", last_pct=40)
    s.update_test("sdb", last_pct=10)  # no test running there: nothing to update
    assert s.cached_data["sda"] == (35, "ok") and s.cached_time["sda"] == 1.0 and s.last_scan["sda"] == 2.0
    assert s.active_tests == {"sda": {"last_pct": 40}}
    copy = s.snapshot("active_tests")
    s.end_test("sda")
    assert copy == {"sda": {"last_pct": 40}} and s.active_tests == {}

    # a writer holding the lock blocks the accessors (they share one lock)
    s.lock.acquire()
    done = threading.Event()
    threading.Thread(target=lambda: (s.set_reading("sdc", 1, "ok"), done.set()), daemon=True).start()
    assert not done.wait(0.2)
    s.lock.release()
    assert done.wait(2)


def test_event_log_helpers():
    with Z_STATE.lock:
        before = list(Z_STATE.event_log)
    try:
        with Z_STATE.lock:
            Z_STATE.event_log.insert(0, {"title": "x"})
        snap = events_snapshot()
        assert snap[0]["title"] == "x"
        snap.clear()
        assert events_snapshot(), "the snapshot is a copy"
        clear_events()
        assert events_snapshot() == []
    finally:
        with Z_STATE.lock:
            Z_STATE.event_log = before
