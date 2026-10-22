"""OPS-11: the core image variant leaves out VMs and the LCD renderer."""

import importlib
import re


def test_dockerfile_installs_vm_and_browser_only_in_full():
    with open("Dockerfile", encoding="utf-8") as f:
        src = f.read()
    core_block = src.split("# Core: disks", 1)[1].split("&& rm -rf", 1)[0]
    assert "qemu" not in core_block and "chromium" not in core_block
    full_block = src.split('if [ "$VARIANT" = "full" ]', 1)[1].split("fi\n", 1)[0]
    for pkg in ("qemu-system-x86", "ovmf", "swtpm", "chromium", "fonts-noto-cjk"):
        assert re.search(rf"\b{re.escape(pkg)}\b", full_block)
    assert "ENV ZETTNAS_IMAGE_VARIANT=${VARIANT}" in src


def test_core_image_updates_to_core_tags(monkeypatch):
    from backend import config

    monkeypatch.setenv("ZETTNAS_IMAGE_VARIANT", "core")
    importlib.reload(config)
    try:
        assert config.variant_tag("latest") == "latest-core"
        assert config.variant_tag("edge") == "edge-core"
        assert config.variant_tag("latest-core") == "latest-core"
    finally:
        monkeypatch.delenv("ZETTNAS_IMAGE_VARIANT")
        importlib.reload(config)
    assert config.variant_tag("latest") == "latest"


def test_lcd_renderer_stops_cleanly_without_chromium(monkeypatch):
    from backend.services import lcd_renderer

    monkeypatch.setattr("backend.hardware.screen.is_auxiliary_lcd_present", lambda: True)
    monkeypatch.setenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/nonexistent/chromium")
    called = []
    monkeypatch.setattr(lcd_renderer, "find_fb_device", lambda **k: called.append(1))
    assert lcd_renderer.render_lcd_loop() is None
    assert called == []
