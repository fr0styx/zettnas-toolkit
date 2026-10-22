"""
End-to-End (E2E) Integration Tests for ZettNAS Toolkit
Tests full frontend-backend integration using Playwright and live FastAPI environment.
"""

import json
import os
import secrets
import time
import urllib.request
import pytest
from playwright.sync_api import sync_playwright

import backend.config as config
from backend.config import STATIC_DIR


E2E_REQUIRED = os.environ.get("ZETTNAS_E2E_REQUIRED") == "1"


def _skip_or_fail(reason):
    """In CI (ZETTNAS_E2E_REQUIRED=1) a missing server or browser is a failure, not a skip."""
    if E2E_REQUIRED:
        pytest.fail(reason)
    pytest.skip(reason)


def test_e2e_server_reachable_when_required():
    if E2E_REQUIRED and not is_server_reachable():
        pytest.fail("ZETTNAS_E2E_REQUIRED=1 but the test server is not reachable on port 8082")


def is_server_reachable(base_url="http://127.0.0.1:8082"):
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_live_server_auth_token(base_url="http://127.0.0.1:8082"):
    """Obtains a valid session token for the live test server."""
    # 1. Attempt login with environment or default password
    for pwd in (os.environ.get("WEB_PASSWORD", "admin"), "admin"):
        try:
            req = urllib.request.Request(
                f"{base_url}/api/auth/login",
                data=json.dumps({"password": pwd}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("token"):
                    return data["token"]
        except Exception:
            pass

    # 2. If running where persistent users.db or sessions.json is mounted
    candidates = [
        os.environ.get("TEST_SERVER_DATA_DIR", ""),
        "/app/data",
        "/mnt/user/appdata/zettnas-toolkit/data",
        "data",
    ]
    for c in candidates:
        if not c:
            continue
        u_file = os.path.join(c, "users.db")
        if os.path.exists(u_file):
            try:
                from backend.users_db import create_user_session, get_user_by_username

                user = get_user_by_username("admin", db_path=u_file)
                user_id = user["id"] if user else "admin-00000000-0000-0000-0000-000000000001"
                tok = create_user_session(
                    user_id, "admin", ip="127.0.0.1", user_agent="test-runner", is_remembered=True, db_path=u_file
                )
                if tok:
                    return tok
            except Exception:
                pass
        s_file = os.path.join(c, "sessions.json")
        if os.path.exists(s_file):
            tok = secrets.token_urlsafe(32)
            try:
                with open(s_file, "r") as f:
                    sessions = json.load(f)
            except Exception:
                sessions = {}
            sessions[tok] = {"user": "admin", "created": time.time(), "expires": time.time() + 3600}
            try:
                with open(s_file, "w") as f:
                    json.dump(sessions, f)
                return tok
            except Exception:
                pass

    return None


@pytest.mark.skipif(
    not is_server_reachable(),
    reason="Live ZettNAS Toolkit test server not reachable at http://127.0.0.1:8082",
)
def test_e2e_live_ui_and_lcd_geometry():
    executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                executable_path=executable_path,
            )
        except Exception as e:
            _skip_or_fail(f"Playwright chromium browser not available on test runner: {e}")

        context = browser.new_context(viewport={"width": 172, "height": 640})
        page = context.new_page()
        page.goto(
            f"http://127.0.0.1:8082/?mode=lcd&lcd_token={config.LCD_INTERNAL_TOKEN}",
            wait_until="domcontentloaded",
            timeout=10000,
        )

        # Check body class
        assert "lcd-direct" in page.eval_on_selector("body", "el => el.className")

        # Check screen element exists and is rendered
        screen = page.wait_for_selector("#screen", timeout=5000)
        assert screen is not None

        browser.close()


@pytest.mark.skipif(
    not is_server_reachable(),
    reason="Live ZettNAS Toolkit test server not reachable at http://127.0.0.1:8082",
)
def _page_diagnostics(page, sel=None):
    """What the page looks like when the desktop didn't appear, for CI annotations."""
    return page.evaluate(
        """async () => {
            const SEL = """
        + json.dumps(sel)
        + """;
            const t0 = performance.now();
            let me = null;
            try { me = (await fetch('/api/auth/me')).status; } catch (e) { me = String(e); }
            const meMs = Math.round(performance.now() - t0);
            const vis = (id) => { const el = document.getElementById(id);
                return el ? getComputedStyle(el).display + '/' + getComputedStyle(el).visibility : 'missing'; };
            const slow = performance.getEntriesByType('resource')
                .filter((r) => r.duration > 500).map((r) => r.name.replace(location.origin, '') + ' ' + Math.round(r.duration) + 'ms');
            const target = SEL ? document.querySelector(SEL) : null;
            const chain = [];
            for (let el = target; el && el !== document.body; el = el.parentElement) {
                const cs = getComputedStyle(el);
                if (cs.display === 'none' || cs.visibility === 'hidden' || el.hidden) chain.push((el.id || el.className || el.tagName) + ':' + cs.display + '/' + cs.visibility);
            }
            return { target: target ? 'present' : 'missing', hiddenBy: chain, hint: localStorage.getItem('zettnas_signed_in'),
                     me, meMs, badge: vis('suite-brand-badge'), overlay: vis('login-overlay'), slow };
        }"""
    )


def test_e2e_live_desktop_session_and_badge():
    token = get_live_server_auth_token()
    if not token:
        _skip_or_fail("Could not obtain auth token for live test server")

    executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                executable_path=executable_path,
            )
        except Exception as e:
            _skip_or_fail(f"Playwright chromium browser not available on test runner: {e}")

        # Sign in through the real login form: the session must arrive as an HttpOnly
        # cookie and never be readable from page scripts (FE-05).
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        # Record anything the enforced Content-Security-Policy blocks (FE-06)
        context.add_init_script(
            "window.__csp = []; document.addEventListener('securitypolicyviolation', "
            "e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI + ' ' + e.sourceFile + ':' + e.lineNumber));"
        )
        page = context.new_page()
        page.goto("http://127.0.0.1:8082/", wait_until="domcontentloaded", timeout=12000)
        if page.is_visible("#login-toggle-manual"):
            page.click("#login-toggle-manual")
        if page.is_visible("#login-username"):
            page.fill("#login-username", "admin")
        page.fill("#login-password", os.environ.get("WEB_PASSWORD", "admin"))
        page.click("#login-btn")
        page.wait_for_function("() => localStorage.getItem('zettnas_signed_in') === '1'", timeout=8000)

        cookies = {c["name"]: c for c in context.cookies()}
        assert "zettnas_session" in cookies and cookies["zettnas_session"]["httpOnly"]
        assert page.evaluate("() => localStorage.getItem('zettnas_token')") is None
        assert page.evaluate("() => document.cookie").find("zettnas_session") == -1
        # An authenticated API call made by the page itself succeeds with just the cookie
        assert page.evaluate("async () => (await fetch('/api/auth/me')).status") == 200
        # and a reload keeps the session
        page.reload(wait_until="domcontentloaded")

        # Check suite badge has NAS WORKBENCH
        def _wait(sel):
            try:
                return page.wait_for_selector(sel, timeout=5000)
            except Exception:
                pytest.fail(f"{sel} not shown after reload: " + json.dumps(_page_diagnostics(page, sel)))

        badge = _wait("#suite-brand-badge")
        assert badge is not None
        assert "NAS WORKBENCH" in badge.inner_text()

        # The hardware settings button is in the page, but only shown on supported
        # appliance hardware, which a CI runner doesn't have.
        btn = page.wait_for_selector("#drawer-toggle-btn", state="attached", timeout=5000)
        assert btn is not None
        assert "HARDWARE SETTINGS" in (btn.text_content() or "").upper()

        # Check dock container exists
        dock = _wait("#os-dock-container")
        assert dock is not None

        page.wait_for_timeout(1500)
        violations = page.evaluate("() => window.__csp || []")
        assert violations == [], f"CSP violations: {violations}"

        browser.close()


def test_e2e_html_structure_and_assets():
    """Verify built static bundle integrity and critical DOM elements."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_path):
        _skip_or_fail("static/index.html is missing: run npm run build first")

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Verify critical components in index.html
    assert 'id="screen"' in html
    assert 'id="os-dock-container"' in html
    assert 'id="desktop-widgets-container"' in html
    assert 'id="login-overlay"' in html
    assert 'id="unraid-array-pill"' in html
    assert "studio-workbench" in html


def test_e2e_batch3_dom_elements():
    """Verify Batch 3 desktop UX, notification center filtering, and file manager DOM structures."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_path):
        _skip_or_fail("static/index.html is missing: run npm run build first")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="notif-center-panel"' in html
    assert 'id="notif-filter-bar"' in html
    assert 'id="notif-clear-all"' in html
    assert 'data-filter="all"' in html
    assert 'data-filter="error"' in html
    assert 'data-scrollable="true"' in html


def test_e2e_batch4_dom_elements():
    """Verify Batch 4 custom fan presets bar and SMART degradation banner in built HTML."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_path):
        _skip_or_fail("static/index.html is missing: run npm run build first")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="fan-presets-bar"' in html
    assert 'id="fan-preset-select"' in html
    assert 'id="btn-save-fan-preset"' in html
    assert 'id="btn-apply-fan-preset"' in html
    assert 'id="smart-degradation-banner"' in html


def test_e2e_batch5_dom_elements():
    """Verify Batch 5 UPS power telemetry and media slot auto-ingest controls in built HTML."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_path):
        _skip_or_fail("static/index.html is missing: run npm run build first")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="mgmt-ups-status"' in html
    assert 'id="mgmt-ups-model"' in html
    assert 'id="mgmt-ups-charge"' in html
    assert 'id="btn-copy-auto-ingest"' in html
    assert 'id="btn-copy-require-confirm"' in html
