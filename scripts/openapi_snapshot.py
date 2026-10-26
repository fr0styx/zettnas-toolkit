"""The /api/v1 contract as a reviewed file (ARC-7).

docs/openapi-v1.json is the OpenAPI document of the public API (/api/v1: tokens, Home
Assistant, MCP). tests/test_arc7_openapi_snapshot.py fails when the live schema differs, so
a contract change is always deliberate and shows up in review. Removed paths or methods
break API clients: say so in the release notes.

    python scripts/openapi_snapshot.py           # compare (exit 1 on a difference)
    python scripts/openapi_snapshot.py --update  # write the current schema
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(ROOT, "docs", "openapi-v1.json")
sys.path.insert(0, ROOT)
os.environ.setdefault("TESTING", "1")


def current() -> dict:
    from app import app

    schema = json.loads(json.dumps(app.openapi(), sort_keys=True))
    schema.get("info", {}).pop("version", None)  # changes every release, not part of the contract
    return schema


def load() -> dict:
    try:
        with open(SNAPSHOT, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def operations(schema: dict) -> set[str]:
    return {f"{m.upper()} {p}" for p, ops in schema.get("paths", {}).items() for m in ops if not m.startswith("x-")}


def differences(old: dict, new: dict) -> list[str]:
    if old == new:
        return []
    out = [f"removed: {op}" for op in sorted(operations(old) - operations(new))]
    out += [f"added: {op}" for op in sorted(operations(new) - operations(old))]
    for path, ops in sorted(new.get("paths", {}).items()):
        for method, spec in sorted(ops.items()):
            before = old.get("paths", {}).get(path, {}).get(method)
            if before is not None and before != spec:
                out.append(f"changed: {method.upper()} {path}")
    old_c = old.get("components", {}).get("schemas", {})
    new_c = new.get("components", {}).get("schemas", {})
    out += [f"changed: schema {name}" for name in sorted(set(old_c) | set(new_c)) if old_c.get(name) != new_c.get(name)]
    return out or ["the document changed outside paths and schemas"]


def main(argv) -> int:
    new = current()
    if "--update" in argv:
        with open(SNAPSHOT, "w", encoding="utf-8") as fh:
            json.dump(new, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print(f"wrote {os.path.relpath(SNAPSHOT, ROOT)}: {len(operations(new))} operations")
        return 0
    diff = differences(load(), new)
    for d in diff:
        print(d)
    return 1 if diff else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
