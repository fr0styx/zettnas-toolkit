"""The built-in LCD renderer (Pillow, no browser)."""

import threading
from datetime import datetime

import pytest
from PIL import Image

from backend.services import lcd_pil
from backend.services.lcd_renderer import _Framebuffer, choose_renderer, rgb565_bytes

STATS = {
    "name": "nas",
    "status": "3 OK",
    "storage": {"used": "4GB", "total": "31GB", "pct": 12},
    "cpu": {"temp": 47, "util": 23, "load_avg": [0.4, 0.3, 0.2]},
    "mem": {"used_gb": 11.4, "total_gb": 32, "pct": 36},
    "fans": [1180, 960],
    "net": {"rx_bytes_sec": 2_500_000, "tx_bytes_sec": 300, "interfaces": {"eth0": {}}},
    "uptime": "3d 4h",
    "disks": [
        {"name": "sda", "temp": None, "health": "standby", "standby": True},
        {"name": "nvme0", "temp": 41, "health": "ok"},
        {"name": "sdb", "temp": 55, "health": "failing", "risk": "high"},
    ],
    "unraid": {"available": False, "state": "STANDALONE", "disks": {"total": 0}},
    "copy_state": {"active": True, "status": "Copying DCIM", "progress": 40},
    "media_slots": {"sd": {"size": 64e9}, "tf": {"size": 0}},
    "layout": {"clock_format": "24"},
}


@pytest.mark.parametrize("page", range(4))
def test_every_page_is_640_by_172_and_rotates_to_portrait(page):
    img = lcd_pil.render_frame(STATS, page, now=datetime(2026, 1, 1, 9, 5))
    assert img.size == (640, 172) and img.mode == "RGB"
    assert lcd_pil.to_framebuffer(img).size == (172, 640)
    # something was drawn beyond the header
    body = img.crop((0, 40, 640, 172))
    assert len(set(body.get_flattened_data())) > 3


def test_rotation_is_clockwise():
    """The left edge of the landscape frame becomes the top of the portrait framebuffer."""
    img = Image.new("RGB", (640, 172), "black")
    img.putpixel((0, 0), (255, 0, 0))
    fb = lcd_pil.to_framebuffer(img)
    assert fb.getpixel((171, 0)) == (255, 0, 0)


def test_empty_or_odd_stats_still_draw():
    for stats in ({}, None, {"cpu": {"temp": "n/a"}, "disks": [None, 3], "fans": [{"rpm": None}]}):
        for page in range(4):
            assert lcd_pil.render_frame(stats, page).size == (640, 172)


def test_page_comes_from_stats_and_wraps():
    a = lcd_pil.render_frame({**STATS, "lcd": {"page": 1}}, now=datetime(2026, 1, 1))
    b = lcd_pil.render_frame(STATS, 5, now=datetime(2026, 1, 1))
    assert a.tobytes() == b.tobytes()


def test_theme_and_custom_accent():
    assert lcd_pil.palette({"lcd_theme": "amber"})["bg"] == "#120d04"
    assert lcd_pil.palette({"lcd_theme": "nope"})["bg"] == lcd_pil.THEMES["cyber"]["bg"]
    assert lcd_pil.palette({"lcd_custom_accent": "#123456"})["brand"] == "#123456"
    assert lcd_pil.palette({"lcd_custom_accent": "red;x"})["brand"] == lcd_pil.THEMES["cyber"]["brand"]
    light = lcd_pil.render_frame(STATS, 0, prefs={"lcd_theme": "light"})
    assert light.getpixel((320, 168)) == (248, 250, 252)


def test_twelve_hour_clock():
    assert lcd_pil._clock({"clock_format": "12"}, datetime(2026, 1, 1, 15, 7)) == "3:07 PM"
    assert lcd_pil._clock({}, datetime(2026, 1, 1, 15, 7)) == "15:07"


def test_long_text_is_shortened():
    img = Image.new("RGB", (10, 10))
    from PIL import ImageDraw

    d = ImageDraw.Draw(img)
    out = lcd_pil._fit(d, "x" * 300, lcd_pil.font("regular", 11), 60)
    assert out.endswith("…") and d.textlength(out, font=lcd_pil.font("regular", 11)) <= 60


def test_choose_renderer():
    assert choose_renderer("auto", True) == "chromium"
    assert choose_renderer("auto", False) == "pil"
    assert choose_renderer("pil", True) == "pil"
    assert choose_renderer("chromium", False) is None
    assert choose_renderer("", False) == "pil"


@pytest.mark.parametrize("bpp", [16, 32])
def test_framebuffer_write_image(bpp):
    stride = 172 * (2 if bpp == 16 else 4)
    mem = bytearray(640 * stride)
    fb = _Framebuffer(mem, len(mem), stride, bpp)
    fb.write_image(lcd_pil.to_framebuffer(lcd_pil.render_frame(STATS, 0)))
    assert any(mem)


class _State:
    def __init__(self, stats):
        self.shutting_down = False
        self.lcd_wake = threading.Event()
        self.ui_wake = threading.Event()
        self.lock = threading.RLock()
        self.cached_stats = stats
        self.current_lcd_page = 0


def test_run_loop_writes_only_changed_frames():
    state = _State(STATS)
    writes = []

    class FB:
        def write_image(self, img):
            writes.append(img.size)
            if len(writes) >= 1 and state.current_lcd_page == 0:
                state.current_lcd_page = 2  # next frame differs
            elif len(writes) >= 2:
                state.shutting_down = True

    lcd_pil.run_loop(FB(), 0.01, lambda fb, blanked: False, state)
    assert writes == [(172, 640), (172, 640)]


def test_run_loop_draws_nothing_while_the_screen_is_off():
    state = _State(STATS)
    calls = {"n": 0}

    def screen_off(fb, blanked):
        calls["n"] += 1
        if calls["n"] > 2:
            state.shutting_down = True
        state.ui_wake.set()
        return True

    class FB:
        def write_image(self, img):
            raise AssertionError("must not draw while blanked")

    lcd_pil.run_loop(FB(), 0.01, screen_off, state)


def test_preview_endpoint(client, auth_headers):
    r = client.get("/api/lcd/preview.png?page=1&theme=amber", headers=auth_headers)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    import io

    img = Image.open(io.BytesIO(r.content))
    assert img.size == (640, 172)
    assert client.get("/api/lcd/preview.png?page=9", headers=auth_headers).status_code == 422


def test_rgb565_packing_and_row_padding():
    img = Image.new("RGB", (2, 1))
    img.putpixel((0, 0), (255, 0, 0))
    img.putpixel((1, 0), (0, 0, 255))
    out = rgb565_bytes(img, stride=6)  # one padding pixel per row
    assert out == bytes([0x00, 0xF8, 0x1F, 0x00, 0x00, 0x00])
    green = rgb565_bytes(Image.new("RGB", (1, 1), (0, 255, 0)), stride=2)
    assert int.from_bytes(green, "little") == 0x07E0


def test_ui_wake_also_wakes_the_lcd_and_clearing_it_does_not_take_that_away():
    from backend.state import ZettState

    st = ZettState()
    st.lcd_wake.clear()
    st.ui_wake.set()
    st.ui_wake.clear()  # another loop (the stats collector) took the ui wake-up
    assert st.lcd_wake.is_set()


def test_page_change_wakes_the_lcd():
    from backend.state import ZettState

    st = ZettState()
    st.lcd_wake.clear()
    st.set_lcd_page(2)
    assert st.lcd_wake.is_set()


def test_seconds_to_next_minute():
    assert lcd_pil.seconds_to_next_minute(120.0) == pytest.approx(60.05)
    assert lcd_pil.seconds_to_next_minute(179.5) == pytest.approx(0.55)


def test_loop_sleeps_on_lcd_wake_until_the_minute_turns(monkeypatch):
    state = _State(STATS)
    waits = []

    class Wake:
        def wait(self, timeout):
            waits.append(timeout)
            state.shutting_down = True
            return False

        def clear(self):
            pass

    state.lcd_wake = Wake()
    monkeypatch.setattr(lcd_pil, "seconds_to_next_minute", lambda: 12.5)

    class FB:
        def write_image(self, img):
            pass

    lcd_pil.run_loop(FB(), 30.0, lambda fb, blanked: False, state)
    assert waits == [12.5]


def test_the_streamline_layout_is_drawn_when_chosen():
    """Choosing "Streamline Big IP" changes the LCD itself, not only the web preview."""
    from backend.services import lcd_pil

    stats = {
        "name": "nas",
        "ip": "192.168.1.20",
        "storage": {"pct": 63, "used": "15TB", "total": "23TB"},
        "cpu": {"util": 12, "temp": 51},
        "mem": {"pct": 31, "used_gb": 18.2},
        "net": {"rx_bytes_sec": 2048, "tx_bytes_sec": 1024},
        "disks": [{"name": "sda", "temp": 41}],
    }
    classic = lcd_pil.render_frame({**stats, "layout": {"style": "classic"}}, page=0).tobytes()
    streamline = lcd_pil.render_frame({**stats, "layout": {"style": "streamline"}}, page=0).tobytes()
    assert classic != streamline
    # other pages are the same in both styles
    assert lcd_pil.render_frame({**stats, "layout": {"style": "streamline"}}, page=1).tobytes() == (
        lcd_pil.render_frame({**stats, "layout": {"style": "classic"}}, page=1).tobytes()
    )
