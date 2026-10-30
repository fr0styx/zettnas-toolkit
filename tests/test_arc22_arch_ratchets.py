"""ARC-22, ARC-23: layering, private-name imports and function size may only get better
(scripts/arch_ratchets.py; tests/arch_baseline.json)."""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("arch_ratchets", ROOT / "scripts" / "arch_ratchets.py")
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)


def test_nothing_is_worse_than_the_baseline():
    import json

    base = json.loads((ROOT / "tests" / "arch_baseline.json").read_text(encoding="utf-8"))
    found = ar.problems(ar.measure(), base)
    assert not found, "\n".join(found)


def test_the_rules():
    assert ar.layer("backend.config") == "core" and ar.layer("backend.services.x") == "services"
    assert ar.layer("backend.main") == "app" and ar.layer("fastapi") is None
    base = {
        "upward_imports": ["backend.db -> backend.services.a"],
        "private_imports": {"m": 2},
        "long_functions": {"m.f": 200},
    }
    now = {
        "upward_imports": ["backend.db -> backend.services.a", "backend.state -> backend.api.x"],
        "private_imports": {"m": 3},
        "long_functions": {"m.f": 201, "m.g": 151, "m.h": 150},
    }
    found = ar.problems(now, base)
    assert any("backend.state -> backend.api.x" in p for p in found)
    assert any("m imports 3 private" in p for p in found)
    assert any(p.startswith("m.f is 201") for p in found) and any(p.startswith("m.g is 151") for p in found)
    assert not any(p.startswith("m.h") for p in found)


def test_the_baseline_is_tight():
    """NARC-3: when code gets better, the baseline follows (python scripts/arch_ratchets.py --update)."""
    import json

    base = json.loads((ROOT / "tests" / "arch_baseline.json").read_text(encoding="utf-8"))
    loose = ar.slack(ar.measure(), base)
    assert not loose, "\n".join(loose)


def test_slack_rules():
    base = {
        "upward_imports": ["a -> b"],
        "long_functions": {"m.f": 300, "m.gone": 200, "m.ok": 160},
        "broad_excepts": {"m": 5},
    }
    now = {
        "upward_imports": [],
        "private_imports": {},
        "long_functions": {"m.f": 200, "m.ok": 150},
        "broad_excepts": {"m": 4},
    }
    found = ar.slack(now, base)
    assert any(p.startswith("m.f is 200 lines but 300") for p in found)
    assert any(p.startswith("m.gone is gone") for p in found)
    assert any("a -> b is gone" in p for p in found)
    assert not any(p.startswith("m.ok") or p.startswith("m: broad") for p in found)
