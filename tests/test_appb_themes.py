"""The five themes (APP-B): the generated stylesheets, their contrast and look.js's tables."""

import json
import os
import re
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import themes  # noqa: E402

PAL = json.loads(Path(themes.PALETTES).read_text(encoding="utf-8"))
LOOK_JS = Path(ROOT, "frontend", "src", "look.js").read_text(encoding="utf-8")


def _table(name):
    body = re.search(r"const " + name + r" = \{(.*?)\n\};", LOOK_JS, flags=re.S).group(1)
    return {k: re.findall(r"'(#[0-9a-f]{6})'", v) for k, v in re.findall(r"(\w+): (\[[^\]]*\])", body)}


def test_the_stylesheets_match_the_generator():
    for theme in themes.THEMES:
        path = os.path.join(themes.OUT_DIR, f"{theme}.css")
        assert Path(path).read_text(encoding="utf-8") == themes.render(theme, PAL), (
            f"run python scripts/themes.py write ({theme})"
        )


def test_every_text_and_border_pair_reads_in_every_theme_and_at_every_tint():
    assert themes.contrast_failures(PAL) == []


def test_status_colours_are_the_same_in_every_theme():
    for theme in themes.THEMES:
        for mode in ("dark", "light"):
            r = themes.roles(theme, mode, PAL)
            for k, v in r.items():
                if any(k.startswith(s) or k == f"on-{s}" for s in themes.STATUS):
                    assert v == PAL["themes"]["lagoon"][mode][k], (theme, mode, k)


def test_lagoon_is_the_brand_palette():
    # docs/BRAND.md: Lagoon's roles come from the brand tokens, unchanged (only the border is
    # lifted to 3:1 on every panel)
    r = themes.roles("lagoon", "dark", PAL)
    assert (r["primary"], r["accent"], r["bg"]) == ("#33cdb8", "#f6b44c", "#0a1113")
    assert themes.roles("lagoon", "light", PAL)["primary"] == "#0a7a70"


def test_teal_moves_to_the_theme_and_status_colours_stay():
    assert themes.move("#33cdb8", "fjord", "dark", PAL) != "#33cdb8"  # Lagoon's teal
    for status in ("#46c776", "#f2b237", "#f26b5e", "#8db1ff", "#ffffff", "rgba(255, 255, 255, 0.08)"):
        assert themes.move(status, "canyon", "dark", PAL) == status


def test_look_js_knows_the_palettes_page_and_main_colours():
    page, primary = _table("PAGE"), _table("PRIMARY")
    for theme in themes.THEMES:
        t = PAL["themes"][theme]
        assert page[theme] == [t["dark"]["bg"], t["light"]["bg"]], theme
        assert primary[theme] == [t["dark"]["primary"], t["light"]["primary"]], theme


def test_look_js_translates_old_names_as_the_palettes_say():
    for old, new in PAL["migration"].items():
        if not isinstance(new, dict):
            continue  # yak: unchanged, outside the family
        m = re.search(r"\b" + old + r": \{([^}]*)\}", LOOK_JS)
        assert m, old
        entry = dict(re.findall(r"(\w+): '?(\w+)'?", m.group(1)))
        assert entry.get("theme") == new["theme"], old
        if "mode" in new:
            assert entry.get("mode") == new["mode"], old
        if new.get("trueBlack"):
            assert entry.get("trueBlack") == "true", old


def test_look_js_caps_the_tint_like_the_generator():
    caps = dict(re.findall(r"(\w+): (\d+(?:\.\d+)?)", re.search(r"const TINT_MAX = \{([^}]*)\}", LOOK_JS).group(1)))
    assert {k: float(v) for k, v in caps.items()} == themes.TINT_MAX
