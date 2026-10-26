"""Per-file UI ratchets (UX-11): inline styles and unstyled buttons may only go down.

For each frontend source file it counts

    styles   style="..." attributes in markup (use a class or a primitive instead)
    buttons  <button> elements without a class (use .btn-pill-toggle or uiButton)

and compares them with tests/ui_ratchets.json. A file may never go above its recorded
count; a new file starts at zero. After cleaning up, record the lower counts:

    python scripts/ui_ratchets.py           # report files above their baseline (exit 1)
    python scripts/ui_ratchets.py --update  # write the current counts as the new baseline
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
BASELINE = os.path.join(ROOT, "tests", "ui_ratchets.json")
STYLE_ATTR = re.compile(r"""\sstyle=["']""")
BUTTON = re.compile(r"<button\b([^>]*)>")


def sources() -> list[str]:
    pats = ("src/**/*.js", "src/**/*.html")
    files = [f for p in pats for f in glob.glob(os.path.join(FRONTEND, p), recursive=True)]
    files.append(os.path.join(FRONTEND, "index.html"))
    return sorted(f for f in files if "__tests__" not in f and os.sep + "locales" + os.sep not in f)


def counts_for(text: str) -> dict[str, int]:
    buttons = sum(1 for m in BUTTON.finditer(text) if not re.search(r"\sclass=", m.group(1)))
    return {"styles": len(STYLE_ATTR.findall(text)), "buttons": buttons}


def current() -> dict[str, dict[str, int]]:
    out = {}
    for f in sources():
        with open(f, encoding="utf-8") as fh:
            c = counts_for(fh.read())
        if any(c.values()):
            out[os.path.relpath(f, ROOT).replace(os.sep, "/")] = c
    return out


def load_baseline() -> dict[str, dict[str, int]]:
    try:
        with open(BASELINE, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def over(now: dict, base: dict) -> list[str]:
    problems = []
    for f, c in sorted(now.items()):
        b = base.get(f, {})
        for k, n in c.items():
            if n > b.get(k, 0):
                problems.append(f"{f}: {n} {k} (baseline {b.get(k, 0)})")
    return problems


def main(argv) -> int:
    now = current()
    if "--update" in argv:
        with open(BASELINE, "w", encoding="utf-8") as fh:
            json.dump(now, fh, indent=1, sort_keys=True)
            fh.write("\n")
        total = {k: sum(c[k] for c in now.values()) for k in ("styles", "buttons")}
        print(
            f"wrote {os.path.relpath(BASELINE, ROOT)}: {total['styles']} inline styles, {total['buttons']} unstyled buttons"
        )
        return 0
    problems = over(now, load_baseline())
    for p in problems:
        print(p)
    if problems:
        print("Use a class, a --zn- token or a primitive (frontend/src/ui/primitives.js) instead.")
        return 1
    print("UI ratchets hold")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
