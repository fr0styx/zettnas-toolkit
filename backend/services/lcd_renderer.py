import base64
import fcntl
import io
import mmap
import os
import re
import struct
import time
from dataclasses import dataclass

from PIL import Image, ImageChops

from backend import config
from backend.config import ENABLE_FB, HOST_SYS, LCD_FORMAT, LCD_FPS, PORT, logger
from backend.hardware.screen import (
    find_fb_device,
    get_effective_brightness,
    set_fb_blank,
    set_screen_brightness,
)
from backend.ignored_errors import ignored
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


FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602


@dataclass(frozen=True)
class FbLayout:
    """What the renderer draws into: the visible panel inside the framebuffer (issue #38).

    The kernel can size one framebuffer for every connected screen: with the front panel
    (eDP, 172x640) and an HDMI monitor (1920x1080) both connected, fb0 is a 1920x1080
    buffer with 7680-byte rows, of which the panel shows the top-left 172x640. The renderer
    draws the visible size at the real row length and maps only the rows it writes.
    """

    width: int  # visible pixels per row
    height: int  # visible rows
    stride: int  # bytes per row in the buffer
    bpp: int
    buffer_bytes: int  # the whole framebuffer, 0 when unknown

    @property
    def map_bytes(self) -> int:
        return self.stride * self.height


def _fb_ioctl_info(fb_path: str) -> dict | None:
    """Visible size, bits per pixel, row length and buffer size straight from the device."""
    try:
        with open(fb_path, "rb", buffering=0) as f:
            var = fcntl.ioctl(f.fileno(), FBIOGET_VSCREENINFO, bytes(160))
            fix = fcntl.ioctl(f.fileno(), FBIOGET_FSCREENINFO, bytes(128))
    except (OSError, ValueError):
        return None
    xres, yres, _xv, _yv, _xo, _yo, bpp = struct.unpack_from("@7I", var)
    _id, _start, smem_len, _type, _aux, _visual, _xp, _yp, _yw, line_length = struct.unpack_from("@16sLIIIIHHHI", fix)
    return {"width": xres, "height": yres, "bpp": bpp, "stride": line_length, "buffer": smem_len}


def _fb_sysfs_info() -> dict:
    """The same from sysfs, for when the ioctls are not available."""
    bases = ["/sys/class/graphics/fb0", "/host/sys/class/graphics/fb0"]
    if HOST_SYS and os.path.isdir(os.path.join(HOST_SYS, "class/graphics/fb0")):
        bases.insert(0, os.path.join(HOST_SYS, "class/graphics/fb0"))

    base = next((b for b in bases if os.path.isdir(b)), "")  # every value from the same device

    def read(name: str) -> str:
        try:
            with open(os.path.join(base, name)) as f:
                return f.read().strip()
        except OSError:
            return ""

    info: dict = {"bpp": discover_fb_bpp()}
    try:
        info["stride"] = int(read("stride") or 0)
    except ValueError:
        info["stride"] = 0
    vparts = [int(p) for p in re.findall(r"\d+", read("virtual_size"))][:2]
    m = re.search(r"(\d+)x(\d+)", read("modes").splitlines()[0] if read("modes") else "")
    if m:  # the mode the screen shows, e.g. "U:172x640p-0"
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    elif len(vparts) == 2:  # no mode: the whole buffer, portrait as before
        info["width"], info["height"] = min(vparts), max(vparts)
    if len(vparts) == 2 and info["stride"]:
        # rows in the buffer: the second number, unless the rows are the short side (a panel
        # reported as "640,172" with 704-byte rows holds 640 rows of 172 pixels)
        bytes_pp = 2 if info["bpp"] == 16 else 4
        rows = vparts[1] if info["stride"] >= vparts[0] * bytes_pp else max(vparts)
        info["buffer"] = info["stride"] * rows
    return info


def fb_layout(fb_path: str) -> FbLayout | None:
    """The framebuffer layout to draw into, or None when it does not add up.

    Never maps past the end of the buffer: a layout whose rows are wider than the row
    length, or whose rows do not fit in the buffer, is refused and the LCD stays off
    instead of crashing the app with SIGBUS (issue #38).
    """
    info = _fb_ioctl_info(fb_path) or _fb_sysfs_info()
    width, height = int(info.get("width") or 0), int(info.get("height") or 0)
    bpp = int(info.get("bpp") or 32)
    if bpp not in (16, 24, 32):
        bpp = 32
    stride = int(info.get("stride") or 0) or width * (bpp // 8)
    buffer_bytes = int(info.get("buffer") or 0)
    layout = FbLayout(width, height, stride, bpp, buffer_bytes)
    problem = ""
    if width <= 0 or height <= 0:
        problem = "no visible size"
    elif width * (2 if bpp == 16 else 4) > stride:
        problem = f"{width} pixels do not fit in {stride}-byte rows"
    elif buffer_bytes and layout.map_bytes > buffer_bytes:
        problem = f"{height} rows of {stride} bytes ({layout.map_bytes}) exceed the {buffer_bytes}-byte buffer"
    if problem:
        logger.warning(f"[LCD] Framebuffer {fb_path} layout does not add up ({problem}). Running web-only.")
        return None
    return layout


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
    renderer = choose_renderer(config.LCD_RENDERER, os.path.exists(chromium))
    if renderer is None:
        logger.info("[LCD] LCD_RENDERER=chromium but this image has no Chromium. Use LCD_RENDERER=pil or auto.")
        return

    fb_path = find_fb_device(writable_only=True)
    if not fb_path:
        logger.info(
            "[LCD] Framebuffer device (/dev/fb0, /host/dev/fb0) not present, inaccessible, or is a directory. Running web-only."
        )
        return

    if renderer == "pil":
        _run_pil(fb_path)
        return

    time.sleep(2)
    url = f"http://127.0.0.1:{PORT}/?mode=lcd"  # the token goes in a header and a cookie, never the URL (SEC-35)

    eff_bri = get_effective_brightness()
    set_fb_blank(eff_bri > 0)
    set_screen_brightness(eff_bri)

    layout = fb_layout(fb_path)
    if layout is None:
        return
    fb_width, fb_height, stride, bpp = layout.width, layout.height, layout.stride, layout.bpp
    total_fb_bytes = layout.map_bytes  # only the visible rows, never past the end of the buffer

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

    from playwright.sync_api import sync_playwright

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
                Z_STATE.lcd_renderer_name = "chromium"

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
                            ignored("backend.services.lcd_renderer.render_lcd_loop")

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


def choose_renderer(setting: str, chromium_present: bool) -> str | None:
    """ "chromium" or "pil" for the LCD_RENDERER setting; None when Chromium is asked for but missing."""
    setting = (setting or "auto").strip().lower()
    if setting == "pil":
        return "pil"
    if setting == "chromium":
        return "chromium" if chromium_present else None
    return "chromium" if chromium_present else "pil"


def _run_pil(fb_path: str) -> None:
    """Drives the LCD with the Pillow renderer (no browser) until shutdown."""
    from backend.services import lcd_pil

    eff_bri = get_effective_brightness()
    set_fb_blank(eff_bri > 0)
    set_screen_brightness(eff_bri)
    layout = fb_layout(fb_path)
    if layout is None:
        return
    fb_width, fb_height, stride, bpp = layout.width, layout.height, layout.stride, layout.bpp
    total_fb_bytes = layout.map_bytes
    logger.info(f"[LCD] Starting the built-in renderer (no browser): {fb_width}x{fb_height} ({bpp}bpp) -> {fb_path}")
    retry_delay = 2.0
    while not Z_STATE.shutting_down:
        try:
            with open(fb_path, "r+b") as fb_file:
                fb_mem = mmap.mmap(fb_file.fileno(), total_fb_bytes, mmap.MAP_SHARED, mmap.PROT_WRITE)
                try:
                    fb = _Framebuffer(fb_mem, total_fb_bytes, stride, bpp)
                    fb.clear()
                    Z_STATE.lcd_renderer_active = True
                    Z_STATE.lcd_renderer_name = "pil"
                    retry_delay = 2.0
                    lcd_pil.run_loop(fb, 30.0, _screen_off, Z_STATE)
                finally:
                    fb_mem.close()
        except Exception as e:
            Z_STATE.lcd_renderer_active = False
            if Z_STATE.shutting_down:
                break
            logger.info(f"[LCD] Built-in renderer error: {e}. Retrying in {retry_delay:.1f}s...")
            time.sleep(retry_delay)
            retry_delay = min(60.0, retry_delay * 1.5)
    Z_STATE.lcd_renderer_active = False
    Z_STATE.lcd_renderer_name = ""


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


# Lookup tables for rgb565_bytes: each channel's share of the low and high byte
_G_LOW = [(v & 0x1C) << 3 for v in range(256)]
_B_LOW = [v >> 3 for v in range(256)]
_R_HIGH = [v & 0xF8 for v in range(256)]
_G_HIGH = [v >> 5 for v in range(256)]


def rgb565_bytes(img: Image.Image, stride: int) -> bytes:
    """
    The image as little-endian RGB565 rows of `stride` bytes (16-bit framebuffers).
    Pillow can read RGB565 but not write it, so the two bytes per pixel are built
    from the colour channels: low = GGGBBBBB, high = RRRRRGGG.
    """
    img = img.convert("RGB")
    width = max(img.width, stride // 2)
    if width != img.width:
        padded = Image.new("RGB", (width, img.height))
        padded.paste(img, (0, 0))
        img = padded
    r, g, b = img.split()
    low = ImageChops.add(g.point(_G_LOW), b.point(_B_LOW))
    high = ImageChops.add(r.point(_R_HIGH), g.point(_G_HIGH))
    return Image.merge("LA", (low, high)).tobytes()


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
            self.write_image(img)

    def write_image(self, img: Image.Image) -> None:
        """Writes a framebuffer-sized image (already in the framebuffer's orientation)."""
        if self.bpp == 16:
            self.mem[: self.total] = rgb565_bytes(img, self.stride)[: self.total]
        else:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
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


# A lit screen whose page hasn't changed for this long is checked once a second, not at LCD_FPS:
# each check is a round trip through Playwright's driver (NPERF-2)
QUIET_AFTER_S = 2.0
QUIET_WAIT_MS = 1000


def _blanked_wait() -> float:
    from backend.services.lcd_pil import seconds_to_next_minute

    return min(30.0, seconds_to_next_minute())


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
            # a button, an alert or a setting wakes it; the night schedule turns on the minute (PERF-20)
            if Z_STATE.ui_wake.wait(_blanked_wait()):
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
    last_change = time.time()
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
                # dark: until the next minute (the night schedule), or a button or an alert (NPERF-2)
                if Z_STATE.ui_wake.wait(_blanked_wait()):
                    Z_STATE.ui_wake.clear()
                continue
            # Lets Playwright deliver the frame events: one frame interval while the page changes,
            # once a second once it has been still for QUIET_AFTER_S (NPERF-2)
            quiet = time.time() - last_change > QUIET_AFTER_S
            page.wait_for_timeout(QUIET_WAIT_MS if quiet else max(50, frame_interval * 1000))
            woke = Z_STATE.ui_wake.is_set()
            if woke:
                Z_STATE.ui_wake.clear()
                last_change = time.time()
            layout.push(woke)
            if not pending:
                if not got_frame and time.time() - started > _NO_FRAME_FALLBACK_S:
                    logger.info("[LCD] No screencast frames from Chromium; capturing by screenshots instead.")
                    return False
                continue
            event = pending.pop()
            got_frame = True
            last_change = time.time()
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
