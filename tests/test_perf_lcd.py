"""LCD idle cost: no busy waiting, no endless animations, cheaper frames (PERF-2)."""

import os
import subprocess
import sys
from unittest.mock import patch

from backend.services import lcd_renderer as lr
from tests.test_lcd_screencast import FakeCdp, FakePage, _fb, _run_for


class CountingPage(FakePage):
    def __init__(self, cdp):
        super().__init__(cdp)
        self.waits = 0

    def wait_for_timeout(self, ms):
        self.waits += 1
        super().wait_for_timeout(ms)


def test_an_idle_screen_does_not_busy_wait():
    cdp = FakeCdp(frames_per_start=1)
    page = CountingPage(cdp)
    with patch.object(lr, "get_effective_brightness", return_value=80), patch.object(lr, "set_fb_blank"):
        _run_for(2.0, lr._screencast_frames, page, cdp, _fb(), "jpeg", 0.2, 4, 2)
    assert page.waits <= 14  # about 5 a second at 5 FPS; it was 20 a second


def test_the_lcd_page_asks_for_reduced_motion():
    opts = lr.lcd_context_options(640, 172)
    assert opts["reduced_motion"] == "reduce"
    assert opts["viewport"] == {"width": 640, "height": 172}


def test_frames_are_jpeg_by_default():
    env = {k: v for k, v in os.environ.items() if k != "LCD_FORMAT"}
    out = (
        subprocess.run(
            [sys.executable, "-c", "from backend import config; print(config.LCD_FORMAT)"],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        .stdout.strip()
        .splitlines()[-1]
    )
    assert out == "jpeg"
