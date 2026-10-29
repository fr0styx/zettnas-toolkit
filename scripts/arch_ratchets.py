"""Architecture ratchets (ARC-22, ARC-23): layering, private-name imports and function size.

Layers, lowest first: core (backend/*.py), hardware, services, api, app (backend/main.py). A
module may import its own layer or a lower one; an import upwards (a service reaching into the
API, a hardware module calling a service) is recorded in tests/arch_baseline.json, and a new one
fails. So do a module importing more private names (_like_this) from other modules than it does
today, and a function longer than 150 lines that isn't in the baseline, or a listed one that
grows. Lazy imports inside functions count too.

    python scripts/arch_ratchets.py           # report what is over the baseline (exit 1)
    python scripts/arch_ratchets.py --update  # record today's numbers after a clean-up
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "arch_baseline.json"
RANK = {"core": 0, "hardware": 1, "services": 2, "api": 3, "app": 4}
MAX_LINES = 150


def layer(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != "backend" or len(parts) < 2:
        return None
    if parts[1] in ("api", "services", "hardware"):
        return parts[1]
    return "app" if parts[1] == "main" else "core"


def _module_of(path: pathlib.Path) -> str:
    mod = ".".join(path.relative_to(ROOT).with_suffix("").parts)
    return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod


def _function_sizes(tree: ast.AST, prefix: str = ""):
    """(qualified name, lines) for every function, nested ones as outer.inner."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}{node.name}"
            yield name, node.end_lineno - node.lineno + 1
            yield from _function_sizes(node, name + ".")
        elif isinstance(node, ast.ClassDef):
            yield from _function_sizes(node, f"{prefix}{node.name}.")
        else:
            yield from _function_sizes(node, prefix)


def measure() -> dict:
    upward: set[str] = set()
    private: dict[str, int] = {}
    long_functions: dict[str, int] = {}
    for path in sorted((ROOT / "backend").rglob("*.py")):
        mod = _module_of(path)
        me = layer(mod)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        n_private = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "backend":
                targets = [f"backend.{a.name}" for a in node.names] if node.module == "backend" else [node.module]
                for target in targets:
                    them = layer(target)
                    if me and them and RANK[them] > RANK[me]:
                        upward.add(f"{mod} -> {target}")
                n_private += sum(1 for a in node.names if a.name.startswith("_") and not a.name.startswith("__"))
            elif isinstance(node, ast.Import):
                for a in node.names:
                    them = layer(a.name)
                    if me and them and RANK[them] > RANK[me]:
                        upward.add(f"{mod} -> {a.name}")
        for name, size in _function_sizes(tree):
            if size > MAX_LINES:
                key = f"{mod}.{name}"
                long_functions[key] = max(size, long_functions.get(key, 0))
        if n_private:
            private[mod] = n_private
    return {"upward_imports": sorted(upward), "private_imports": private, "long_functions": long_functions}


def problems(now: dict, base: dict) -> list[str]:
    out = []
    for edge in sorted(set(now["upward_imports"]) - set(base.get("upward_imports", []))):
        out.append(f"new upward import {edge}: move the shared code down a layer, or pass it in")
    for mod, n in now["private_imports"].items():
        if n > base.get("private_imports", {}).get(mod, 0):
            out.append(
                f"{mod} imports {n} private names (baseline {base.get('private_imports', {}).get(mod, 0)}): export what is shared"
            )
    for fn, n in now["long_functions"].items():
        allowed = base.get("long_functions", {}).get(fn, MAX_LINES)
        if n > allowed:
            out.append(f"{fn} is {n} lines (limit {allowed}): split it")
    return out


def main(argv: list[str]) -> int:
    now = measure()
    if "--update" in argv:
        BASELINE.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"wrote {BASELINE.relative_to(ROOT)}: {len(now['upward_imports'])} upward imports, "
            f"{sum(now['private_imports'].values())} private-name imports, {len(now['long_functions'])} functions over {MAX_LINES} lines"
        )
        return 0
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    found = problems(now, base)
    for p in found:
        print(p)
    if not found:
        print("architecture ratchets hold")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
