"""UX-9: nothing a person reads is smaller than 13px; sizes come from a six-step scale.

Rules that draw the LCD screen, its mini previews, the desktop twin and the chassis drawing keep
their exact sizes (they are scaled pictures of fixed-size hardware), and so do canvas/SVG text."""

import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
DRY = "--dry" in sys.argv
SMALL = r"(?:[0-9]|1[0-2])(?:\.\d+)?px"
TOKEN = "var(--zn-fs-xs)"
LCD_SEL = re.compile(
    r"#screen|lcd(?!-(?:style|theme)-chip)|mini-|\.dt-|desktop-twin|chassis-|bay-|\.dn\b|\.dt\b|disk-tile|#console-window|screensaver-clock"
    r"|\.nas-name|\.pill\b|\.clock\b|\.bmc-|\.lph-|\.nio-|\.uc-|\.sl-|\.slot-|\.fv\b|\.u\b|\.m2-|\.h-left|card-disks|\.io-dot|standby-zzz",
    re.I,
)
SKIP_FILES = {
    "10-lcd-preview.css",
    "lcd-direct.css",
    "vm-console-direct.css",
    "dashboard.js",
    "mini-preview.js",
    "58-light-palette.css",
}
counts = {}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def fix_decls(text):
    n = 0

    def rep_size(m):
        nonlocal n
        n += 1
        return m.group(1) + TOKEN

    text = re.sub(r"(font-size\s*:\s*)" + SMALL, rep_size, text)

    # font shorthand: "font: 600 11px/1.2 ..." -> the size part only
    def rep_short(m):
        nonlocal n
        n += 1
        return m.group(1) + TOKEN + m.group(2)

    text = re.sub(
        r"(\bfont\s*:\s*(?:[a-z0-9-]+\s+)*?)" + SMALL + r"((?:/[\d.]+[a-z%]*)?\s+[a-zA-Z\"'-])", rep_short, text
    )
    return text, n


def do_css(path):
    s = _read(path)
    out, pos, total = [], 0, 0
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", s):
        sel, body = m.group(1), m.group(2)
        if LCD_SEL.search(sel):
            continue
        new, n = fix_decls(body)
        if n:
            out.append(s[pos : m.start(2)] + new)
            pos = m.end(2)
            total += n
    out.append(s[pos:])
    return "".join(out), total


def do_markup(path):
    s = _read(path)
    total = 0

    def in_style(m):
        nonlocal total
        new, n = fix_decls(m.group(0))
        total += n
        return new

    # inline style="..." and template-literal style strings; JS style props
    s2 = re.sub(r"style\s*=\s*\"[^\"]*\"|style\s*=\s*'[^']*'|cssText\s*=\s*[`'\"][^`'\"]*[`'\"]", in_style, s)

    def js_prop(m):
        nonlocal total
        total += 1
        return m.group(1) + TOKEN + m.group(2)

    s2 = re.sub(r"(\bfontSize\s*[=:]\s*['\"])" + SMALL + r"(['\"])", js_prop, s2)

    # <style> blocks inside html/js templates
    def style_block(m):
        nonlocal total
        inner = m.group(2)
        out, pos = [], 0
        for r in re.finditer(r"([^{}]+)\{([^{}]*)\}", inner):
            if LCD_SEL.search(r.group(1)):
                continue
            new, n = fix_decls(r.group(2))
            if n:
                out.append(inner[pos : r.start(2)] + new)
                pos = r.end(2)
                total += n
        out.append(inner[pos:])
        return m.group(1) + "".join(out) + m.group(3)

    s2 = re.sub(r"(<style[^>]*>)(.*?)(</style>)", style_block, s2, flags=re.S)
    return s2, total


for dirpath, _, names in os.walk(ROOT + "/src"):
    if "__tests__" in dirpath or "locales" in dirpath:
        continue
    for n in names:
        p = os.path.join(dirpath, n)
        if n in SKIP_FILES or not n.endswith((".css", ".js", ".html")):
            continue
        new, c = do_css(p) if n.endswith(".css") else do_markup(p)
        if c:
            counts[p.replace(ROOT + "/", "")] = c
            if not DRY:
                _write(p, new)
p = ROOT + "/index.html"
new, c = do_markup(p)
if c:
    counts["index.html"] = c
    if not DRY:
        _write(p, new)
print(sum(counts.values()), "sizes raised in", len(counts), "files")
for k, v in sorted(counts.items(), key=lambda x: -x[1])[:12]:
    print(v, k)
