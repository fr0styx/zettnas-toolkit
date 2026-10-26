"""ARC-6: import cycles counting imports inside functions may shrink, never grow."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import import_cycles as ic  # noqa: E402


def test_no_new_or_larger_import_cycles():
    problems = ic.regressions(ic.cycles(), ic.load_baseline())
    assert not problems, (
        "Move the shared code down a layer, or pass a callback instead of importing upwards:\n" + "\n".join(problems)
    )


def test_the_cycle_finder():
    g = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}, "e": {"f"}, "f": {"e"}, "g": set()}
    assert ic.cycles(g) == [["a", "b", "c"], ["e", "f"]]
    base = [["a", "b", "c"], ["e", "f"]]
    assert ic.regressions([["a", "b"]], base) == []  # shrinking is fine
    assert ic.regressions([["a", "b", "c", "d"]], base) == ["a cycle through 4 modules; new in it: d"]
    assert ic.regressions([["x", "y"]], base) == ["a cycle through 2 modules; new in it: x, y"]


def test_imports_inside_functions_and_relative_ones_count(tmp_path, monkeypatch):
    pkg = tmp_path / "backend"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "sub" / "__init__.py").write_text("")
    (pkg / "low.py").write_text("def f():\n    from backend.sub import high\n")
    (pkg / "sub" / "high.py").write_text(
        "from .. import low\nimport importlib\nimportlib.import_module('backend.low')\n"
    )
    monkeypatch.setattr(ic, "ROOT", tmp_path)
    monkeypatch.setattr(ic, "BACKEND", pkg)
    assert ic.cycles() == [["backend.low", "backend.sub.high"]]


def test_a_damaged_settings_file_still_raises_an_event(tmp_path, monkeypatch):
    from backend import fsutil, state

    seen = []
    monkeypatch.setattr(state, "add_event", lambda *a, **k: seen.append(a))
    bad = tmp_path / "x.json"
    bad.write_text("{not json")
    assert fsutil.read_json(str(bad), {"ok": 1}) == {"ok": 1}
    assert seen and seen[0][1] == "Damaged settings file"
    assert state._record_damaged_file in fsutil.CORRUPT_LISTENERS
