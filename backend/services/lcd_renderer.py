import base64
import io
import mmap
import os
import time

from PIL import Image
from playwright.sync_api import sync_playwright

from backend import config
from backend.config import ENABLE_FB, LCD_FORMAT, LCD_FPS, PORT, logger
from backend.hardware.screen import discover_backlight_dir, get_effective_brightness
from backend.state import Z_STATE


def discover_fb_geometry() -> tuple[int, int, int]:
    """
    Returns (width, height, stride).
    Defaults to (172, 640, 704) matching the physical rotated LCD on Zettbox.
    """
    default_w = 172
    default_h = 640
    default_stride = 704

    for base in ["/sys/class/graphics/fb0", "/host/sys/class/graphics/fb0"]:
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


def render_lcd_loop():
    """
    Active Framebuffer Streamer to /dev/fb0:
    - Dynamic discovery of backlight sysfs and framebuffer stride/geometry.
    - Viewport oriented 172x640 via CSS 90deg rotation (No CPU matrix rotate overhead).
    - Screen-off pause: 0 FPS when screen blanked/night mode.
    - Adaptive FPS: 1 FPS when idle/static, bursting to target FPS on telemetry changes.
    - Single mmap memory block write into video memory per frame.
    """
    if not ENABLE_FB or not os.path.exists("/dev/fb0"):
        logger.info("[LCD] Framebuffer /dev/fb0 not present or disabled. Running web-only.")
        return

    time.sleep(2)
    url = f"http://127.0.0.1:{PORT}/?mode=lcd&lcd_token={config.LCD_INTERNAL_TOKEN}"

    bl_dir = discover_backlight_dir()
    if bl_dir:
        try:
            with open(os.path.join(bl_dir, "brightness"), "w") as bl_f:
                bl_f.write("192000\n")
        except OSError:
            pass

    fb_width, fb_height, stride = discover_fb_geometry()
    row_bytes = fb_width * 4
    total_fb_bytes = fb_height * stride

    target_fps = max(1, LCD_FPS)
    frame_interval = 1.0 / target_fps
    lcd_format = LCD_FORMAT

    logger.info(
        f"[LCD] Starting active renderer: {fb_width}x{fb_height} @ {target_fps} FPS -> /dev/fb0 (stride {stride}, format {lcd_format})"
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

    while True:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=chromium_args)
                context = browser.new_context(viewport={"width": fb_width, "height": fb_height}, device_scale_factor=1)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                Z_STATE.lcd_renderer_active = True

                cdp = context.new_cdp_session(page)
                shot_params = {"format": "jpeg" if lcd_format == "jpeg" else "png", "optimizeForSpeed": True}
                if lcd_format == "jpeg":
                    shot_params["quality"] = 95

                with open("/dev/fb0", "r+b") as fb_file:
                    fb_mem = mmap.mmap(fb_file.fileno(), total_fb_bytes, mmap.MAP_SHARED, mmap.PROT_WRITE)
                    # Pre-fill line padding once
                    fb_mem[:total_fb_bytes] = b"\x00" * total_fb_bytes
                    prev_raw_b64 = None
                    idle_backoff = 0.0
                    max_idle_backoff = 1.0

                    while not Z_STATE.shutting_down:
                        # Screen-off pause: 0 FPS when brightness is 0 or night mode is blanked
                        if get_effective_brightness() <= 0:
                            if Z_STATE.ui_wake.wait(1.0):
                                Z_STATE.ui_wake.clear()
                            continue

                        t0 = time.time()

                        try:
                            res = cdp.send("Page.captureScreenshot", shot_params)
                            raw_b64 = res.get("data")
                            if raw_b64 and raw_b64 == prev_raw_b64:
                                # Adaptive FPS: frame unchanged, incrementally back off up to 1.0s
                                idle_backoff = min(max_idle_backoff, idle_backoff + 0.1)
                                sleep_time = max(frame_interval, idle_backoff)
                                if Z_STATE.ui_wake.wait(sleep_time):
                                    Z_STATE.ui_wake.clear()
                                    idle_backoff = 0.0
                                continue

                            # Frame changed: reset idle backoff immediately
                            idle_backoff = 0.0
                            prev_raw_b64 = raw_b64
                            raw_bytes = base64.b64decode(raw_b64)
                        except Exception:
                            # Fallback if CDP session encounters an issue
                            raw_bytes = page.screenshot(type="png")

                        img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
                        raw_pixels = img.tobytes("raw", "BGRA")
                        mv = memoryview(raw_pixels)

                        src_pos = 0
                        dst_pos = 0
                        for _ in range(fb_height):
                            fb_mem[dst_pos : dst_pos + row_bytes] = mv[src_pos : src_pos + row_bytes]
                            src_pos += row_bytes
                            dst_pos += stride

                        elapsed = time.time() - t0
                        sleep_time = max(0.01, frame_interval - elapsed)
                        if Z_STATE.ui_wake.wait(sleep_time):
                            Z_STATE.ui_wake.clear()
                            idle_backoff = 0.0

        except Exception as e:
            Z_STATE.lcd_renderer_active = False
            logger.info(f"[LCD] Active render loop error: {e}")
            time.sleep(2)
