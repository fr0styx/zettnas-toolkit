"""NARC-5: quality gates fail when they can\x27t measure, instead of passing."""

import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _silent_except():
    spec = importlib.util.spec_from_file_location("silent_except", os.path.join(ROOT, "scripts", "silent_except.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_file_that_doesnt_parse_fails_the_count(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n    pass\n")
    with pytest.raises(SystemExit, match="can.t parse"):
        _silent_except().silent_handlers(str(bad))


def test_the_type_ratchet_needs_tsc():
    with open(os.path.join(ROOT, "frontend", "scripts", "checkjs-ratchet.mjs"), encoding="utf-8") as f:
        src = f.read()
    assert "TypeScript is not installed" in src and "did not run properly" in src
