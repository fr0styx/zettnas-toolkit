"""Counts (and optionally fixes) silent `except ...: pass` handlers in the backend (ARC-01).

python scripts/silent_except.py            # fail if more than the baseline
python scripts/silent_except.py --list     # show them
python scripts/silent_except.py --update   # record the current count
"""

import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "scripts", "silent-except-baseline.json")


def silent_handlers(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            out.append(node)
    return out


def scan():
    found = []
    for dp, _, fs in os.walk(os.path.join(ROOT, "backend")):
        if "__pycache__" in dp:
            continue
        for f in sorted(fs):
            if f.endswith(".py"):
                p = os.path.join(dp, f)
                found += [(os.path.relpath(p, ROOT), h.lineno) for h in silent_handlers(p)]
    return found


def main():
    found = scan()
    if "--list" in sys.argv:
        for f, line in found:
            print(f"{f}:{line}")
    if "--update" in sys.argv:
        with open(BASELINE, "w") as fh:
            json.dump({"silent_except_pass": len(found)}, fh)
            fh.write("\n")
        print(f"recorded {len(found)} silent except/pass handlers")
        return 0
    base = {"silent_except_pass": 10**9}
    if os.path.exists(BASELINE):
        with open(BASELINE) as fh:
            base = json.load(fh)
    if len(found) > base["silent_except_pass"]:
        print(
            f"✗ {len(found)} silent 'except: pass' handlers (baseline {base['silent_except_pass']}); log or handle the error"
        )
        return 1
    print(f"silent except/pass: {len(found)} (baseline {base['silent_except_pass']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
