"""Buttons styled inline onto the system button (UX-11).

A <button> with no class whose inline style paints a button look (background, border,
padding, font) becomes .btn-pill-toggle with the matching variant (UX-6):

    background var(--brand...)      -> is-primary
    a red background or text        -> is-danger
    transparent/none, no border     -> is-ghost (text links with tiny padding stay as they are)
    anything else                   -> the default (secondary) look
    small padding or the xs font    -> + is-small

Layout declarations (flex, margin, width, display, ...) stay inline. Buttons with a class,
with template expressions in their style, or without a button look are left alone.

    python scripts/ui_buttons.py          # dry run: what would change
    python scripts/ui_buttons.py --write  # rewrite the sources
"""

from __future__ import annotations

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
LOOK = {
    "background",
    "background-color",
    "border",
    "border-color",
    "border-radius",
    "color",
    "padding",
    "font-size",
    "font-weight",
    "cursor",
    "line-height",
    "transition",
}
BUTTON = re.compile(r"<button\b([^>]*)>")
STYLE = re.compile(r"""\sstyle=(["'])(.*?)\1""", re.S)


def sources() -> list[str]:
    pats = ("src/**/*.js", "src/**/*.html")
    files = [f for p in pats for f in glob.glob(os.path.join(FRONTEND, p), recursive=True)]
    files.append(os.path.join(FRONTEND, "index.html"))
    return sorted(f for f in files if "__tests__" not in f and os.sep + "locales" + os.sep not in f)


def declarations(style: str) -> list[tuple[str, str]]:
    out = []
    for part in style.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out.append((k.strip().lower(), v.strip()))
    return out


def variant(decls: dict[str, str]) -> str | None:
    """The button variant an inline style asks for, or None when it is not a button look."""
    bg = (decls.get("background") or decls.get("background-color") or "").lower()
    look = [k for k in decls if k in LOOK]
    if len(look) < 3 or not ("padding" in decls or bg or "border" in decls):
        return None
    if "gradient" in bg or "url(" in bg:
        return None  # a picture or a gradient: its own look
    text = decls.get("color", "").lower()
    pad = decls.get("padding", "")
    first = re.match(r"\s*(\d+)px", pad)
    bare = bg in ("", "none", "transparent") and decls.get("border", "none").lower() in ("none", "0", "transparent")
    if bare and ("underline" in decls.get("text-decoration", "") or not first or int(first.group(1)) <= 4):
        return None  # a text link, not a button: it keeps its own look
    if "--brand" in bg or "--accent" in bg:
        v = "is-primary"
    elif any(r in bg + text for r in ("danger", "crit", "#ef4444", "#f87171", "235, 87, 87", "239, 68, 68")):
        v = "is-danger"
    elif bare:
        v = "is-ghost"
    elif bg and not any(
        t in bg for t in ("glaze", "255, 255, 255", "rgba(255,255,255", "transparent", "none", "--zn-surface", "--card")
    ):
        return None  # a coloured fill this tool cannot name: leave it
    else:
        v = ""
    if "--zn-fs-xs" in decls.get("font-size", "") or (first and int(first.group(1)) <= 4):
        v = (v + " is-small").strip()
    return v


def rewrite_button(attrs: str) -> str | None:
    if re.search(r"""\sclass=""", attrs):
        return None
    m = STYLE.search(attrs)
    if not m or "${" in m.group(2):
        return None
    decls = declarations(m.group(2))
    v = variant(dict(decls))
    if v is None:
        return None
    keep = "; ".join(f"{k}: {val}" for k, val in decls if k not in LOOK)
    cls = ("btn-pill-toggle " + v).strip()
    q = m.group(1)
    new_style = f" style={q}{keep};{q}" if keep else ""
    return attrs[: m.start()] + f" class={q}{cls}{q}" + new_style + attrs[m.end() :]


def rewrite(text: str) -> tuple[str, int]:
    n = 0

    def one(m):
        nonlocal n
        new = rewrite_button(m.group(1))
        if new is None:
            return m.group(0)
        n += 1
        return f"<button{new}>"

    return BUTTON.sub(one, text), n


def main(argv) -> int:
    write = "--write" in argv
    total = 0
    for f in sources():
        with open(f, encoding="utf-8") as fh:
            old = fh.read()
        new, n = rewrite(old)
        if n:
            total += n
            print(f"{n:4d}  {os.path.relpath(f, ROOT)}")
            if write:
                with open(f, "w", encoding="utf-8") as fh:
                    fh.write(new)
    print(f"{total} buttons {'rewritten' if write else 'to rewrite'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
