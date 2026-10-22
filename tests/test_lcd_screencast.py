"""LCD renderer: frames pushed by Chromium when the page changes, capped at LCD_FPS, with a polling fallback."""

import base64
import io
import mmap
import threading
import time
from unittest.mock import patch

from PIL import Image

from backend.services import lcd_renderer as lr
from backend.state import Z_STATE


def _png(color):
    buf = io.BytesIO()
    Image.new("RGB", (4, 2), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeCdp:
    def __init__(self, frames_per_start=3, screenshot=None):
        self.sent = []
        self.handlers = {}
        self.queue = []
        self.frames_per_start = frames_per_start
        self.screenshot = screenshot
        self.waiting_for_ack = False  # like Chromium: no new frame until the last one is acknowledged

    def on(self, event, cb):
        self.handlers[event] = cb

    def send(self, method, params=None):
        self.sent.append((time.time(), method, params))
        if method == "Page.startScreencast":
            self.queue += [{"data": _png((i * 40, 0, 0)), "sessionId": i} for i in range(self.frames_per_start)]
        if method == "Page.screencastFrameAck":
            self.waiting_for_ack = False
        if method == "Page.captureScreenshot":
            return {"data": self.screenshot}
        return {}

    def deliver(self):
        if self.queue and not self.waiting_for_ack:
            self.waiting_for_ack = True
            self.handlers["Page.screencastFrame"](self.queue.pop(0))


class FakePage:
    def __init__(self, cdp):
        self.cdp = cdp

    def wait_for_timeout(self, ms):
        time.sleep(min(ms, 500) / 1000)
        self.cdp.deliver()

    def evaluate(self, *a):
        return None

    def screenshot(self, **k):
        return base64.b64decode(_png((1, 2, 3)))


def _fb():
    mem = mmap.mmap(-1, 2 * 16)
    fb = lr._Framebuffer(mem, 2 * 16, 16, 32)
    fb.writes = 0
    orig = fb.write

    def write(raw):
        fb.writes += 1
        orig(raw)

    fb.write = write
    return fb


def _run_for(seconds, fn, *args):
    Z_STATE.shutting_down = False
    timer = threading.Timer(seconds, lambda: setattr(Z_STATE, "shutting_down", True))
    timer.start()
    try:
        return fn(*args)
    finally:
        timer.cancel()
        Z_STATE.shutting_down = False


def test_screencast_writes_each_frame_and_caps_the_rate():
    cdp = FakeCdp(frames_per_start=4)
    fb = _fb()
    with patch.object(lr, "get_effective_brightness", return_value=80), patch.object(lr, "set_fb_blank"):
        assert _run_for(1.5, lr._screencast_frames, FakePage(cdp), cdp, fb, "png", 0.2, 4, 2) is True
    acks = [t for t, m, _p in cdp.sent if m == "Page.screencastFrameAck"]
    assert fb.writes == 4 and len(acks) == 4
    assert all(b - a >= 0.18 for a, b in zip(acks, acks[1:], strict=False))  # no faster than LCD_FPS (5 here)
    assert cdp.sent[0][1] == "Page.startScreencast" and cdp.sent[-1][1] == "Page.stopScreencast"


def test_falls_back_when_chromium_sends_nothing():
    cdp = FakeCdp(frames_per_start=0)
    with (
        patch.object(lr, "get_effective_brightness", return_value=80),
        patch.object(lr, "set_fb_blank"),
        patch.object(lr, "_NO_FRAME_FALLBACK_S", 0.3),
    ):
        assert _run_for(3, lr._screencast_frames, FakePage(cdp), cdp, _fb(), "png", 0.1, 4, 2) is False


def test_screen_off_stops_the_screencast():
    cdp = FakeCdp(frames_per_start=1)
    fb = _fb()
    levels = iter([80, 80, 80, 0, 0, 0] + [0] * 50)
    with (
        patch.object(lr, "get_effective_brightness", side_effect=lambda: next(levels)),
        patch.object(lr, "set_fb_blank") as blank,
    ):
        _run_for(1.2, lr._screencast_frames, FakePage(cdp), cdp, fb, "png", 0.05, 4, 2)
    methods = [m for _t, m, _p in cdp.sent]
    assert methods.index("Page.stopScreencast") > methods.index("Page.startScreencast")
    blank.assert_any_call(False)
    assert bytes(fb.mem[:32]) == b"\x00" * 32  # cleared while the screen is off


def test_polling_writes_only_changed_frames():
    cdp = FakeCdp(screenshot=_png((9, 9, 9)))
    fb = _fb()
    with patch.object(lr, "get_effective_brightness", return_value=80), patch.object(lr, "set_fb_blank"):
        _run_for(0.6, lr._poll_frames, FakePage(cdp), cdp, fb, {"format": "png"}, 0.05)
    assert fb.writes == 1
