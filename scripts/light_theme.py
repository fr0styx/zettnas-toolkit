"""Light theme palette (UX-7).

The dark themes hard-code their colours in thousands of declarations, so the light theme
cannot work by swapping a few tokens: its dark text ended up on dark panels. This tool
rewrites each hard-coded colour in a color, background or border declaration to

    var(--lt-<kind>-<rrggbbaa>, <the original colour>)

and writes frontend/src/styles/58-light-palette.css, which defines those variables for the
light theme only. Each light value is computed from its original: dark surfaces become light
ones with the same tint, light text becomes a darker shade of its hue with at least 4.5:1
contrast on white, white glazes and black shades become faint slate ones. Every other theme
still gets the original colour (the var() fallback), so nothing changes there.

Left alone: the front LCD and its preview, the VM console, the desktop and wallpaper
previews, the photo viewer, the yak theme and the theme definitions themselves.

Semantic colour tokens (UX-10): the colours used most, by role, have names (SEMANTIC below,
defined in 50-components.css). Their dark value is the colour itself and their light value is
what this tool computes for it, so swapping var(--lt-...) for the token changes nothing on
screen. convert writes the token for those colours; new code should use the names directly.

    python scripts/light_theme.py convert   # rewrite sources, then write the palette
    python scripts/light_theme.py tokens    # swap var(--lt-...) for the semantic tokens, then the palette
    python scripts/light_theme.py palette   # regenerate the palette from the sources
    python scripts/light_theme.py check     # exit 1 when the palette is out of date
"""

from __future__ import annotations

import colorsys
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
PALETTE = os.path.join(FRONTEND, "src", "styles", "58-light-palette.css")

# Files that must keep their own colours (dark by design, or theme definitions)
SKIP_FILES = {
    "lcd-direct.css",
    "vm-console-direct.css",
    "00-tokens.css",
    "01-themes.css",
    "02-lcd-themes.css",
    "04-yak-theme.css",
    "06-lcd-bigip-layout.css",
    "27-chassis-twin.css",
    "40-vm-console.css",
    "48-viewer.css",
    "58-light-palette.css",
    "mini-preview.js",
    "screensaver.js",
    "wallpapers.js",
    "vm-console.js",
    "lcd-preview.js",
}
# Rules in mixed files that style the LCD or the desktop preview stay as they are
SKIP_SELECTOR = re.compile(
    r"body\.theme-|#screen\b|#mini-lcd|mini-preview|mini-lcd|desktop-screensaver|screensaver-clock|screensaver-wake|\.lcd-|#lcd-|lcd-theme|\.hardware-screen|\.dt-|#dt-|desktop-twin|#console-window"
)
# Elements whose inline styles stay as they are (the LCD, its preview, the desktop preview)
SKIP_IDS = ("console-window", "mini-lcd-canvas", "desktop-twin-viewport")

COLOR = re.compile(r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{4}\b|#[0-9a-fA-F]{3}\b|rgba?\([^()]*\)|\bwhite\b")
SHADOW = re.compile(r"(?<![\w-])(text-shadow)(\s*:\s*)([^;{}\"'`]+)")
PROPS = r"color|background|background-color|background-image|border(?:-(?:top|bottom|left|right))?(?:-color)?"
DECL = re.compile(r"(?<![\w-])(" + PROPS + r")(\s*:\s*)([^;{}\"'`]+)")
VAR_USE = re.compile(r"var\(--lt-([tbr])-([0-9a-f]{8}),\s*([^()]*(?:\([^()]*\))?[^()]*?)\)")
SLATE = (15, 23, 42)
PAGE = (248, 250, 252)
# Text must read on the darkest light surface it can sit on, not only on white
DARKEST_SURFACE = (214, 218, 224)
# Text set in the brand colour gets a dark shade in the light theme (the brand stays for fills)
BRAND_VARS = ("brand", "accent-cyan")
BRAND_INK = "#075985"

# Semantic colour tokens (UX-10): (kind, rrggbbaa) -> token. t = text, r = border, b = background.
# Lines, glazes (white over a surface) and shades (black over it) are named by their opacity
# in percent: --zn-line-8 is a white line at 8 %.
SEMANTIC = {
    ("t", "ffffffff"): "zn-text-strong",
    ("t", "f1f5f9ff"): "zn-text-bright",
    ("t", "e2e8f0ff"): "zn-text",
    ("t", "cbd5e1ff"): "zn-text-soft",
    ("t", "94a3b8ff"): "zn-text-muted",
    ("t", "38bdf8ff"): "zn-text-accent",
    ("t", "34d399ff"): "zn-text-ok",
    ("t", "fbbf24ff"): "zn-text-warn",
    ("t", "f87171ff"): "zn-text-crit",
    ("t", "c084fcff"): "zn-text-ai",
    ("r", "ffffff0d"): "zn-line-5",
    ("r", "ffffff0f"): "zn-line-6",
    ("r", "ffffff12"): "zn-line-7",
    ("r", "ffffff14"): "zn-line-8",
    ("r", "ffffff1a"): "zn-line-10",
    ("r", "ffffff1f"): "zn-line-12",
    ("r", "ffffff24"): "zn-line-14",
    ("r", "ffffff26"): "zn-line-15",
    ("r", "ffffff2e"): "zn-line-18",
    ("r", "ffffff33"): "zn-line-20",
    ("b", "ffffff05"): "zn-glaze-2",
    ("b", "ffffff08"): "zn-glaze-3",
    ("b", "ffffff0a"): "zn-glaze-4",
    ("b", "ffffff0d"): "zn-glaze-5",
    ("b", "ffffff0f"): "zn-glaze-6",
    ("b", "ffffff14"): "zn-glaze-8",
    ("b", "ffffff1a"): "zn-glaze-10",
    ("b", "ffffff1f"): "zn-glaze-12",
    ("b", "ffffff26"): "zn-glaze-15",
    ("b", "00000033"): "zn-shade-20",
    ("b", "00000040"): "zn-shade-25",
    ("b", "0000004c"): "zn-shade-30",
    ("b", "00000059"): "zn-shade-35",
    ("b", "00000066"): "zn-shade-40",
}
# Tokens whose light value 50-components.css sets by hand (they predate the tool)
LIGHT_BY_HAND = {"zn-text-strong", "zn-text", "zn-text-soft", "zn-text-muted"}
TOKEN_FILE = os.path.join(FRONTEND, "src", "styles", "50-components.css")


def token_value(name: str) -> str:
    """The dark value of a semantic token: the colour it stands for."""
    (k, h) = next(pair for pair, n in SEMANTIC.items() if n == name)
    r, g, b, a = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16) / 255
    return css((r, g, b), round(a, 2))


def token_light(name: str) -> str | None:
    (k, h) = next(pair for pair, n in SEMANTIC.items() if n == name)
    return LIGHT[k](parse(token_value(name)))


# ---------------------------------------------------------------------------
# Colour maths
# ---------------------------------------------------------------------------


def parse(c: str):
    c = c.strip().lower()
    if c == "white":
        return 255, 255, 255, 1.0
    if c.startswith("#"):
        h = c[1:]
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return r, g, b, a
    m = re.match(r"rgba?\(([^)]*)\)", c)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(1).strip()) if p]
    if len(parts) < 3 or any("%" in p for p in parts[:3]):
        return None
    try:
        r, g, b = (int(round(float(p))) for p in parts[:3])
        a = float(parts[3].rstrip("%")) / (100 if parts[3].endswith("%") else 1) if len(parts) > 3 else 1.0
    except ValueError:
        return None
    return r, g, b, a


def key(rgba) -> str:
    r, g, b, a = rgba
    return f"{r:02x}{g:02x}{b:02x}{round(a * 255):02x}"


def lum(r, g, b) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(c1, c2) -> float:
    a, b = lum(*c1[:3]), lum(*c2[:3])
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def hls(r, g, b):
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


def from_hls(h, lt, s):
    return tuple(int(round(v * 255)) for v in colorsys.hls_to_rgb(h, max(0, min(1, lt)), max(0, min(1, s))))


def css(rgb, a=1.0) -> str:
    r, g, b = rgb
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {round(a, 3)})"


def saturated_fill(rgba) -> bool:
    """A coloured fill (a badge, a primary button) whose text keeps its own colour."""
    r, g, b, a = rgba
    _, lig, s = hls(r, g, b)
    y = lum(r, g, b)
    return a >= 0.6 and s >= 0.35 and 0.05 <= y <= 0.6


def light_text(rgba):
    """Dark ink for a light text colour (None when it already reads on light surfaces)."""
    r, g, b, a = rgba
    if a == 0 or contrast((r, g, b), DARKEST_SURFACE) >= 4.6:
        return None
    h, lig, s = hls(r, g, b)
    if s < 0.35 and lig >= 0.5:  # whites and slate greys
        return css((15, 23, 42) if lig >= 0.86 else (30, 41, 59) if lig >= 0.7 else (71, 85, 105))
    l2 = min(lig, 0.5)
    rgb = from_hls(h, l2, s)
    while contrast(rgb, DARKEST_SURFACE) < 4.6 and l2 > 0.05:
        l2 -= 0.01
        rgb = from_hls(h, l2, s)
    return css(rgb)


def light_background(rgba):
    r, g, b, a = rgba
    if a < 0.02:
        return None
    y = lum(r, g, b)
    h, lig, s = hls(r, g, b)
    # faint, because nested glazes and shades add up (a shade on a card on a panel)
    if y > 0.6:  # white glaze -> faint slate tint; opaque light backgrounds stay
        return css(SLATE, min(0.06, max(0.02, a * 0.6))) if a < 0.3 else None
    if lig < 0.03 and a < 0.95:  # black shade
        return css(SLATE, min(0.06, max(0.02, a * 0.15)))
    if y < 0.06:  # dark surface -> light surface with the same tint
        # nearly opaque: a translucent light panel over the dark wallpaper would turn grey
        rgb = from_hls(h, 1 - lig * 0.35, min(s, 0.5) * 0.5)
        return css(rgb, max(a, 0.96))
    if s < 0.15 and y < 0.35:  # mid grey surface
        return css(from_hls(h, 1 - lig * 0.25, s), max(a, 0.96))
    return None  # coloured fills keep their colour


def light_border(rgba):
    r, g, b, a = rgba
    y = lum(r, g, b)
    if y > 0.6 and a < 0.5:
        return css(SLATE, min(0.28, max(0.08, a * 1.6)))
    if y < 0.06 and a > 0.3:
        return css(SLATE, 0.16)
    return None


LIGHT = {"t": light_text, "b": light_background, "r": light_border}


def kind(prop: str) -> str:
    return "t" if prop == "color" else "b" if prop.startswith("background") else "r"


# ---------------------------------------------------------------------------
# Rewriting
# ---------------------------------------------------------------------------


def _wrap_brand(value: str) -> str:
    """color: var(--brand, ...) -> var(--lt-ink-brand, var(--brand, ...))"""
    out, i = [], 0
    pat = re.compile(r"var\(--(?:" + "|".join(BRAND_VARS) + r")\b")
    while True:
        m = pat.search(value, i)
        if not m:
            out.append(value[i:])
            return "".join(out)
        if value[max(0, m.start() - 18) : m.start()].endswith("--lt-ink-brand, "):
            out.append(value[i : m.end()])
            i = m.end()
            continue
        depth, j = 0, m.start() + 3  # at the "(" of var(
        while j < len(value):
            depth += value[j] == "("
            depth -= value[j] == ")"
            j += 1
            if depth == 0:
                break
        if depth != 0:  # unbalanced (cut off by the declaration regex): leave it
            out.append(value[i:])
            return "".join(out)
        out.append(value[i : m.start()] + "var(--lt-ink-brand, " + value[m.start() : j] + ")")
        i = j


def _light_defined() -> set[str]:
    """Custom properties the light theme defines itself (their fallbacks never apply there)."""
    names = set()
    for f in glob.glob(os.path.join(FRONTEND, "src", "styles", "*.css")):
        if os.path.basename(f) == "58-light-palette.css":
            continue
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        for m in re.finditer(r"body\.theme-light[^{,]*\{([^}]*)\}", text):
            names.update(re.findall(r"(--[\w-]+)\s*:", m.group(1)))
    return names


LIGHT_DEFINED = _light_defined()
# var(--lt-ink-brand, var(--brand, var(--lt-t-..., X))) -> the inner one is never used
_REDUNDANT = re.compile(
    r"var\(--lt-ink-brand, var\((--[\w-]+),\s*var\(--lt-t-[0-9a-f]{8},\s*([^()]*(?:\([^()]*\))?)\)\)\)"
)
_FALLBACK = re.compile(r"var\((--[\w-]+),\s*(" + COLOR.pattern + r")\s*\)")


def _fallbacks(prop: str, value: str) -> str:
    """var(--text, #e2e8f0) -> var(--text, var(--lt-t-..., #e2e8f0)) when the light theme lacks --text."""
    k = kind(prop)

    def fb(m):
        name, lit = m.group(1), m.group(2)
        p = parse(lit)
        if name in LIGHT_DEFINED or name.startswith("--lt-") or not p or LIGHT[k](p) is None:
            return m.group(0)
        if k == "t" and name[2:] in BRAND_VARS:  # covered by --lt-ink-brand
            return m.group(0)
        return f"var({name}, var(--lt-{k}-{key(p)}, {lit}))"

    return _FALLBACK.sub(fb, value)


def rewrite_block(block: str) -> str:
    """Rewrites the declarations of one CSS rule or style attribute."""
    keep_text = False
    for m in DECL.finditer(block):
        if kind(m.group(1)) == "b" and "var(" not in m.group(3):
            for c in COLOR.findall(m.group(3)):
                p = parse(c)
                if p and saturated_fill(p):
                    keep_text = True

    def decl(m):
        prop, sep, value = m.group(1), m.group(2), m.group(3)
        if "${" not in value and "var(--" in value and not (prop == "color" and keep_text):
            value = _REDUNDANT.sub(r"var(--lt-ink-brand, var(\1, \2))", _fallbacks(prop, value))
            return prop + sep + (_wrap_brand(value) if prop == "color" else value)
        if "var(" in value or "${" in value or (prop == "color" and keep_text):
            return m.group(0)
        k = kind(prop)

        def col(cm):
            p = parse(cm.group(0))
            if not p or LIGHT[k](p) is None:
                return cm.group(0)
            if (k, key(p)) in SEMANTIC:
                return f"var(--{SEMANTIC[(k, key(p))]})"
            return f"var(--lt-{k}-{key(p)}, {cm.group(0)})"

        return prop + sep + COLOR.sub(col, value)

    def shadow(m):
        value = m.group(3).strip()
        if value.startswith("none") or "var(" in value or "${" in value:
            return m.group(0)
        return m.group(1) + m.group(2) + f"var(--lt-text-shadow, {value})"

    return SHADOW.sub(shadow, DECL.sub(decl, block))


def _skip_ranges(text: str) -> list[tuple[int, int]]:
    """Character ranges of the elements in SKIP_IDS (div nesting counted)."""
    ranges = []
    for el_id in SKIP_IDS:
        m = re.search(r'<div\b[^>]*\bid="' + re.escape(el_id) + r'"', text)
        if not m:
            continue
        depth, pos = 0, m.start()
        for t in re.finditer(r"<div\b|</div>", text[m.start() :]):
            depth += 1 if t.group(0) == "<div" else -1
            if depth == 0:
                pos = m.start() + t.end()
                break
        ranges.append((m.start(), pos))
    return ranges


def rewrite_css(text: str) -> str:
    def rule(m):
        if SKIP_SELECTOR.search(m.group(1)):
            return m.group(0)
        return m.group(1) + "{" + rewrite_block(m.group(2)) + "}"

    return re.sub(r"([^{}]*)\{([^{}]*)\}", rule, text)


def rewrite_markup(text: str) -> str:
    skip = _skip_ranges(text)

    def attr(m):
        if any(a <= m.start() < b for a, b in skip):
            return m.group(0)
        return m.group(1) + rewrite_block(m.group(2)) + m.group(3)

    text = re.sub(r'(style\s*=\s*")([^"]*)(")', attr, text)
    return re.sub(r"(style\s*=\s*')([^']*)(')", attr, text)


def sources() -> list[str]:
    pats = ("src/**/*.css", "src/**/*.js", "src/**/*.html")
    files = [f for p in pats for f in glob.glob(os.path.join(FRONTEND, p), recursive=True)]
    files.append(os.path.join(FRONTEND, "index.html"))
    return sorted(
        f
        for f in files
        if "__tests__" not in f and os.sep + "locales" + os.sep not in f and os.path.basename(f) not in SKIP_FILES
    )


def tokenize(text: str) -> str:
    """var(--lt-r-ffffff14, rgba(255, 255, 255, 0.08)) -> var(--zn-line-8)"""

    def swap(m):
        name = SEMANTIC.get((m.group(1), m.group(2)))
        p = parse(m.group(3))
        if not name or not p or key(p) != m.group(2):
            return m.group(0)
        return f"var(--{name})"

    return VAR_USE.sub(swap, text)


def tokens() -> int:
    changed = 0
    for f in sources():
        with open(f, encoding="utf-8") as fh:
            old = fh.read()
        new = tokenize(old)
        if new != old:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
            changed += 1
    return changed


def convert() -> int:
    changed = 0
    for f in sources():
        with open(f, encoding="utf-8") as fh:
            old = fh.read()
        new = tokenize(rewrite_css(old) if f.endswith(".css") else rewrite_markup(old))
        if new != old:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
            changed += 1
    return changed


def palette_text() -> str:
    found: dict[str, str] = {}
    for f in sources():
        with open(f, encoding="utf-8") as fh:
            for m in VAR_USE.finditer(fh.read()):
                p = parse(m.group(3))
                if p is None or key(p) != m.group(2):
                    continue
                value = LIGHT[m.group(1)](p)
                if value:
                    found[f"--lt-{m.group(1)}-{m.group(2)}"] = value
    lines = [
        "/* Generated by scripts/light_theme.py from the var(--lt-...) colours in the sources; do not edit.",
        "   Light-theme values for colours the dark themes hard-code (UX-7). Other themes use the",
        "   var() fallbacks, i.e. their original colours. */",
        "body.theme-light:not(.lcd-direct) {",
        f"  --lt-ink-brand: {BRAND_INK};",
        "  --lt-text-shadow: none;",
        *(f"  {k}: {v};" for k, v in sorted(found.items())),
        "  /* the semantic tokens (UX-10) */",
        *(
            f"  --{name}: {token_light(name)};"
            for name in sorted(SEMANTIC.values())
            if name not in LIGHT_BY_HAND and token_light(name)
        ),
        "}",
        "",
    ]
    return "\n".join(lines)


def main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "convert":
        print(f"rewrote {convert()} files")
    if cmd == "tokens":
        print(f"tokenised {tokens()} files")
    if cmd in ("convert", "tokens", "palette"):
        with open(PALETTE, "w", encoding="utf-8") as fh:
            fh.write(palette_text())
        print(f"wrote {os.path.relpath(PALETTE, ROOT)}")
        return 0
    if cmd == "check":
        current = ""
        if os.path.exists(PALETTE):
            with open(PALETTE, encoding="utf-8") as fh:
                current = fh.read()
        if current != palette_text():
            print("58-light-palette.css is out of date: run python scripts/light_theme.py palette")
            return 1
        print("light palette up to date")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
