"""Theme stylesheets (APP-B): Lagoon, Fjord, Moss, Heather and Canyon, each in dark and light.

The source is scripts/theme_palettes.json: the palette family designed from the brand's Lagoon
tokens (docs/BRAND.md; Lagoon is kept verbatim, the others share its lightness ladder and change
hue). For each theme this writes frontend/src/styles/themes/<id>.css with

- the app's colour variables (--bg, --card, --brand, the --c-* tokens, ...) from the palette;
- every colour the stylesheets wrap for light mode (var(--lt-...), scripts/light_theme.py) and the
  semantic --kb-* tokens, moved to the theme: Lagoon's teal and blue-green become the theme's hues
  at the same lightness, while greys, white, black and the status colours stay as they are;
- True black (a dark-mode option): the palette's near-black surfaces in the theme's hue;
- the tint slider: neutral colours with their chroma multiplied by --kb-tint (1 = Subtle, the
  palette itself; up to 3 = Strong), for browsers that understand oklch().

Status colours are the same in every theme (owner's decision, 10 Nov 2026), so the palette's
per-theme status nudges are not used: every theme gets Lagoon's success, warning, danger and info.

Lagoon's own file holds only the tint rules: Lagoon is what the stylesheets already say.
A theme's file loads when it is chosen (or when Lagoon is tinted), not with the first page.

    python scripts/themes.py write   # regenerate the stylesheets
    python scripts/themes.py check   # exit 1 when they are out of date or a contrast pair fails
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLES = os.path.join(ROOT, "frontend", "src", "styles")
OUT_DIR = os.path.join(STYLES, "themes")
PALETTES = os.path.join(ROOT, "scripts", "theme_palettes.json")
LIGHT_PALETTE = os.path.join(STYLES, "58-light-palette.css")
COMPONENTS = os.path.join(STYLES, "50-components.css")
THEMES = ("lagoon", "fjord", "moss", "heather", "canyon")
STATUS = ("success", "warning", "danger", "info")
# How far the slider can raise a theme's neutral chroma. Canyon stops at Medium: at Strong its sand
# panels read as warning amber (prototype gate, 10 Nov 2026).
TINT_MAX = {"lagoon": 3.0, "fjord": 3.0, "moss": 3.0, "heather": 3.0, "canyon": 2.0}
# Lagoon's hues (OKLCH degrees): the family a literal colour belongs to is judged against these
LAGOON_HP, LAGOON_HN = 181.5, 217.0

# ---------------------------------------------------------------------------
# Colour maths: sRGB <-> OKLab/OKLCH (Björn Ottosson)
# ---------------------------------------------------------------------------


def parse(c: str):
    c = c.strip().lower()
    if c in ("white", "#fff"):
        return 255, 255, 255, 1.0
    if c in ("black", "#000"):
        return 0, 0, 0, 1.0
    if c.startswith("#"):
        h = c[1:]
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h)
        if len(h) not in (6, 8):
            return None
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a
    m = re.fullmatch(r"rgba?\(([^)]*)\)", c)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(1).strip()) if p]
    if len(parts) < 3 or any("%" in p for p in parts[:3]):
        return None
    r, g, b = (float(p) for p in parts[:3])
    a = float(parts[3]) if len(parts) > 3 else 1.0
    return r, g, b, a


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _enc(c: float) -> float:
    c = max(0.0, c)
    return (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055) * 255


def to_lch(rgb) -> tuple[float, float, float]:
    r, g, b = (_lin(v) for v in rgb[:3])
    lv = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    mv = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    sv = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    lv, mv, sv = (math.copysign(abs(x) ** (1 / 3), x) for x in (lv, mv, sv))
    L = 0.2104542553 * lv + 0.7936177850 * mv - 0.0040720468 * sv
    a = 1.9779984951 * lv - 2.4285922050 * mv + 0.4505937099 * sv
    bb = 0.0259040371 * lv + 0.7827717662 * mv - 0.8086757660 * sv
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _lab_to_rgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    lv = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    mv = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    sv = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * lv - 3.3077115913 * mv + 0.2309699292 * sv
    g = -1.2684380046 * lv + 2.6097574011 * mv - 0.3413193965 * sv
    bl = -0.0041960863 * lv - 0.7034186147 * mv + 1.7076147010 * sv
    return r, g, bl


def from_lch(L: float, C: float, H: float) -> tuple[int, int, int]:
    """The colour, with its chroma reduced until it fits sRGB (lightness and hue stay)."""
    for _ in range(60):
        lin = _lab_to_rgb(L, C * math.cos(math.radians(H)), C * math.sin(math.radians(H)))
        if all(-1e-4 <= v <= 1 + 1e-4 for v in lin):
            break
        C *= 0.95
    return tuple(max(0, min(255, round(_enc(v)))) for v in lin)  # type: ignore[return-value]


def css(rgb, a: float = 1.0) -> str:
    r, g, b = (int(round(v)) for v in rgb[:3])
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {round(a, 3)})"


def hue_dist(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def hue_mix(a: float, b: float, t: float) -> float:
    """t of the way from hue a to hue b, the short way round."""
    d = ((b - a + 180) % 360) - 180
    return (a + d * t) % 360


def lum(rgb) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def contrast(c1, c2) -> float:
    a, b = lum(c1), lum(c2)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# ---------------------------------------------------------------------------
# Moving a colour to a theme
# ---------------------------------------------------------------------------


def family(lch) -> str:
    """'primary' for Lagoon's teal, 'neutral' for its blue-green greys, '' for everything else
    (greys without hue, white, black, status colours, amber, the AI violet ...)."""
    L, C, H = lch
    if C < 0.006:
        return ""
    if C >= 0.06:
        return "primary" if hue_dist(H, LAGOON_HP) <= 25 else ""
    if hue_dist(H, LAGOON_HN) <= 45 or hue_dist(H, LAGOON_HP) <= 20:
        return "neutral"
    return ""


def seeds(theme: str, mode: str, pal: dict) -> dict:
    s = dict(pal["seeds"][theme])
    hp = s.get("hp_light", s["hp"]) if mode == "light" else s["hp"]
    return {
        "hp": hp,
        "hn": s["hn"],
        "nc": s.get(f"nc_{mode}", 1.0),
        "pc": s.get(f"pc_{mode}", 1.0),
    }


def move(value: str, theme: str, mode: str, pal: dict) -> str:
    """value (a Lagoon colour) as it reads in theme; unchanged when it is not Lagoon-hued."""
    if theme == "lagoon":
        return value
    c = parse(value)
    if not c:
        return value
    lch = to_lch(c)
    fam = family(lch)
    if not fam:
        return value
    s = seeds(theme, mode, pal)
    L, C, H = lch
    if fam == "primary":
        rgb = from_lch(L, C * s["pc"], s["hp"])
    else:
        # dark surfaces take the neutral hue; lighter neutrals (borders, muted text, text) and every
        # light-mode neutral lean a quarter of the way to the primary, as the palette's ladder does
        hue = s["hn"] if (mode == "dark" and L < 0.45) else hue_mix(s["hn"], s["hp"], 0.25)
        rgb = from_lch(L, C * s["nc"], hue)
    return css(rgb, c[3])


def tinted(value: str) -> str | None:
    """The oklch() form of a neutral colour whose chroma follows --kb-tint, or None."""
    c = parse(value)
    if not c:
        return None
    lch = to_lch(c)
    L, C, H = lch
    if C < 0.006 or C >= 0.06:
        return None
    alpha = "" if c[3] >= 0.999 else f" / {round(c[3], 3)}"
    return f"oklch({L:.4f} calc({C:.4f} * var(--kb-tint, 1)) {H:.1f}{alpha})"


# ---------------------------------------------------------------------------
# What the stylesheets already define
# ---------------------------------------------------------------------------

DECL = re.compile(r"^\s*(--[\w-]+)\s*:\s*([^;]+);", re.M)


def _blocks(path: str) -> list[tuple[str, str]]:
    """(selector, body) of each top-level rule; good enough for the token files."""
    src = re.sub(r"/\*.*?\*/", "", Path(path).read_text(encoding="utf-8"), flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", src)]


FRONTEND = os.path.join(ROOT, "frontend")
# Variables the stylesheets only ever use with a fallback (nothing defines them): Lagoon shows the
# fallback in both modes, a theme moves it
FALLBACK_HOLDERS = {"--accent-cyan": "#33cdb8", "--accent-cyan-hi": "#4fd8c4"}


def _sources() -> list[str]:
    pats = ("src/styles/*.css", "src/windows/*.html", "index.html", "src/**/*.js")
    files = [f for p in pats for f in glob.glob(os.path.join(FRONTEND, p), recursive=True)]
    return sorted(f for f in files if "__tests__" not in f)


def light_wrapped() -> dict[str, tuple[str, str]]:
    """--lt-<kind>-<rrggbbaa> -> (Lagoon's dark colour, its light value): every wrapped colour the
    sources use; the light value is 58-light-palette.css's, or the colour itself where light mode
    keeps it (saturated fills)."""
    light = {}
    for sel, body in _blocks(LIGHT_PALETTE):
        if "theme-light" in sel:
            light.update({n: v.strip() for n, v in DECL.findall(body)})
    names = set()
    for f in _sources():
        names |= set(re.findall(r"var\((--lt-[tbr]-[0-9a-f]{8})", Path(f).read_text(encoding="utf-8")))
    out = {}
    for name in sorted(names | {n for n in light if re.fullmatch(r"--lt-[tbr]-[0-9a-f]{8}", n)}):
        h = name[-8:]
        dark = css((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)), int(h[6:8], 16) / 255)
        out[name] = (dark, light.get(name, dark))
    return out


def semantic() -> dict[str, tuple[str | None, str | None]]:
    """--kb-* colour tokens -> (dark value, light value)."""
    dark: dict[str, str] = {}
    light: dict[str, str] = {}
    for path in (COMPONENTS, LIGHT_PALETTE):
        for sel, body in _blocks(path):
            target = light if "theme-light" in sel else dark if sel == ":root" else None
            if target is None:
                continue
            for name, val in DECL.findall(body):
                if name.startswith("--kb-") and parse(val.strip()):
                    target.setdefault(name, val.strip())
    return {n: (dark.get(n), light.get(n)) for n in sorted(set(dark) | set(light))}


def rgb_triplet(hexv: str) -> str:
    r, g, b, _ = parse(hexv)
    return f"{int(r)}, {int(g)}, {int(b)}"


def roles(theme: str, mode: str, pal: dict) -> dict[str, str]:
    """The palette's roles as the app uses them: status colours are Lagoon's in every theme, and
    the border is lightened (dark) or darkened (light) just enough for 3:1 on every surface; the
    palette's own border step left 2.84 to 2.98:1 on raised and overlay panels."""
    p = dict(pal["themes"][theme][mode])
    for k in list(p):
        if any(k.startswith(s) or k == f"on-{s}" for s in STATUS):
            p[k] = pal["themes"]["lagoon"][mode][k]
    surfaces = [parse(p[k])[:3] for k in ("bg", "surface", "surface-raised", "surface-overlay")]
    L, C, H = to_lch(parse(p["border"]))
    step = 0.002 if mode == "dark" else -0.002
    while min(contrast(from_lch(L, C, H), s) for s in surfaces) < 3.0 and 0 < L < 1:
        L += step
    p["border"] = css(from_lch(L, C, H))
    return p


def base_vars(theme: str, mode: str, pal: dict) -> dict[str, str]:
    """The app's colour variables from the palette's roles.

    --ok2 is the app's accent in most places (about 290 uses) and also marks "healthy". It takes the
    theme's main colour, which the owner allowed for "alive and healthy" (10 Nov 2026), except where
    that colour sits within 60 degrees of hue of the critical red (Canyon's terracotta): there it
    takes the theme's accent, so "healthy" never reads red-ish (NUX-4)."""
    p = roles(theme, mode, pal)
    main = p["primary"] if mode == "dark" else p["primary-text"]
    crit = p["danger"]
    ok2 = (
        main
        if hue_dist(to_lch(parse(main))[2], to_lch(parse(crit))[2]) >= 60
        else (p["accent"] if mode == "dark" else p["accent-text"])
    )
    dark_primary = pal["themes"][theme]["dark"]["primary"]
    glow = 0.35 if mode == "dark" else 0.3
    hover = 0.15 if mode == "dark" else 0.12
    brand = p["primary"]
    return {
        "--bg": p["bg"],
        "--card": p["surface"],
        "--card-hi": p["surface-raised"],
        "--fg": p["text"],
        "--muted": p["text-muted"],
        "--track": p["line"],
        "--ok2": ok2,
        "--brand": brand,
        "--brand-rgb": rgb_triplet(brand),
        "--accent-rgb": rgb_triplet(brand),
        "--accent-glow": f"rgba({rgb_triplet(brand)}, {glow})",
        "--accent-hover": f"rgba({rgb_triplet(brand)}, {hover})",
        "--accent-contrast-fg": p["on-primary"],
        "--focus-ring": p["focus"],
        "--focus-shadow": f"0 0 0 3px rgba({rgb_triplet(p['focus'])}, {glow})",
        "--c-bg": p["bg"],
        "--c-raised": p["surface-raised"],
        "--c-text": p["text"],
        "--c-muted": p["text-muted"],
        "--c-primary": p["primary"],
        # light mode's washes keep the bright primary: a pale wash of the dark shade turned
        # selected rows grey on white (APP-A gate)
        "--c-primary-rgb": rgb_triplet(p["primary"] if mode == "dark" else dark_primary),
        "--c-primary-text": p["primary-text"],
        "--c-primary-text-rgb": rgb_triplet(p["primary-text"] if mode == "dark" else dark_primary),
        "--c-success": p["success"],
        "--c-info-text": p["info-text"],
        "--c-accent": p["accent"],
        "--c-neutral": p["text-muted"],
        "--c-neutral-soft": p["surface-raised"],
        "--c-border": p["border"],
        "--kb-glass-tint": p["glass-tint"],
    }


# Lagoon's page background (00-tokens.css and 01-themes.css), moved like any other colour
PAGE_GRADIENT = {
    "dark": ("#131d20", "#070d0f"),
    "light": ("#f9fbfb", "#e3eaea"),
}


def theme_values(theme: str, mode: str, pal: dict) -> dict[str, str]:
    """Every variable the theme sets in mode, before the tint."""
    out: dict[str, str] = {}
    if theme != "lagoon":
        out.update(base_vars(theme, mode, pal))
    for name, (dark, light) in light_wrapped().items():
        src = dark if mode == "dark" else light
        moved = move(src, theme, mode, pal)
        if moved != src:
            out[name] = moved
    if theme != "lagoon" and mode == "light":
        out["--lt-ink-brand"] = pal["themes"][theme]["light"]["primary-text"]
    for name, lagoon in FALLBACK_HOLDERS.items():
        moved = move(lagoon, theme, "dark", pal)  # the same colour in both modes, as in Lagoon
        if moved != lagoon:
            out[name] = moved
    for name, (dark, light) in semantic().items():
        src = dark if mode == "dark" else light
        if not src:
            continue
        moved = move(src, theme, mode, pal)
        if moved != src:
            out[name] = moved
    return out


def tint_values(theme: str, mode: str, pal: dict) -> dict[str, str]:
    """The variables whose chroma follows the slider: every neutral the theme ends up with."""
    final: dict[str, str] = {}
    for name, (dark, light) in light_wrapped().items():
        final[name] = dark if mode == "dark" else light
    for name, (dark, light) in semantic().items():
        v = dark if mode == "dark" else light
        if v:
            final[name] = v
    if theme == "lagoon":
        final.update(base_vars("lagoon", mode, pal))
    final.update(theme_values(theme, mode, pal))
    out = {}
    for name, v in final.items():
        c = parse(v)
        t = tinted(v) if c else None
        # only colours on the theme's neutral hues: status fills and the AI violet stay put
        if t and (family(to_lch(c)) == "neutral" or _theme_neutral(v, theme, mode, pal)):
            out[name] = t
    return out


def _theme_neutral(value: str, theme: str, mode: str, pal: dict) -> bool:
    """Whether value sits on the theme's neutral hue (a colour move() produced)."""
    c = parse(value)
    if not c:
        return False
    L, C, H = to_lch(c)
    if C < 0.006 or C >= 0.06:
        return False
    s = seeds(theme, mode, pal)
    return hue_dist(H, s["hn"]) <= 30 or hue_dist(H, hue_mix(s["hn"], s["hp"], 0.25)) <= 30


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _block(selector: str, values: dict[str, str], extra: str = "") -> str:
    lines = [f"  {k}: {v};" for k, v in sorted(values.items())]
    if extra:
        lines.append(f"  {extra}")
    return selector + " {\n" + "\n".join(lines) + "\n}\n"


def render(theme: str, pal: dict) -> str:
    name = pal["themes"][theme]["name"]
    head = (
        f"/* Generated by scripts/themes.py from scripts/theme_palettes.json; do not edit.\n"
        f"   {name} ({pal['themes'][theme]['description']}): dark, light, True black and the tint slider (APP-B). */\n"
    )
    t = f"body.kb-theme-{theme}"
    parts = [head]
    if theme != "lagoon":
        for mode in ("dark", "light"):
            g1, g2 = (move(c, theme, mode, pal) for c in PAGE_GRADIENT[mode])
            sel = f"{t}:not(.theme-light):not(.lcd-direct)" if mode == "dark" else f"{t}.theme-light:not(.lcd-direct)"
            parts.append(
                _block(
                    sel,
                    theme_values(theme, mode, pal),
                    f"background: radial-gradient(circle at 50% 50%, {g1} 0%, {g2} 70%);",
                )
            )
        tb = pal["themes"][theme]["trueBlack"]
        parts.append(
            _block(
                f"{t}.theme-oled:not(.theme-light):not(.lcd-direct)",
                {
                    "--bg": tb["bg"],
                    "--c-bg": tb["bg"],
                    "--card": tb["surface"],
                    "--card-hi": tb["surface-raised"],
                    "--c-raised": tb["surface-raised"],
                    "--c-neutral-soft": tb["surface-raised"],
                    "--track": tb["line"],
                    "--kb-glass-tint": tb["glass-tint"],
                },
                "background: #000000;",
            )
        )
    tint = []
    for mode in ("dark", "light"):
        sel = (
            f"body.kb-tinted{'.kb-theme-' + theme}:not(.theme-light):not(.theme-oled):not(.lcd-direct)"
            if mode == "dark"
            else f"body.kb-tinted.kb-theme-{theme}.theme-light:not(.lcd-direct)"
        )
        tint.append(_block(sel, tint_values(theme, mode, pal)).replace("\n", "\n  ").rstrip() + "\n")
    parts.append("@supports (color: oklch(0.5 0.1 180)) {\n  " + "\n  ".join(tint).rstrip() + "\n}\n")
    return "\n".join(parts)


# Text pairs that must read (WCAG 2.1 AA): (foreground role, background role, minimum)
PAIRS = [
    ("text", "bg", 4.5),
    ("text", "surface", 4.5),
    ("text", "surface-raised", 4.5),
    ("text", "surface-overlay", 4.5),
    ("text-muted", "bg", 4.5),
    ("text-muted", "surface", 4.5),
    ("text-muted", "surface-raised", 4.5),
    ("text-muted", "surface-overlay", 4.5),
    ("primary-text", "bg", 4.5),
    ("primary-text", "surface", 4.5),
    ("on-primary", "primary", 4.5),
    ("accent-text", "bg", 4.5),
    ("border", "surface", 3.0),
    ("border", "surface-raised", 3.0),
    ("border", "surface-overlay", 3.0),
    ("success-text", "bg", 4.5),
    ("warning-text", "bg", 4.5),
    ("danger-text", "bg", 4.5),
    ("info-text", "bg", 4.5),
]


def contrast_failures(pal: dict) -> list[str]:
    """Every pair that misses its minimum, at Subtle and at the slider's top end."""
    bad = []
    for theme in THEMES:
        for mode in ("dark", "light"):
            p = roles(theme, mode, pal)
            for k_max in (1.0, TINT_MAX[theme]):
                q = {}
                for k, v in p.items():
                    L, C, H = to_lch(parse(v))
                    q[k] = from_lch(L, C * k_max, H) if 0.006 <= C < 0.06 else parse(v)[:3]
                for fg, bg, need in PAIRS:
                    got = contrast(q[fg], q[bg])
                    if got < need:
                        bad.append(f"{theme} {mode} tint {k_max}: {fg} on {bg} is {got:.2f}:1 (needs {need})")
    return bad


def main(argv: list[str]) -> int:
    pal = json.loads(Path(PALETTES).read_text(encoding="utf-8"))
    cmd = argv[1] if len(argv) > 1 else "check"
    stale = []
    for theme in THEMES:
        path = os.path.join(OUT_DIR, f"{theme}.css")
        want = render(theme, pal)
        have = Path(path).read_text(encoding="utf-8") if os.path.exists(path) else None
        if cmd == "write":
            os.makedirs(OUT_DIR, exist_ok=True)
            if have != want:
                Path(path).write_text(want, encoding="utf-8")
                print("wrote", os.path.relpath(path, ROOT))
        elif have != want:
            stale.append(os.path.relpath(path, ROOT))
    bad = contrast_failures(pal)
    for b in bad:
        print("contrast:", b)
    for s in stale:
        print("out of date (run python scripts/themes.py write):", s)
    return 1 if (bad or stale) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
