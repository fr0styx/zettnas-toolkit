"""ARC-27: the contributor docs name only files, modules and settings that exist.

AGENTS.md's file tree and the repository paths, dotted Python names and environment
variables written in backticks in AGENTS.md, CONTRIBUTING.md and docs/ARCHITECTURE.md are
checked against the tree, so a rename or a removal has to update the docs too.
"""

import importlib
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = ["AGENTS.md", "CONTRIBUTING.md", "docs/ARCHITECTURE.md"]
TOP = ("backend", "frontend", "scripts", "tests", "docs", "contrib", ".github", "static")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def tree_paths(text):
    """The paths in a ``├── name  # note`` tree that starts with ``<repo>/``."""
    out, stack = [], []
    for block in re.findall(r"```\n(\S+/\n.*?)```", text, re.S):
        for line in block.splitlines()[1:]:
            m = re.match(r"^((?:│   |    )*)(?:├── |└── )([^#]+?)\s*(?:#.*)?$", line)
            if not m:
                continue
            depth = len(m.group(1)) // 4
            del stack[depth:]
            name = m.group(2).strip()
            stack.append(name.rstrip("/"))
            out.append("/".join(stack) + ("/" if name.endswith("/") else ""))
    return out


def test_agents_tree_lists_real_files():
    missing = [p for p in tree_paths(_read("AGENTS.md")) if not os.path.exists(os.path.join(ROOT, p))]
    assert not missing, f"AGENTS.md names files that don't exist: {missing}"


@pytest.mark.parametrize("doc", DOCS)
def test_backticked_paths_and_names_exist(doc):
    text = _read(doc)
    problems = []
    for ref in sorted(set(re.findall(r"`([^`\s]+)`", text))):
        ref = ref.rstrip(".,:;")
        path = ref.split(":")[0].split("::")[0]
        if path.startswith(TOP) and "/" in path and not any(c in path for c in "<>*{"):
            if not os.path.exists(os.path.join(ROOT, path)):
                problems.append(ref)
        elif re.fullmatch(r"backend(\.\w+)+", ref):
            parts = ref.split(".")
            for i in range(len(parts), 1, -1):
                try:
                    obj = importlib.import_module(".".join(parts[:i]))
                except ImportError:
                    continue
                try:
                    for attr in parts[i:]:
                        obj = getattr(obj, attr)
                except AttributeError:
                    problems.append(ref)
                break
            else:
                problems.append(ref)
    assert not problems, f"{doc} names things that don't exist: {problems}"


def test_tree_parser():
    text = "```\nrepo/\n├── a/\n│   ├── b.py   # x\n│   └── c/\n│       └── d.js\n└── e.md\n```\n"
    assert tree_paths(text) == ["a/", "a/b.py", "a/c/", "a/c/d.js", "e.md"]
