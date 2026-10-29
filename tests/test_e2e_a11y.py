"""FE-10 / FE-21: axe accessibility checks in a real browser, on desktop and on a touch phone.

Fails on any "serious" or "critical" WCAG 2.2 A/AA issue, which includes target-size (touch
targets of at least 24px or enough space around them). Covers the main windows, the setup
wizard, every Settings pane, the light theme, the file explorer with photos, the photo
viewer and the Docker cleanup dialog, on desktop and on a phone (UX-9). Needs the live test
server (ZETTNAS_E2E_BASE, default :8082, like test_e2e_integration.py) and
node_modules/axe-core (npm ci). With ZETTNAS_E2E_MEDIA_DIR set to a folder the server can
browse, sample photos go there.

Issues already known when a view was added are listed in tests/a11y_baseline.json; any other
issue fails. ZETTNAS_A11Y_UPDATE=1 rewrites that file (only to remove entries, please).
"""

import json
import os

import pytest

from tests.test_e2e_integration import _skip_or_fail, is_server_reachable

BASE = os.environ.get("ZETTNAS_E2E_BASE", "http://127.0.0.1:8082")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AXE = os.path.join(ROOT, "node_modules", "axe-core", "axe.min.js")
REPORT_ONLY = os.environ.get("ZETTNAS_A11Y_REPORT") == "1"
UPDATE = os.environ.get("ZETTNAS_A11Y_UPDATE") == "1"
BASELINE = os.path.join(ROOT, "tests", "a11y_baseline.json")
MEDIA_DIR = os.environ.get("ZETTNAS_E2E_MEDIA_DIR", "")
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
# UX-8: moderate issues count too (ZETTNAS_A11Y_IMPACTS narrows it for a quick look)
IMPACTS = os.environ.get("ZETTNAS_A11Y_IMPACTS", "moderate,serious,critical").split(",")

pytestmark = pytest.mark.skipif(
    not is_server_reachable(BASE) and os.environ.get("ZETTNAS_E2E_REQUIRED") != "1",
    reason="Live ZettNAS Toolkit test server not reachable at http://127.0.0.1:8082",
)

VIEWS = [
    ("desktop", None, "body"),
    ("mission-control", "window.openManagementWindow && window.openManagementWindow()", "#management-window"),
    ("file-manager", "window.openFileManager && window.openFileManager()", ".file-manager-window"),
    ("containers", "window.openContainersManager && window.openContainersManager()", "#containers-manager-window"),
]


# Settings panes, opened one by one (UX-9)
PANES = [
    "mgmt-pane-storage-shares",
    "mgmt-pane-storage-disks",
    "mgmt-pane-storage-remotes",
    "mgmt-pane-network",
    "mgmt-pane-vms-list",
    "mgmt-pane-security",
    "mgmt-pane-users",
    "mgmt-pane-notifications",
    "mgmt-pane-backups",
    "mgmt-pane-events",
    "mgmt-pane-about",
    "mgmt-pane-wallpaper",
    "mgmt-pane-language",
]
MGMT = "#management-window"


def _panes(page, results, prefix):
    for pane in PANES:
        page.evaluate(f"() => (window.openManagementSection || window.openManagementWindow)({json.dumps(pane)})")
        try:
            page.wait_for_selector(f"#{pane}", state="visible", timeout=6000)
        except Exception:
            results[f"{prefix}{pane}"] = [
                {"id": "view-did-not-open", "impact": "critical", "count": 1, "sample": [pane]}
            ]
            continue
        page.wait_for_timeout(900)
        results[f"{prefix}{pane}"] = _axe(page, MGMT)


def _axe(page, selector):
    return page.evaluate(
        """async ([sel, tags, impacts]) => {
            const ctx = document.querySelector(sel) || document.body;
            const r = await axe.run(ctx, { runOnly: { type: 'tag', values: tags }, resultTypes: ['violations'] });
            return r.violations.filter(v => impacts.includes(v.impact))
                .map(v => ({ id: v.id, impact: v.impact, count: v.nodes.length,
                             sample: v.nodes.slice(0, 3).map(n => n.target.join(' ') + ' :: ' + (n.failureSummary || '').split('\\n')[1]) }));
        }""",
        [selector, TAGS, IMPACTS],
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
    # the desktop dock, or the launcher on a phone (phone mode hides the desktop, UX-13)
    page.wait_for_function(
        "() => ['#os-dock-container', '#phone-launcher'].some((s) => document.querySelector(s)"
        "?.checkVisibility({ visibilityProperty: true }))",
        timeout=8000,
    )
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
        # the hardware-settings drawer loads after the first paint: checked open, every time
        _open(page, results, "settings-drawer", "window.openDrawer && window.openDrawer()", "#led-drawer")
        page.keyboard.press("Escape")
        page.evaluate("() => document.getElementById('drawer-close-btn')?.click()")
        page.wait_for_timeout(400)
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
        # the setup wizard, one step at a time
        page.evaluate("() => window.openSetupWizard && window.openSetupWizard(null, false)")
        try:
            page.wait_for_selector("#setup-wizard-modal", state="visible", timeout=6000)
            page.wait_for_timeout(600)
            for step in (1, 2, 3, 4, 5, 6):  # the six-step setup (UX-17)
                results[f"wizard-step-{step}"] = _axe(page, "#setup-wizard-modal")
                if step in (1, 3, 4, 5):
                    page.click("#setup-wizard-next")
                elif step == 2:
                    page.evaluate(
                        "() => ['setup-current-pwd','setup-new-pwd','setup-confirm-pwd'].forEach((id, i) => { "
                        "const el = document.getElementById(id); if (el) el.value = i ? 'Axe-Check-Pass-1' : 'x'; })"
                    )
                    page.click("#setup-wizard-next")
                page.wait_for_timeout(300)
            page.evaluate("() => document.getElementById('setup-wizard-skip')?.click()")
        except Exception:
            results["wizard-step-1"] = [
                {"id": "view-did-not-open", "impact": "critical", "count": 1, "sample": ["#setup-wizard-modal"]}
            ]
        page.wait_for_timeout(400)
        _panes(page, results, "")
        # the light theme
        page.evaluate("() => document.body.classList.add('theme-light')")
        page.wait_for_timeout(400)
        results["light-desktop"] = _axe(page, "body")
        _panes(page, results, "light-")
        page.evaluate("() => document.body.classList.remove('theme-light')")
        context.close()

        # A touch phone: where small targets hurt most
        phone = browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, bypass_csp=True
        )
        page = phone.new_page()
        results["phone-login"] = _login(page)
        _explorer_and_viewer(page, results, "phone-", folder)
        _open(
            page, results, "phone-mission-control", "window.openManagementWindow && window.openManagementWindow()", MGMT
        )
        phone.close()
        browser.close()

    print(json.dumps(results, indent=1))
    known = {}
    if os.path.exists(BASELINE):
        with open(BASELINE, encoding="utf-8") as f:
            known = json.load(f)
    if UPDATE:
        found = {k: sorted({v["id"] for v in vs}) for k, vs in results.items() if vs}
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(found, f, indent=1, sort_keys=True)
            f.write("\n")
        return
    if not REPORT_ONLY:
        problems = {k: [v for v in vs if v["id"] not in known.get(k, [])] for k, vs in results.items()}
        problems = {k: v for k, v in problems.items() if v}
        assert not problems, "Serious accessibility issues:\n" + json.dumps(problems, indent=1)
