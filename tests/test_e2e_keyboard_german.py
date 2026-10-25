"""UX-8 and UX-13 in a real browser: a keyboard-only journey, and German text that fits.

Needs the live test server, like test_e2e_a11y.py. The German check lists buttons, labels and
headings whose text is cut off; overflows already known are in tests/german_overflow_baseline.json
(ZETTNAS_GERMAN_UPDATE=1 rewrites it, to remove entries only, please). ZETTNAS_GERMAN_SHOTS=<dir>
saves a screenshot of each view for a native speaker's review.
"""

import json
import os

import pytest

from tests.test_e2e_a11y import BASE, PANES
from tests.test_e2e_integration import _skip_or_fail, is_server_reachable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "tests", "german_overflow_baseline.json")
UPDATE = os.environ.get("ZETTNAS_GERMAN_UPDATE") == "1"
SHOTS = os.environ.get("ZETTNAS_GERMAN_SHOTS", "")
PASSWORD = os.environ.get("ZETTNAS_E2E_PASSWORD") or os.environ.get("WEB_PASSWORD", "admin")

pytestmark = pytest.mark.skipif(
    not is_server_reachable(BASE) and os.environ.get("ZETTNAS_E2E_REQUIRED") != "1",
    reason="Live ZettNAS Toolkit test server not reachable",
)

CUT_OFF = """(root) => {
  const sel = 'button, label, h1, h2, h3, .mgmt-sidebar-text, .btn-pill-toggle, .mgmt-app-title, .setup-steps li';
  const out = [];
  for (const el of (root || document).querySelectorAll(sel)) {
    if (!el.offsetParent || !el.textContent.trim()) continue;
    const st = getComputedStyle(el);
    const clips = st.overflow === 'hidden' || st.overflowX === 'hidden' || st.textOverflow === 'ellipsis' || st.whiteSpace === 'nowrap';
    if (clips && el.scrollWidth > el.clientWidth + 2) out.push((el.id ? '#' + el.id + ' ' : '') + el.textContent.trim().slice(0, 40));
  }
  return [...new Set(out)].sort();
}"""


def _browser(p):
    try:
        return p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"),
        )
    except Exception as e:
        _skip_or_fail(f"Playwright chromium not available: {e}")


def _sign_in_with_keyboard(page):
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=12000)
    page.wait_for_timeout(600)
    if page.is_visible("#login-toggle-manual"):
        page.focus("#login-toggle-manual")
        page.keyboard.press("Enter")
    if page.is_visible("#login-username"):
        page.focus("#login-username")
        page.keyboard.press("Control+A")  # the name may be filled in already
        page.keyboard.type("admin")
    page.focus("#login-password")
    page.keyboard.press("Control+A")
    page.keyboard.type(PASSWORD)
    page.keyboard.press("Enter")
    try:
        page.wait_for_function("() => localStorage.getItem('zettnas_signed_in') === '1'", timeout=4000)
    except Exception:
        page.focus("#login-btn")  # Enter in the field didn't submit: the button, by keyboard
        page.keyboard.press("Enter")
        page.wait_for_function("() => localStorage.getItem('zettnas_signed_in') === '1'", timeout=8000)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#management-desktop-icon", state="visible", timeout=15000)
    page.wait_for_timeout(1500)


def test_a_keyboard_only_journey():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        _sign_in_with_keyboard(page)
        page.evaluate(
            "() => { const m = document.getElementById('setup-wizard-modal'); if (m) m.classList.remove('open'); }"
        )
        # Mission Control opens from the keyboard, takes focus, and Escape gives it back
        page.focus("#management-desktop-icon")
        page.keyboard.press("Enter")
        page.wait_for_selector("#management-window", state="visible", timeout=8000)
        page.wait_for_timeout(800)
        assert page.evaluate("() => document.getElementById('management-window').contains(document.activeElement)"), (
            "focus did not move into Mission Control"
        )
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        assert (
            page.evaluate("() => document.activeElement && document.activeElement.id") == "management-desktop-icon"
        ), "focus did not come back"
        # the setup wizard can be walked with Tab and Enter
        page.evaluate("() => window.openSetupWizard && window.openSetupWizard(null, true)")
        page.wait_for_selector("#setup-wizard-modal", state="visible", timeout=6000)
        for _ in range(40):
            if page.evaluate("() => document.activeElement && document.activeElement.id") == "setup-wizard-next":
                break
            page.keyboard.press("Tab")
        assert page.evaluate("() => document.activeElement && document.activeElement.id") == "setup-wizard-next", (
            "Next can't be reached with Tab"
        )
        page.keyboard.press("Enter")
        assert page.is_visible("#setup-current-pwd"), "Enter on Next did not move to the password step"
        browser.close()


def test_german_text_fits():
    from playwright.sync_api import sync_playwright

    found = {}
    with sync_playwright() as p:
        browser = _browser(p)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script("localStorage.setItem('zettnas_language', 'de')")
        page = context.new_page()
        _sign_in_with_keyboard(page)

        def look(name, selector=None):
            found[name] = page.evaluate(CUT_OFF, page.query_selector(selector) if selector else None)
            if SHOTS:
                os.makedirs(SHOTS, exist_ok=True)
                page.screenshot(path=os.path.join(SHOTS, f"de-{name}.png"))

        look("desktop")
        page.evaluate("() => window.openManagementWindow && window.openManagementWindow()")
        page.wait_for_selector("#management-window", state="visible", timeout=8000)
        page.wait_for_timeout(1200)
        look("mission-control", "#management-window")
        for pane in PANES:
            page.evaluate(f"() => (window.openManagementSection || window.openManagementWindow)({json.dumps(pane)})")
            try:
                page.wait_for_selector(f"#{pane}", state="visible", timeout=6000)
            except Exception:
                continue
            page.wait_for_timeout(700)
            look(pane, "#management-window")
        page.evaluate("() => window.openSetupWizard && window.openSetupWizard(null, true)")
        page.wait_for_timeout(700)
        look("setup-wizard", "#setup-wizard-modal")
        browser.close()

    found = {k: v for k, v in found.items() if v}
    if UPDATE:
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(found, f, indent=1, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        return
    known = {}
    if os.path.exists(BASELINE):
        with open(BASELINE, encoding="utf-8") as f:
            known = json.load(f)
    new = {k: [x for x in v if x not in known.get(k, [])] for k, v in found.items()}
    new = {k: v for k, v in new.items() if v}
    assert not new, "German text cut off:\n" + json.dumps(new, indent=1, ensure_ascii=False)
