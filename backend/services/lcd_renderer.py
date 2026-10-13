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

    if not ENABLE_FB:
        logger.info("[LCD] Framebuffer disabled via ENABLE_FB=0. Running web-only.")
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
        "--headless=shell",
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
                context = browser.new_context(viewport={"width": fb_width, "height": fb_height}, device_scale_factor=1)
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

                with open(fb_path, "r+b") as fb_file:
                    fb_mem = mmap.mmap(fb_file.fileno(), total_fb_bytes, mmap.MAP_SHARED, mmap.PROT_WRITE)
                    try:
                        # Pre-fill line padding once
                        fb_mem[:total_fb_bytes] = b"\x00" * total_fb_bytes
                        prev_raw_b64 = None
                        idle_backoff = 0.0
                        max_idle_backoff = 1.0
                        screen_blanked = False

                        while not Z_STATE.shutting_down:
                            # Screen-off pause: 0 FPS when power is off, brightness is 0, or night mode is blanked
                            if get_effective_brightness() <= 0:
                                if not screen_blanked:
                                    set_fb_blank(False)
                                    try:
                                        fb_mem[:total_fb_bytes] = b"\x00" * total_fb_bytes
                                    except Exception:
                                        pass
                                    screen_blanked = True
                                    prev_raw_b64 = None
                                if Z_STATE.ui_wake.wait(1.0):
                                    Z_STATE.ui_wake.clear()
                                continue

                            if screen_blanked:
                                set_fb_blank(True)
                                screen_blanked = False

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
                                raw_bytes = page.screenshot(type="png", animations="disabled")

                            # Successfully rendered a frame, reset restart backoff
                            retry_delay = 2.0

                            with Image.open(io.BytesIO(raw_bytes)) as img:
                                if bpp == 16:
                                    rgb_img = img.convert("RGB")
                                    fb_mem[:total_fb_bytes] = rgb_img.tobytes("raw", "BGR;16", stride, 1)
                                else:
                                    raw_mode = "BGRA" if img.mode == "RGBA" else "BGRX"
                                    fb_mem[:total_fb_bytes] = img.tobytes("raw", raw_mode, stride, 1)
                                try:
                                    fb_mem.flush()
                                except Exception:
                                    pass

                            elapsed = time.time() - t0
                            sleep_time = max(0.01, frame_interval - elapsed)
                            if Z_STATE.ui_wake.wait(sleep_time):
                                Z_STATE.ui_wake.clear()
                                idle_backoff = 0.0
                    finally:
                        try:
                            fb_mem.close()
                        except Exception:
                            pass

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
