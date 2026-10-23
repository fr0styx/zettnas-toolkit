"""Buttons on the brand colour use the dark contrast foreground, not white (UX-5).

White on the default brand cyan is 1.41:1; --accent-contrast-fg (#0b1118) is 13.5:1.
"""

import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parent.parent / "frontend"
STYLE = re.compile(r"""style=(["'])(.*?)\1""", re.S)
WHITE = re.compile(r"(?<![-\w])color\s*:\s*(?:#fff(?:fff)?|white)\b", re.I)


def test_no_white_text_on_brand_backgrounds():
    files = [
        FRONTEND / "index.html",
        *FRONTEND.glob("src/windows/*.html"),
        *FRONTEND.glob("src/components/*.js"),
        *FRONTEND.glob("src/*.js"),
    ]
    offenders = []
    for f in files:
        for m in STYLE.finditer(f.read_text(encoding="utf-8")):
            style = m.group(2)
            bg = re.search(r"background(?:-color)?\s*:\s*([^;]+)", style)
            if bg and "--brand" in bg.group(1) and WHITE.search(style):
                offenders.append(f"{f.relative_to(FRONTEND)}: {style[:80]}")
    assert not offenders, "white text on the brand colour:\n" + "\n".join(offenders)
