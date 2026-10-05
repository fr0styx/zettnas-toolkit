import base64
import io
import mmap
import os
import time

from PIL import Image
from playwright.sync_api import sync_playwright

from backend import config
from backend.config import ENABLE_FB, LCD_FORMAT, LCD_FPS, PORT, logger
from backend.state import Z_STATE


def render_lcd_loop():
    """
    Active Framebuffer Streamer to /dev/fb0:
    - Viewport oriented 172x640 via CSS 90deg rotation (No CPU matrix rotate overhead).
    - Captures at LCD_FPS with single-pass memory line assembly.
    - Single mmap memory block write into video memory per frame.
    """
    if not ENABLE_FB or not os.path.exists("/dev/fb0"):
        logger.info("[LCD] Framebuffer /dev/fb0 not present or disabled. Running web-only.")
        return

    time.sleep(2)
    url = f"http://127.0.0.1:{PORT}/?mode=lcd&lcd_token={config.LCD_INTERNAL_TOKEN}"

    backlight_path = "/sys/class/backlight/intel_backlight/brightness"
    if os.path.exists(backlight_path):
        try:
            with open(backlight_path, "w") as bl_f:
                bl_f.write("192000\n")
        except OSError:
            pass

    stride = 704
    fb_height = 640
    fb_width = 172
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

                    while True:
                        t0 = time.time()

                        try:
                            res = cdp.send("Page.captureScreenshot", shot_params)
                            raw_b64 = res.get("data")
                            if raw_b64 and raw_b64 == prev_raw_b64:
                                elapsed = time.time() - t0
                                sleep_time = max(0.01, frame_interval - elapsed)
                                time.sleep(sleep_time)
                                continue
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
                        time.sleep(sleep_time)

        except Exception as e:
            Z_STATE.lcd_renderer_active = False
            logger.info(f"[LCD] Active render loop error: {e}")
            time.sleep(2)
