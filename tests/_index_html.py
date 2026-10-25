"""The page markup as the browser ends up with it: index.html with Mission Control's markup
(frontend/src/windows/management-window.html, inserted when first needed, FE-04) in its slot."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def with_management_markup(page: str) -> str:
    mc = (ROOT / "frontend" / "src" / "windows" / "management-window.html").read_text(encoding="utf-8")
    drawer = (ROOT / "frontend" / "src" / "windows" / "drawer.html").read_text(encoding="utf-8")
    page = re.sub(r'<template id="management-window-slot">.*?</template>', lambda _m: mc, page, count=1, flags=re.S)
    # the hardware-settings drawer is inserted with its code too (B6 first-load budget)
    return page.replace('<template id="led-drawer-slot"></template>', drawer, 1)


def read_index_html() -> str:
    return with_management_markup((ROOT / "frontend" / "index.html").read_text(encoding="utf-8"))
