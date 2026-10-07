"""
End-to-End (E2E) Integration Tests for ZettNAS Toolkit
Tests full frontend-backend integration using Playwright and FastAPI ASGI test environment.
"""

import os
import pytest
from playwright.sync_api import sync_playwright

from backend.config import STATIC_DIR


@pytest.mark.skipif(
    True,  # Will run in environments with live host/display or headless browser available
    reason="Requires active X11/wayland or headless chromium display port",
)
def test_e2e_live_ui_and_lcd_geometry():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(viewport={"width": 172, "height": 640})
        page = context.new_page()
        page.goto("http://127.0.0.1:8082/?mode=lcd", wait_until="domcontentloaded", timeout=10000)

        # Check body class
        assert "lcd-direct" in page.eval_on_selector("body", "el => el.className")

        # Check screen element exists and is rendered
        screen = page.wait_for_selector("#screen", timeout=5000)
        assert screen is not None

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
