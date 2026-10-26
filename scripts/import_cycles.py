"""Import cycles among backend modules, counting imports inside functions too (ARC-6).

The module-load gate (tests/test_arch2_no_import_cycles.py) keeps import time cycle-free.
Imports inside functions are how code dodges that gate, so the real dependency tangles
hide there. This tool follows every import: module level, inside functions and classes,
relative ones and importlib.import_module("backend...") with a literal name. Each
strongly connected group of modules (a set that can all reach each other) is a cycle.

tests/import_cycles.json records today's groups. The test fails when a new group forms
or a group gains modules; shrinking is always fine (record it with --update).

    python scripts/import_cycles.py           # list the groups and compare with the baseline
    python scripts/import_cycles.py --update  # record the current groups as the baseline
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
BASELINE = ROOT / "tests" / "import_cycles.json"


def modules() -> dict[str, pathlib.Path]:
    mods = {}
    for p in BACKEND.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        name = ".".join(p.relative_to(ROOT).with_suffix("").parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        mods[name] = p
    return mods


def _resolve(module: str | None, level: int, here: str, is_pkg: bool) -> str | None:
    if level == 0:
        return module
    base = here.split(".") if is_pkg else here.split(".")[:-1]
    if level > 1:
        base = base[: -(level - 1)]
    return ".".join(base + ([module] if module else []))


def dependencies(name: str, path: pathlib.Path, mods: dict[str, pathlib.Path]) -> set[str]:
    deps: set[str] = set()
    is_pkg = path.name == "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                # import backend.x.y also loads backend.x
                parts = a.name.split(".")
                for i in range(len(parts), 1, -1):
                    if ".".join(parts[:i]) in mods:
                        deps.add(".".join(parts[:i]))
                        break
        elif isinstance(node, ast.ImportFrom):
            target = _resolve(node.module, node.level, name, is_pkg)
            if not target:
                continue
            if target in mods:
                deps.add(target)
            for a in node.names:
                full = f"{target}.{a.name}"
                if full in mods:
                    deps.add(full)
        elif (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", getattr(node.func, "id", "")) == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value in mods
        ):
            deps.add(node.args[0].value)
    return deps - {name}


def graph() -> dict[str, set[str]]:
    mods = modules()
    return {name: dependencies(name, p, mods) for name, p in mods.items()}


def cycles(g: dict[str, set[str]] | None = None) -> list[list[str]]:
    """Strongly connected groups of two or more modules (Tarjan, iterative)."""
    g = graph() if g is None else g
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in sorted(g):
        if root in index:
            continue
        work = [(root, iter(sorted(g.get(root, ()))))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(g.get(w, ())))))
                    advanced = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp))
    return sorted(out, key=lambda c: (-len(c), c))


def load_baseline() -> list[list[str]]:
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def regressions(now: list[list[str]], base: list[list[str]]) -> list[str]:
    """Groups that are new or larger than any baseline group they overlap."""
    problems = []
    for comp in now:
        s = set(comp)
        if not any(s <= set(b) for b in base):
            grown = max(base, key=lambda b: len(s & set(b)), default=[])
            extra = sorted(s - set(grown))
            problems.append(f"a cycle through {len(comp)} modules; new in it: {', '.join(extra[:8])}")
    return problems


def main(argv) -> int:
    now = cycles()
    if "--update" in argv:
        BASELINE.write_text(json.dumps(now, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {os.path.relpath(BASELINE, ROOT)}: {len(now)} groups, {sum(map(len, now))} modules")
        return 0
    for comp in now:
        print(f"{len(comp):4d}  {', '.join(comp[:6])}{' ...' if len(comp) > 6 else ''}")
    problems = regressions(now, load_baseline())
    for p in problems:
        print("NEW:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
