"""The endpoint list in docs/API.md, generated from the OpenAPI document (ARC-25).

    python scripts/api_reference.py           # compare (exit 1 when docs/API.md is out of date)
    python scripts/api_reference.py --update  # rewrite the generated section

Only the part between the BEGIN/END markers is generated; the rest of API.md is written by hand.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "API.md")
BEGIN = "<!-- BEGIN generated endpoints: python scripts/api_reference.py --update -->"
END = "<!-- END generated endpoints -->"
sys.path.insert(0, ROOT)
os.environ.setdefault("TESTING", "1")
METHODS = ("get", "post", "put", "patch", "delete")


def _summary(op: dict) -> str:
    text = (op.get("description") or "").strip().split("\n\n")[0].replace("\n", " ").strip()
    if not text:
        text = op.get("summary", "")
    text = text.split(". ")[0].rstrip(".")
    if len(text) > 140:
        text = text[:137].rstrip() + "…"
    return text.replace("|", "\\|")


def _access(op: dict) -> str:
    if op.get("security") == []:
        return "public"
    scopes = op.get("x-required-scopes")
    if not scopes:
        return "signed in"
    listed = ", ".join(f"`{s}`" for s in scopes)
    return listed if len(scopes) == 1 else "any of " + listed


def render(schema: dict) -> str:
    groups: dict[str, list[tuple[str, str, dict]]] = {}
    for path, ops in schema.get("paths", {}).items():
        if not path.startswith(("/api/v1/", "/redfish")):
            continue
        for method in METHODS:
            op = ops.get(method)
            if op is None:
                continue
            tag = (op.get("tags") or ["Other"])[0]
            groups.setdefault(tag, []).append((path, method, op))
    total = sum(len(v) for v in groups.values())
    out = [
        BEGIN,
        "",
        f"{total} operations. **Access** is what the session or token needs: `public` needs nothing,"
        " `signed in` any valid session or token, otherwise one of the listed scopes."
        " ⏱ marks operations that can answer 429.",
        "",
    ]
    for tag in sorted(groups):
        out += [f"### {tag}", "", "| Method | Path | Access | What it does |", "| :--- | :--- | :--- | :--- |"]
        for path, method, op in sorted(groups[tag]):
            limited = " ⏱" if "429" in op.get("responses", {}) else ""
            out.append(f"| `{method.upper()}` | `{path}` | {_access(op)}{limited} | {_summary(op)} |")
        out.append("")
    out.append(END)
    return "\n".join(out)


def current_doc() -> str:
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


def updated(doc: str, section: str) -> str:
    a, b = doc.index(BEGIN), doc.index(END) + len(END)
    return doc[:a] + section + doc[b:]


def main(argv) -> int:
    from app import app

    doc = current_doc()
    new = updated(doc, render(app.openapi()))
    if "--update" in argv:
        with open(DOC, "w", encoding="utf-8") as fh:
            fh.write(new)
        print("wrote docs/API.md")
        return 0
    if new != doc:
        print("docs/API.md is out of date: python scripts/api_reference.py --update")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
