"""No import cycles at module load among backend modules (Batch 3 gate)."""

import ast
import pathlib
import sys


def _cycles():
    root = pathlib.Path(__file__).resolve().parent.parent / "backend"

    mods = {}
    for p in root.rglob("*.py"):
        name = ".".join(p.relative_to(root.parent).with_suffix("").parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        mods[name] = p
    graph = {}
    for name, p in mods.items():
        deps = set()
        for node in ast.parse(p.read_text()).body:  # module level only, not inside functions
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in mods:
                        deps.add(a.name)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                if node.module in mods:
                    deps.add(node.module)
                for a in node.names:
                    full = f"{node.module}.{a.name}"
                    if full in mods:
                        deps.add(full)
            elif isinstance(node, (ast.If, ast.Try)):
                pass
        graph[name] = deps - {name}
    # strongly connected components (Tarjan)
    index, low, stack, on, sccs, i = {}, {}, [], set(), [], [0]
    sys.setrecursionlimit(10000)

    def strong(v):
        index[v] = low[v] = i[0]
        i[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                sccs.append(sorted(comp))

    for v in graph:
        if v not in index:
            strong(v)
    return sccs


def test_no_import_cycles_at_module_load():
    assert _cycles() == [], "import inside the function that needs it, or move the shared code down a layer"
