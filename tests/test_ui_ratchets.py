"""UX-11: inline styles and unstyled buttons only go down, file by file."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ui_buttons  # noqa: E402
import ui_ratchets  # noqa: E402


def test_no_file_gains_inline_styles_or_unstyled_buttons():
    problems = ui_ratchets.over(ui_ratchets.current(), ui_ratchets.load_baseline())
    assert not problems, "Use a class, a --zn- token or a primitive (frontend/src/ui/primitives.js):\n" + "\n".join(
        problems
    )


def test_the_counts():
    text = '<div style="x"></div><button>a</button><button class="btn-pill-toggle">b</button><b style=\'y\'>'
    assert ui_ratchets.counts_for(text) == {"styles": 2, "buttons": 1}


def test_a_new_file_starts_at_zero():
    assert ui_ratchets.over({"new.js": {"styles": 1, "buttons": 0}}, {}) == ["new.js: 1 styles (baseline 0)"]
    assert ui_ratchets.over({"old.js": {"styles": 3, "buttons": 1}}, {"old.js": {"styles": 4, "buttons": 1}}) == []


def test_inline_styled_buttons_become_the_system_button():
    old = (
        '<button id="ok" style="padding: 7px 18px; font-size: var(--zn-fs-xs); font-weight: 700; '
        'background: var(--brand, #0ea5e9); border: none; flex: 1;">OK</button>'
    )
    new, n = ui_buttons.rewrite(old)
    assert n == 1
    assert new == '<button id="ok" class="btn-pill-toggle is-primary is-small" style="flex: 1;">OK</button>'


def test_the_button_codemod_leaves_links_classes_and_fills_alone():
    for keep in (
        '<button style="background:none; border:none; color:var(--muted); padding:2px 4px;">link</button>',
        '<button class="x" style="padding: 7px; background: #222; border: none;">classed</button>',
        '<button style="padding: 7px; background: linear-gradient(red, blue); border: none;">fill</button>',
        '<button style="padding: 7px; background: #7c3aed; border: none; color: #fff;">purple</button>',
        '<button style="padding: ${p}px; background: none; border: 0;">template</button>',
    ):
        assert ui_buttons.rewrite(keep) == (keep, 0), keep
    danger = (
        '<button style="padding: 7px 18px; background: var(--crit, #ef4444); border: none; color: #fff;">Del</button>'
    )
    assert 'class="btn-pill-toggle is-danger"' in ui_buttons.rewrite(danger)[0]
    ghost = '<button style="padding: 6px 10px; background: transparent; border: none; color: #94a3b8;">Tab</button>'
    assert 'class="btn-pill-toggle is-ghost"' in ui_buttons.rewrite(ghost)[0]
    plain = '<button style="padding: 7px 16px; background: var(--zn-glaze-8); border: 1px solid #333;">Cancel</button>'
    assert ui_buttons.rewrite(plain)[0].startswith('<button class="btn-pill-toggle">')
