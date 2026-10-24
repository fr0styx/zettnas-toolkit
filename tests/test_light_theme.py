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
    css = ".x { color: #e2e8f0; background: #0d141e; border: 1px solid rgba(255,255,255,0.08); }"
    out = lt.rewrite_css(css)
    assert "var(--lt-t-e2e8f0ff, #e2e8f0)" in out
    assert "var(--lt-b-0d141eff, #0d141e)" in out
    assert "var(--lt-r-ffffff14, rgba(255,255,255,0.08))" in out
    # every fallback is exactly the original literal
    for _k, key, fallback in re.findall(r"var\(--lt-([tbr])-([0-9a-f]{8}), ([^()]*(?:\([^()]*\))?)\)", out):
        assert lt.key(lt.parse(fallback)) == key


def test_lcd_and_previews_are_left_alone():
    css = "#screen .card { color: #e2e8f0; } .dt-window { background: #0d141e; } body.theme-light .x { color: #fff; }"
    assert lt.rewrite_css(css) == css
    html = '<div id="console-window"><div id="screen"><span style="color:#e2e8f0">x</span></div></div><b style="color:#e2e8f0">y</b>'
    out = lt.rewrite_markup(html)
    assert '<span style="color:#e2e8f0">' in out and "var(--lt-t-e2e8f0ff" in out


def test_white_text_on_a_coloured_fill_stays_white():
    assert lt.rewrite_css(".b { background: #0284c7; color: #fff; }") == ".b { background: #0284c7; color: #fff; }"


def test_brand_coloured_text_gets_a_dark_shade():
    out = lt.rewrite_css(".t { color: var(--brand, #00f0ff); }")
    assert out == ".t { color: var(--lt-ink-brand, var(--brand, #00f0ff)); }"
    assert lt.rewrite_css(out) == out


def test_fallbacks_of_variables_the_light_theme_lacks():
    out = lt.rewrite_css(".t { color: var(--text, #e2e8f0); }")
    assert "var(--text, var(--lt-t-e2e8f0ff, #e2e8f0))" in out
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
