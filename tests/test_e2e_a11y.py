"""FE-10 / FE-21: axe accessibility checks on the five main views, in a real browser.

Fails on any "serious" or "critical" WCAG 2.1 A/AA issue. Needs the live test server on
:8082 (like test_e2e_integration.py) and node_modules/axe-core (npm ci).
"""

import json
import os

import pytest

from tests.test_e2e_integration import _skip_or_fail, is_server_reachable

BASE = "http://127.0.0.1:8082"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AXE = os.path.join(ROOT, "node_modules", "axe-core", "axe.min.js")
REPORT_ONLY = os.environ.get("ZETTNAS_A11Y_REPORT") == "1"

pytestmark = pytest.mark.skipif(
    not is_server_reachable() and os.environ.get("ZETTNAS_E2E_REQUIRED") != "1",
    reason="Live ZettNAS Toolkit test server not reachable at http://127.0.0.1:8082",
)

VIEWS = [
    ("login", None, "#login-overlay"),
    ("desktop", None, "body"),
    ("mission-control", "window.openManagementWindow && window.openManagementWindow()", "#management-window"),
    ("file-manager", "window.openFileManager && window.openFileManager()", ".file-manager-window"),
    ("containers", "window.openContainersManager && window.openContainersManager()", "#containers-manager-window"),
]


def _axe(page, selector):
    return page.evaluate(
        """async (sel) => {
            const ctx = document.querySelector(sel) || document.body;
            const r = await axe.run(ctx, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
                                           resultTypes: ['violations'] });
            return r.violations.filter(v => v.impact === 'serious' || v.impact === 'critical')
                .map(v => ({ id: v.id, impact: v.impact, count: v.nodes.length,
                             sample: v.nodes.slice(0, 3).map(n => n.target.join(' ') + ' :: ' + (n.failureSummary || '').split('\\n')[1]) }));
        }""",
        selector,
    )


def test_main_views_have_no_serious_accessibility_issues():
    if not os.path.exists(AXE):
        _skip_or_fail("axe-core is not installed (npm ci)")
    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"),
            )
        except Exception as e:
            _skip_or_fail(f"Playwright chromium not available: {e}")
        # axe is injected as a script, so the page's CSP must not block it in this test only
        context = browser.new_context(viewport={"width": 1440, "height": 900}, bypass_csp=True)
        page = context.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=12000)
        page.add_script_tag(path=AXE)
        page.wait_for_timeout(800)
        results["login"] = _axe(page, "#login-overlay")

        if page.is_visible("#login-toggle-manual"):
            page.click("#login-toggle-manual")
        if page.is_visible("#login-username"):
            page.fill("#login-username", "admin")
        page.fill("#login-password", os.environ.get("WEB_PASSWORD", "admin"))
        page.click("#login-btn")
        page.wait_for_function("() => localStorage.getItem('zettnas_signed_in') === '1'", timeout=8000)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#os-dock-container", timeout=8000)
        page.add_script_tag(path=AXE)
        page.wait_for_timeout(1500)
        for name, opener, selector in VIEWS[1:]:
            if opener:
                page.evaluate(f"() => {{ {opener}; }}")
                try:
                    page.wait_for_selector(selector, state="visible", timeout=6000)
                except Exception:
                    results[name] = [
                        {"id": "view-did-not-open", "impact": "critical", "count": 1, "sample": [selector]}
                    ]
                    continue
                page.wait_for_timeout(1200)
            results[name] = _axe(page, selector)
        browser.close()

    print(json.dumps(results, indent=1))
    if not REPORT_ONLY:
        problems = {k: v for k, v in results.items() if v}
        assert not problems, "Serious accessibility issues:\n" + json.dumps(problems, indent=1)
