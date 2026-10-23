"""FE-10 / FE-21: axe accessibility checks in a real browser, on desktop and on a touch phone.

Fails on any "serious" or "critical" WCAG 2.2 A/AA issue, which includes target-size (touch
targets of at least 24px or enough space around them). Covers the main windows, the file
explorer with photos, the photo viewer and the Docker cleanup dialog. Needs the live test
server on :8082 (like test_e2e_integration.py) and node_modules/axe-core (npm ci). With
ZETTNAS_E2E_MEDIA_DIR set to a folder the server can browse, sample photos go there.
"""

import json
import os

import pytest

from tests.test_e2e_integration import _skip_or_fail, is_server_reachable

BASE = "http://127.0.0.1:8082"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AXE = os.path.join(ROOT, "node_modules", "axe-core", "axe.min.js")
REPORT_ONLY = os.environ.get("ZETTNAS_A11Y_REPORT") == "1"
MEDIA_DIR = os.environ.get("ZETTNAS_E2E_MEDIA_DIR", "")
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

pytestmark = pytest.mark.skipif(
    not is_server_reachable() and os.environ.get("ZETTNAS_E2E_REQUIRED") != "1",
    reason="Live ZettNAS Toolkit test server not reachable at http://127.0.0.1:8082",
)

VIEWS = [
    ("desktop", None, "body"),
    ("mission-control", "window.openManagementWindow && window.openManagementWindow()", "#management-window"),
    ("file-manager", "window.openFileManager && window.openFileManager()", ".file-manager-window"),
    ("containers", "window.openContainersManager && window.openContainersManager()", "#containers-manager-window"),
]


def _axe(page, selector):
    return page.evaluate(
        """async ([sel, tags]) => {
            const ctx = document.querySelector(sel) || document.body;
            const r = await axe.run(ctx, { runOnly: { type: 'tag', values: tags }, resultTypes: ['violations'] });
            return r.violations.filter(v => v.impact === 'serious' || v.impact === 'critical')
                .map(v => ({ id: v.id, impact: v.impact, count: v.nodes.length,
                             sample: v.nodes.slice(0, 3).map(n => n.target.join(' ') + ' :: ' + (n.failureSummary || '').split('\\n')[1]) }));
        }""",
        [selector, TAGS],
    )


def _photos():
    """A few sample photos in a folder the test server can browse; None when there is none."""
    if not MEDIA_DIR:
        return None
    from PIL import Image

    folder = os.path.join(MEDIA_DIR, "Photos")
    os.makedirs(folder, exist_ok=True)
    for i, size in enumerate([(1600, 1200), (1200, 1600), (1920, 1080)]):
        path = os.path.join(folder, f"IMG_{100 + i}.jpg")
        if not os.path.exists(path):
            Image.new("RGB", size, (40 + i * 60, 110, 170)).save(path, quality=80)
    return folder


def _login(page):
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=12000)
    page.add_script_tag(path=AXE)
    page.wait_for_timeout(800)
    login = _axe(page, "#login-overlay")
    if page.is_visible("#login-toggle-manual"):
        page.click("#login-toggle-manual")
    if page.is_visible("#login-username"):
        page.fill("#login-username", "admin")
    page.fill("#login-password", os.environ.get("ZETTNAS_E2E_PASSWORD") or os.environ.get("WEB_PASSWORD", "admin"))
    page.click("#login-btn")
    page.wait_for_function("() => localStorage.getItem('zettnas_signed_in') === '1'", timeout=8000)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#os-dock-container", timeout=8000)
    page.add_script_tag(path=AXE)
    page.wait_for_timeout(1500)
    return login


def _open(page, results, name, opener, selector):
    if opener:
        page.evaluate(f"() => {{ {opener}; }}")
        try:
            page.wait_for_selector(selector, state="visible", timeout=6000)
        except Exception:
            results[name] = [{"id": "view-did-not-open", "impact": "critical", "count": 1, "sample": [selector]}]
            return False
        page.wait_for_timeout(1200)
    results[name] = _axe(page, selector)
    return True


def _explorer_and_viewer(page, results, prefix, folder):
    if not folder:
        return
    _open(
        page,
        results,
        f"{prefix}explorer-photos",
        f"window.openFileManager({json.dumps(folder)})",
        ".file-manager-window",
    )
    page.evaluate(
        "() => { const b = document.querySelector('.file-manager-window .fm-btn-view-icon'); b && b.click(); }"
    )
    page.wait_for_timeout(1200)
    results[f"{prefix}explorer-icons"] = _axe(page, ".file-manager-window")
    page.evaluate(
        "() => { const b = document.querySelector('.file-manager-window .fm-btn-view-list'); b && b.click(); }"
    )
    page.wait_for_timeout(600)
    photo = os.path.join(folder, "IMG_100.jpg")
    _open(
        page,
        results,
        f"{prefix}photo-viewer",
        f"window.openFilePreviewModal({json.dumps(photo)}, 'IMG_100.jpg')",
        "#quicklook-modal-overlay",
    )
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)


def test_main_views_have_no_serious_accessibility_issues():
    if not os.path.exists(AXE):
        _skip_or_fail("axe-core is not installed (npm ci)")
    from playwright.sync_api import sync_playwright

    folder = _photos()
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
        results["login"] = _login(page)
        for name, opener, selector in VIEWS:
            _open(page, results, name, opener, selector)
        if page.is_visible("#btn-cw-prune"):
            page.evaluate("() => document.getElementById('btn-cw-prune').click()")  # the setup wizard may cover it
            try:
                page.wait_for_selector("#docker-prune-modal-window", state="visible", timeout=6000)
                page.wait_for_timeout(800)
                results["docker-cleanup"] = _axe(page, "#docker-prune-modal-window")
            except Exception:
                results["docker-cleanup"] = [
                    {
                        "id": "view-did-not-open",
                        "impact": "critical",
                        "count": 1,
                        "sample": ["#docker-prune-modal-window"],
                    }
                ]
            page.keyboard.press("Escape")
        _explorer_and_viewer(page, results, "", folder)
        context.close()

        # A touch phone: where small targets hurt most
        phone = browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, bypass_csp=True
        )
        page = phone.new_page()
        results["phone-login"] = _login(page)
        _explorer_and_viewer(page, results, "phone-", folder)
        phone.close()
        browser.close()

    print(json.dumps(results, indent=1))
    if not REPORT_ONLY:
        problems = {k: v for k, v in results.items() if v}
        assert not problems, "Serious accessibility issues:\n" + json.dumps(problems, indent=1)
