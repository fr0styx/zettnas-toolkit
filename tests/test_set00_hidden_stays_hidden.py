"""SET-00: a control marked hidden stays hidden.

The phone layout forces buttons, tabs and tiles to display with !important, which used to beat the
hidden attribute and an inline display:none. The rule that restores it lives in a cascade layer (an
!important declaration in a layer wins over every unlayered one); the two phone rules that force
display leave out controls a page hid with an inline style.
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLES = os.path.join(ROOT, "frontend", "src", "styles")
FORCED = (".btn-container-act", ".btn-pill-toggle", ".btn-locate-topo", ".mgmt-inner-tab", ".btn-webui-badge")


def _css(name):
    with open(os.path.join(STYLES, name), encoding="utf-8") as fh:
        return re.sub(r"/\*.*?\*/", "", fh.read(), flags=re.S)


def test_the_hidden_rule_is_in_a_layer_of_the_first_sheet():
    css = _css("00-tokens.css")
    layer = re.search(r"@layer hidden-attr\s*\{(.*?)\}\s*\}", css, flags=re.S)
    assert layer, "the hidden-attr layer is missing from 00-tokens.css"
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", layer.group(1))


def _rules(css):
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        yield selector.strip(), body


def test_the_phone_rules_do_not_force_a_control_hidden_inline():
    for name in ("23-mobile-stacked.css", "24-tablet-bottom-sheet.css"):
        forced = []
        for selector, body in _rules(_css(name)):
            if not re.search(r"display:\s*inline-flex\s*!important", body):
                continue
            for part in re.split(r",(?![^(]*\))", selector):
                first = re.match(r"(?:body\.mobile-mode\s+)?(\.[\w-]+)", part.strip())
                if first and first.group(1) in FORCED:
                    forced.append(part.strip())
        assert forced, f"{name}: the rule that keeps touch targets in a row is gone"
        bare = [s for s in forced if 'style*="display: none"' not in s or 'style*="display:none"' not in s]
        assert not bare, f"{name}: these selectors would show a control hidden with an inline style: {bare}"
