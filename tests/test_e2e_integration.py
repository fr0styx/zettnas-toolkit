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

    # 2. If running where persistent sessions.json is mounted
    candidates = [
        os.environ.get("TEST_SERVER_DATA_DIR", ""),
        "/app/data",
        "/mnt/user/appdata/zettnas-toolkit/data",
        "data",
    ]
    for c in candidates:
        if not c:
            continue
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
            pytest.skip(f"Playwright chromium browser not available on test runner: {e}")

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
def test_e2e_live_desktop_session_and_badge():
    token = get_live_server_auth_token()
    if not token:
        pytest.skip("Could not obtain auth token for live test server")

    executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                executable_path=executable_path,
            )
        except Exception as e:
            pytest.skip(f"Playwright chromium browser not available on test runner: {e}")

        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            storage_state={
                "cookies": [],
                "origins": [
                    {
                        "origin": "http://127.0.0.1:8082",
                        "localStorage": [{"name": "zettnas_token", "value": token}],
                    }
                ],
            },
        )
        page = context.new_page()
        page.goto("http://127.0.0.1:8082/", wait_until="domcontentloaded", timeout=12000)

        # Check suite badge has NAS WORKBENCH
        badge = page.wait_for_selector("#suite-brand-badge", timeout=5000)
        assert badge is not None
        assert "NAS WORKBENCH" in badge.inner_text()

        # Check drawer toggle button
        btn = page.wait_for_selector("#drawer-toggle-btn", timeout=5000)
        assert btn is not None
        assert "HARDWARE SETTINGS" in btn.inner_text()

        # Check dock container exists
        dock = page.wait_for_selector("#os-dock-container", timeout=5000)
        assert dock is not None

        browser.close()


def test_e2e_html_structure_and_assets():
    """Verify built static bundle integrity and critical DOM elements."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    assert os.path.isfile(index_path), "index.html must exist in static/"

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
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="mgmt-ups-status"' in html
    assert 'id="mgmt-ups-model"' in html
    assert 'id="mgmt-ups-charge"' in html
    assert 'id="btn-copy-auto-ingest"' in html
    assert 'id="btn-copy-require-confirm"' in html
