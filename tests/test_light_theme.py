"""The generated light theme (UX-7): readable colours, other themes untouched, palette in sync."""

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import light_theme as lt  # noqa: E402


def test_palette_matches_the_sources():
    with open(lt.PALETTE, encoding="utf-8") as f:
        assert lt.palette_text() == f.read(), "run: python scripts/light_theme.py palette"


def test_sources_are_fully_converted():
    """A new hard-coded colour gets its light value from the codemod, not by hand."""
    left = []
    for f in lt.sources():
        with open(f, encoding="utf-8") as fh:
            old = fh.read()
        new = lt.rewrite_css(old) if f.endswith(".css") else lt.rewrite_markup(old)
        if new != old:
            left.append(os.path.relpath(f, ROOT))
    assert not left, "run: python scripts/light_theme.py convert  (unconverted colours in " + ", ".join(left) + ")"


@pytest.mark.parametrize(
    "c", ["#ffffff", "#e2e8f0", "#94a3b8", "#00f0ff", "#38bdf8", "#22c55e", "#fca5a5", "#f5b731", "#c084fc"]
)
def test_light_text_reads_on_every_light_surface(c):
    value = lt.light_text(lt.parse(c))
    assert value is not None
    assert lt.contrast(lt.parse(value)[:3], lt.DARKEST_SURFACE) >= 4.5
    assert lt.contrast(lt.parse(value)[:3], (255, 255, 255)) >= 4.5


def test_light_text_keeps_the_hue():
    r, g, b, _ = lt.parse(lt.light_text(lt.parse("#22c55e")))
    assert g > r and g > b  # green stays green


@pytest.mark.parametrize(
    "c", ["#0d141e", "rgba(13, 20, 30, 0.88)", "#111a24", "rgba(0, 0, 0, 0.35)", "rgba(255, 255, 255, 0.05)"]
)
def test_dark_surfaces_become_light(c):
    r, g, b, a = lt.parse(lt.light_background(lt.parse(c)))
    assert lt.lum(r, g, b) > 0.8 or a <= 0.06  # a light surface, or only a faint tint


def test_coloured_fills_keep_their_colour():
    assert lt.light_background(lt.parse("#0284c7")) is None
    assert lt.light_background(lt.parse("rgba(37, 194, 160, 0.15)")) is None


def test_other_themes_get_the_original_colour():
    css = ".x { color: #e5e7eb; background: #0d141e; border: 1px solid rgba(255,255,255,0.09); }"
    out = lt.rewrite_css(css)
    assert "var(--lt-t-e5e7ebff, #e5e7eb)" in out
    assert "var(--lt-b-0d141eff, #0d141e)" in out
    assert "var(--lt-r-ffffff17, rgba(255,255,255,0.09))" in out
    # colours with a semantic token (UX-10) get the token, whose dark value is that colour
    assert lt.rewrite_css(".y { color: #e2e8f0; }") == ".y { color: var(--zn-text); }"
    # every fallback is exactly the original literal
    for _k, key, fallback in re.findall(r"var\(--lt-([tbr])-([0-9a-f]{8}), ([^()]*(?:\([^()]*\))?)\)", out):
        assert lt.key(lt.parse(fallback)) == key


def test_lcd_and_previews_are_left_alone():
    css = "#screen .card { color: #e2e8f0; } .dt-window { background: #0d141e; } body.theme-light .x { color: #fff; }"
    assert lt.rewrite_css(css) == css
    html = '<div id="console-window"><div id="screen"><span style="color:#e2e8f0">x</span></div></div><b style="color:#e2e8f0">y</b>'
    out = lt.rewrite_markup(html)
    assert '<span style="color:#e2e8f0">' in out and "var(--zn-text)" in out


def test_white_text_on_a_coloured_fill_stays_white():
    assert lt.rewrite_css(".b { background: #0284c7; color: #fff; }") == ".b { background: #0284c7; color: #fff; }"


def test_brand_coloured_text_gets_a_dark_shade():
    out = lt.rewrite_css(".t { color: var(--brand, #00f0ff); }")
    assert out == ".t { color: var(--lt-ink-brand, var(--brand, #00f0ff)); }"
    assert lt.rewrite_css(out) == out


def test_fallbacks_of_variables_the_light_theme_lacks():
    out = lt.rewrite_css(".t { color: var(--never-defined, #e2e8f0); }")
    assert "var(--never-defined, var(--lt-t-e2e8f0ff, #e2e8f0))" in out
    assert lt.rewrite_css(".t { color: var(--fg, #e2e8f0); }") == ".t { color: var(--fg, #e2e8f0); }"


def test_text_glows_are_off_in_the_light_theme():
    assert lt.rewrite_css(".t { text-shadow: 0 1px 3px rgba(0,0,0,0.9); }") == (
        ".t { text-shadow: var(--lt-text-shadow, 0 1px 3px rgba(0,0,0,0.9)); }"
    )
    assert "--lt-text-shadow: none;" in lt.palette_text()


def test_palette_applies_to_the_light_theme_only():
    text = lt.palette_text()
    assert "body.theme-light:not(.lcd-direct) {" in text
    assert text.count("{") == 1


# --- UX-10: semantic colour tokens --------------------------------------------------------

# var(--lt-...) colours left in the sources; lower it when you replace some, never raise it
HARD_CODED_BASELINE = 811


def _sources_text():
    for f in lt.sources():
        with open(f, encoding="utf-8") as fh:
            yield f, fh.read()


def test_every_semantic_token_is_defined_with_its_colour():
    with open(lt.TOKEN_FILE, encoding="utf-8") as f:
        text = f.read()
    for (_k, h), name in lt.SEMANTIC.items():
        assert lt.key(lt.parse(lt.token_value(name))) == h, name
        if name in lt.LIGHT_BY_HAND:
            continue
        assert f"--{name}: {lt.token_value(name)};" in text, f"{name} is not defined in 50-components.css"


def test_mapped_colours_use_their_token():
    left = []
    for f, text in _sources_text():
        for m in lt.VAR_USE.finditer(text):
            if (m.group(1), m.group(2)) in lt.SEMANTIC:
                left.append(f"{os.path.relpath(f, ROOT)}: {m.group(0)}")
    assert not left, "run: python scripts/light_theme.py tokens\n" + "\n".join(left[:10])


def test_hard_coded_colours_do_not_grow():
    n = sum(len(lt.VAR_USE.findall(text)) for _, text in _sources_text())
    assert n <= HARD_CODED_BASELINE, f"{n} hard-coded colours (baseline {HARD_CODED_BASELINE}): use a --zn- token"


def test_new_colours_get_the_token_directly():
    assert lt.rewrite_block("color: #fff; border: 1px solid rgba(255,255,255,0.08)") == (
        "color: var(--zn-text-strong); border: 1px solid var(--zn-line-8)"
    )
    assert lt.tokenize("background: var(--lt-b-0000004c, rgba(0, 0, 0, 0.3))") == "background: var(--zn-shade-30)"
    # a mismatched fallback is not swapped
    assert lt.tokenize("color: var(--lt-t-ffffffff, #eee)") == "color: var(--lt-t-ffffffff, #eee)"


def test_token_light_values_match_what_they_replaced():
    for name in lt.SEMANTIC.values():
        if name not in lt.LIGHT_BY_HAND:
            assert lt.token_light(name) is not None, name
    with open(lt.PALETTE, encoding="utf-8") as f:
        palette = f.read()
    assert f"--zn-shade-30: {lt.token_light('zn-shade-30')};" in palette
