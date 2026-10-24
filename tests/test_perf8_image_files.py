"""The app image carries only what the app uses: the README screenshot lives in docs/ (PERF-8)."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_readme_screenshot_is_not_shipped_in_the_image():
    for folder in ("frontend/public", "static"):
        assert not list((ROOT / folder).rglob("ui-screenshot.png")), folder
    assert (ROOT / "docs/img/ui-screenshot.png").is_file()
    assert "docs/img/ui-screenshot.png" in (ROOT / "README.md").read_text(encoding="utf-8")
