import base64
import io
import mmap
import os
import time

from PIL import Image
from playwright.sync_api import sync_playwright

from backend import config
from backend.config import ENABLE_FB, HOST_SYS, LCD_FORMAT, LCD_FPS, PORT, logger
from backend.hardware.screen import (
    find_fb_device,
    get_effective_brightness,
    set_fb_blank,
    set_screen_brightness,
)
from backend.state import Z_STATE


def discover_fb_geometry() -> tuple[int, int, int]:
    """
    Returns (width, height, stride).
    Defaults to (172, 640, 704) matching the physical rotated LCD on Zettbox.
    """
    default_w = 172
    default_h = 640
    default_stride = 704

    bases = ["/sys/class/graphics/fb0", "/host/sys/class/graphics/fb0"]
    if HOST_SYS and os.path.isdir(os.path.join(HOST_SYS, "class/graphics/fb0")):
        bases.insert(0, os.path.join(HOST_SYS, "class/graphics/fb0"))

    for base in bases:
        stride_file = os.path.join(base, "stride")
        vsize_file = os.path.join(base, "virtual_size")
        if os.path.exists(stride_file):
            try:
                with open(stride_file) as f:
                    s_val = int(f.read().strip())
                    if s_val > 0:
                        default_stride = s_val
            except (OSError, ValueError):
                pass
        if os.path.exists(vsize_file):
            try:
                with open(vsize_file) as f:
                    content = f.read().strip()
                    parts = [int(p.strip()) for p in content.split(",") if p.strip()]
                    if len(parts) == 2:
                        w, h = min(parts), max(parts)
                        if w > 0 and h > 0:
                            default_w, default_h = w, h
            except (OSError, ValueError):
                pass
    return default_w, default_h, default_stride


def discover_fb_bpp() -> int:
    """
    Discovers bits_per_pixel from sysfs (/sys/class/graphics/fb0/bits_per_pixel).
    Defaults to 32 (or 16 if 16-bit).
    """
    default_bpp = 32
    bases = ["/sys/class/graphics/fb0", "/host/sys/class/graphics/fb0"]
    if HOST_SYS and os.path.isdir(os.path.join(HOST_SYS, "class/graphics/fb0")):
        bases.insert(0, os.path.join(HOST_SYS, "class/graphics/fb0"))

    for base in bases:
        bpp_file = os.path.join(base, "bits_per_pixel")
        if os.path.exists(bpp_file):
            try:
                with open(bpp_file) as f:
                    b_val = int(f.read().strip())
                    if b_val in (16, 24, 32):
                        return b_val
            except (OSError, ValueError):
                pass
    return default_bpp


def render_lcd_loop():
    """
    Active Framebuffer Streamer:
    - Dynamic discovery of backlight sysfs and framebuffer stride/geometry.
    - Viewport oriented 172x640 via CSS 90deg rotation (No CPU matrix rotate overhead).
    - Screen-off pause: 0 FPS when screen blanked/night mode.
    - Adaptive FPS: 1 FPS when idle/static, bursting to target FPS on telemetry changes.
    - Single mmap memory block write into video memory per frame.
    """
    if Z_STATE.shutting_down:
        return

    from backend.hardware.screen import is_auxiliary_lcd_present

    if not is_auxiliary_lcd_present():
        logger.info("[LCD] No auxiliary front-panel LCD detected or ENABLE_FB=0. Running web-only.")
        return

    chromium = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "/usr/lib/chromium/chromium-headless-shell")
    if not os.path.exists(chromium):
        logger.info(
            "[LCD] The core image has no LCD renderer (no Chromium). Use the full image to drive the front LCD."
        )
        return

    fb_path = find_fb_device(writable_only=True)
    if not fb_path:
        logger.info(
            "[LCD] Framebuffer device (/dev/fb0, /host/dev/fb0) not present, inaccessible, or is a directory. Running web-only."
        )
        return

    time.sleep(2)
    url = f"http://127.0.0.1:{PORT}/?mode=lcd&lcd_token={config.LCD_INTERNAL_TOKEN}"

    eff_bri = get_effective_brightness()
    set_fb_blank(eff_bri > 0)
    set_screen_brightness(eff_bri)

    fb_width, fb_height, stride = discover_fb_geometry()
    bpp = discover_fb_bpp()
    row_bytes = fb_width * (2 if bpp == 16 else 4)
    total_fb_bytes = fb_height * stride

    target_fps = max(1, LCD_FPS)
    frame_interval = 1.0 / target_fps
    lcd_format = LCD_FORMAT

    logger.info(
        f"[LCD] Starting active renderer: {fb_width}x{fb_height} ({bpp}bpp) @ {target_fps} FPS -> {fb_path} (stride {stride}, format {lcd_format})"
    )

    chromium_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-extensions",
        "--disable-component-update",
        "--disable-sync",
        "--disable-translate",
        "--mute-audio",
        "--no-first-run",
        "--disable-default-apps",
        "--hide-scrollbars",
        "--disable-breakpad",
        "--disable-features=Translate,OptimizationHints,MediaRouter",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--ignore-gpu-blocklist",
        "--js-flags=--max-old-space-size=64",
        "--disk-cache-size=1",
        "--media-cache-size=1",
    ]

    retry_delay = 2.0
    while not Z_STATE.shutting_down:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=chromium_args,
                    executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"),
                )
                context = browser.new_context(**lcd_context_options(fb_width, fb_height))
                context.set_extra_http_headers({"Authorization": f"Bearer {config.LCD_INTERNAL_TOKEN}"})
                try:
                    context.add_cookies(
                        [
                            {
                                "name": "zettnas_session",
                                "value": config.LCD_INTERNAL_TOKEN,
                                "domain": "127.0.0.1",
                                "path": "/",
                            }
                        ]
                    )
                except Exception as e:
                    logger.debug(f"[LCD] Failed to add internal session cookie: {e}")
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                Z_STATE.lcd_renderer_active = True

                cdp = context.new_cdp_session(page)
                shot_params = {"format": "jpeg" if lcd_format == "jpeg" else "png", "optimizeForSpeed": True}
                if lcd_format == "jpeg":
                    shot_params["quality"] = 95
                retry_delay = 2.0

                with open(fb_path, "r+b") as fb_file:
                    fb_mem = mmap.mmap(fb_file.fileno(), total_fb_bytes, mmap.MAP_SHARED, mmap.PROT_WRITE)
                    try:
                        fb = _Framebuffer(fb_mem, total_fb_bytes, stride, bpp)
                        fb.clear()
                        streamed = LCD_CAPTURE != "poll" and _screencast_frames(
                            page, cdp, fb, shot_params["format"], frame_interval, fb_width, fb_height
                        )
                        if not streamed:
                            _poll_frames(page, cdp, fb, shot_params, frame_interval)
                    finally:
                        try:
                            fb_mem.close()
                        except Exception:
                            logger.debug("backend.services.lcd_renderer.render_lcd_loop: ignored error", exc_info=True)

            if Z_STATE.shutting_down:
                break

        except Exception as e:
            Z_STATE.lcd_renderer_active = False
            if Z_STATE.shutting_down:
                break
            logger.info(f"[LCD] Active render loop error: {e}. Reconnecting in {retry_delay:.1f}s...")
            time.sleep(retry_delay)
            retry_delay = min(60.0, retry_delay * 1.5)

    Z_STATE.lcd_renderer_active = False
    logger.info("[LCD] Active render loop terminated cleanly.")


def lcd_context_options(width: int, height: int) -> dict:
    """Browser settings for the LCD page. Reduced motion stops CSS animations after one
    run, so an idle screen stops repainting (and stops costing frames) (PERF-2)."""
    return {"viewport": {"width": width, "height": height}, "device_scale_factor": 1, "reduced_motion": "reduce"}


# ---------------------------------------------------------------------------
# Frame capture. "screencast" (default): Chromium sends a frame only when the
# page repaints, so a static screen costs almost nothing and a change shows at
# once. Each frame is acknowledged one frame interval after the previous one,
# which keeps LCD_FPS as the upper limit. "poll": the previous behaviour, a
# screenshot every frame interval with a back-off to 1 FPS while unchanged.
# ---------------------------------------------------------------------------

LCD_CAPTURE = os.environ.get("ZETTNAS_LCD_CAPTURE", "screencast").strip().lower()
_NO_FRAME_FALLBACK_S = 5.0


class _Framebuffer:
    def __init__(self, fb_mem, total_bytes: int, stride: int, bpp: int):
        self.mem = fb_mem
        self.total = total_bytes
        self.stride = stride
        self.bpp = bpp

    def clear(self) -> None:
        self.mem[: self.total] = b"\x00" * self.total

    def write(self, raw_bytes: bytes) -> None:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            if self.bpp == 16:
                self.mem[: self.total] = img.convert("RGB").tobytes("raw", "BGR;16", self.stride, 1)
            else:
                raw_mode = "BGRA" if img.mode == "RGBA" else "BGRX"
                self.mem[: self.total] = img.tobytes("raw", raw_mode, self.stride, 1)
        try:
            self.mem.flush()
        except Exception:
            logger.debug("[LCD] framebuffer flush failed", exc_info=True)


class _LayoutPusher:
    """Hands a changed dashboard layout to the page (applyStats) when the UI wakes it or it changes."""

    def __init__(self, page):
        self.page = page
        self.version = 0

    def push(self, woke: bool) -> None:
        with Z_STATE.lock:
            layout = Z_STATE.cached_stats.get("layout") if Z_STATE.cached_stats else None
        ver = layout.get("version", 0) if isinstance(layout, dict) else 0
        if not (woke or (ver and ver != self.version)):
            return
        self.version = ver
        if not layout or not hasattr(self.page, "evaluate"):
            return
        try:
            self.page.evaluate(
                """(layout) => {
                    if (window.applyStats) {
                        window.applyStats({ layout });
                    } else if (window.fetchDashboardLayout) {
                        window.fetchDashboardLayout();
                    }
                }""",
                layout,
            )
        except Exception as e:
            logger.debug(f"[LCD] Page layout evaluate error: {e}")


def _screen_off(fb: "_Framebuffer", blanked: bool) -> bool:
    """Handles brightness 0 / power off / night blanking. Returns the new 'blanked' state."""
    if get_effective_brightness() <= 0:
        if not blanked:
            set_fb_blank(False)
            try:
                fb.clear()
            except Exception:
                logger.debug("[LCD] clearing the framebuffer failed", exc_info=True)
        return True
    if blanked:
        set_fb_blank(True)
    return False


def _poll_frames(page, cdp, fb: "_Framebuffer", shot_params: dict, frame_interval: float) -> None:
    """Screenshot every frame interval; back off to 1 FPS while nothing changes."""
    prev_raw_b64 = None
    idle_backoff = 0.0
    blanked = False
    layout = _LayoutPusher(page)
    while not Z_STATE.shutting_down:
        blanked = _screen_off(fb, blanked)
        if blanked:
            prev_raw_b64 = None
            if Z_STATE.ui_wake.wait(1.0):
                Z_STATE.ui_wake.clear()
            continue
        t0 = time.time()
        try:
            raw_b64 = cdp.send("Page.captureScreenshot", shot_params).get("data")
            if raw_b64 and raw_b64 == prev_raw_b64:
                idle_backoff = min(1.0, idle_backoff + 0.1)
                woke = Z_STATE.ui_wake.wait(max(frame_interval, idle_backoff))
                if woke:
                    Z_STATE.ui_wake.clear()
                    idle_backoff = 0.0
                layout.push(woke)
                continue
            idle_backoff = 0.0
            prev_raw_b64 = raw_b64
            raw_bytes = base64.b64decode(raw_b64)
        except Exception:
            raw_bytes = page.screenshot(type="png", animations="disabled")
        fb.write(raw_bytes)
        if Z_STATE.ui_wake.wait(max(0.01, frame_interval - (time.time() - t0))):
            Z_STATE.ui_wake.clear()


def _screencast_frames(page, cdp, fb: "_Framebuffer", fmt: str, frame_interval: float, width: int, height: int) -> bool:
    """
    Frames pushed by Chromium when the page repaints. Returns False if no frame ever
    arrived (the caller then polls instead), True when it stopped for shutdown.
    """
    pending: list[dict] = []
    params = {"format": fmt, "maxWidth": width, "maxHeight": height, "everyNthFrame": 1}
    if fmt == "jpeg":
        params["quality"] = 95

    def on_frame(event: dict) -> None:
        pending[:] = [event]  # keep only the newest frame

    cdp.on("Page.screencastFrame", on_frame)
    layout = _LayoutPusher(page)
    blanked = False
    casting = False
    started = time.time()
    got_frame = False
    last_write = 0.0
    try:
        while not Z_STATE.shutting_down:
            now_blanked = _screen_off(fb, blanked)
            if now_blanked != blanked or not casting:
                if now_blanked and casting:
                    cdp.send("Page.stopScreencast")
                    casting = False
                elif not now_blanked and not casting:
                    cdp.send("Page.startScreencast", params)
                    casting = True
                    started = time.time()
            blanked = now_blanked
            if blanked:
                if Z_STATE.ui_wake.wait(1.0):
                    Z_STATE.ui_wake.clear()
                continue
            # Lets Playwright deliver the frame events. One frame interval is enough: frames are
            # capped at that rate anyway, and a shorter wait only adds round trips while idle.
            page.wait_for_timeout(max(50, frame_interval * 1000))
            woke = Z_STATE.ui_wake.is_set()
            if woke:
                Z_STATE.ui_wake.clear()
            layout.push(woke)
            if not pending:
                if not got_frame and time.time() - started > _NO_FRAME_FALLBACK_S:
                    logger.info("[LCD] No screencast frames from Chromium; capturing by screenshots instead.")
                    return False
                continue
            event = pending.pop()
            got_frame = True
            fb.write(base64.b64decode(event["data"]))
            # Chromium sends the next frame only after this one is acknowledged: wait out the frame interval
            wait_ms = (frame_interval - (time.time() - last_write)) * 1000
            if wait_ms > 1:
                page.wait_for_timeout(wait_ms)
            last_write = time.time()
            cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
        return True
    finally:
        if casting:
            try:
                cdp.send("Page.stopScreencast")
            except Exception:
                logger.debug("[LCD] stopScreencast failed", exc_info=True)
