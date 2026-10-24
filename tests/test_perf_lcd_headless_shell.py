"""The LCD uses Chromium's headless shell, not the full browser (PERF-2)."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_image_installs_the_headless_shell_only():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "chromium-headless-shell" in dockerfile
    assert "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/lib/chromium/chromium-headless-shell" in dockerfile
    assert "        chromium \\\n" not in dockerfile and "chromium-sandbox" not in dockerfile


def test_renderer_does_not_pass_a_headless_mode_the_shell_lacks():
    src = (ROOT / "backend/services/lcd_renderer.py").read_text()
    assert "--headless=shell" not in src
