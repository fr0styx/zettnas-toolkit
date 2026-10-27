"""Issue #38: the front LCD must never be drawn past the end of its framebuffer.

With the front panel (eDP, 172x640) and an HDMI monitor connected, the kernel makes one
1920x1080 framebuffer with 7680-byte rows; the panel shows its top-left 172x640. The old
code mapped 7680 x 1920 bytes of an 8,294,400-byte buffer and the app died with SIGBUS.
"""

from PIL import Image

from backend.services import lcd_renderer as lr

PANEL_ONLY = {"width": 172, "height": 640, "bpp": 32, "stride": 704, "buffer": 704 * 640}
PANEL_AND_HDMI = {"width": 172, "height": 640, "bpp": 32, "stride": 7680, "buffer": 8294400}


def layout_for(monkeypatch, info):
    monkeypatch.setattr(lr, "_fb_ioctl_info", lambda path: info)
    return lr.fb_layout("/dev/fb0")


def test_the_panel_alone_is_drawn_as_before(monkeypatch):
    lay = layout_for(monkeypatch, PANEL_ONLY)
    assert (lay.width, lay.height, lay.stride, lay.bpp) == (172, 640, 704, 32)
    assert lay.map_bytes == 704 * 640


def test_with_a_monitor_too_only_the_panels_rows_are_mapped(monkeypatch):
    lay = layout_for(monkeypatch, PANEL_AND_HDMI)
    assert (lay.width, lay.height, lay.stride) == (172, 640, 7680)
    assert lay.map_bytes == 7680 * 640 <= 8294400  # was 7680 x 1920 = 14,745,600


def test_a_layout_that_does_not_fit_turns_the_lcd_off_instead_of_crashing(monkeypatch):
    # what the old code computed for issue #38: portrait 1080x1920 with landscape rows
    assert (
        layout_for(monkeypatch, {"width": 1080, "height": 1920, "bpp": 32, "stride": 7680, "buffer": 8294400}) is None
    )
    # rows wider than the row length
    assert (
        layout_for(monkeypatch, {"width": 1920, "height": 640, "bpp": 32, "stride": 704, "buffer": 704 * 640}) is None
    )
    assert layout_for(monkeypatch, {"width": 0, "height": 0, "bpp": 32, "stride": 0, "buffer": 0}) is None


def _sysfs(tmp_path, **files):
    base = tmp_path / "class/graphics/fb0"
    base.mkdir(parents=True)
    for name, value in files.items():
        (base / name).write_text(value)


def test_without_the_ioctls_sysfs_gives_the_same_answer(monkeypatch, tmp_path):
    _sysfs(tmp_path, modes="U:172x640p-0\n", virtual_size="1920,1080", stride="7680", bits_per_pixel="32")
    monkeypatch.setattr(lr, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(lr, "_fb_ioctl_info", lambda path: None)
    lay = lr.fb_layout("/dev/fb0")
    assert (lay.width, lay.height, lay.stride, lay.buffer_bytes) == (172, 640, 7680, 7680 * 1080)


def test_sysfs_without_a_mode_never_maps_past_the_end(monkeypatch, tmp_path):
    _sysfs(tmp_path, virtual_size="1920,1080", stride="7680", bits_per_pixel="32")
    monkeypatch.setattr(lr, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(lr, "_fb_ioctl_info", lambda path: None)
    assert lr.fb_layout("/dev/fb0") is None


def test_a_panel_reported_on_its_side_still_works_from_sysfs(monkeypatch, tmp_path):
    _sysfs(tmp_path, virtual_size="640,172", stride="704", bits_per_pixel="32")
    monkeypatch.setattr(lr, "HOST_SYS", str(tmp_path))
    monkeypatch.setattr(lr, "_fb_ioctl_info", lambda path: None)
    lay = lr.fb_layout("/dev/fb0")
    assert (lay.width, lay.height, lay.stride) == (172, 640, 704)


def test_frames_land_on_the_panels_rows_inside_a_wider_buffer():
    # 4x3 visible inside 32-byte rows (a 8-pixel-wide buffer): every row starts a stride apart
    buf = bytearray(32 * 3)
    fb = lr._Framebuffer(memoryview(buf), 32 * 3, 32, 32)
    img = Image.new("RGB", (4, 3), (0, 0, 0))
    img.putpixel((0, 1), (255, 0, 0))
    fb.write_image(img)
    assert len(buf) == 96
    assert buf[32 : 32 + 3] == bytes([0, 0, 255])  # BGRX: the red pixel opens the second row


def test_the_ioctl_reader_handles_a_missing_device():
    assert lr._fb_ioctl_info("/nonexistent/fb0") is None


def test_the_ioctls_give_the_visible_size_row_length_and_buffer(monkeypatch, tmp_path):
    import struct

    dev = tmp_path / "fb0"
    dev.write_bytes(b"")
    var = struct.pack("@7I", 172, 640, 1920, 1080, 0, 0, 32).ljust(160, b"\0")
    fix = struct.pack("@16sLIIIIHHHI", b"i915drmfb", 0, 8294400, 0, 0, 2, 1, 1, 0, 7680).ljust(128, b"\0")
    answers = {lr.FBIOGET_VSCREENINFO: var, lr.FBIOGET_FSCREENINFO: fix}
    monkeypatch.setattr(lr.fcntl, "ioctl", lambda fd, req, buf: answers[req])
    assert lr._fb_ioctl_info(str(dev)) == {"width": 172, "height": 640, "bpp": 32, "stride": 7680, "buffer": 8294400}


def test_odd_sysfs_values_fall_back_safely(monkeypatch, tmp_path):
    _sysfs(tmp_path, modes="U:172x640p-0", virtual_size="172,640", stride="junk", bits_per_pixel="32")
    monkeypatch.setattr(lr, "HOST_SYS", str(tmp_path))
    assert lr._fb_sysfs_info()["stride"] == 0
    # an unknown depth is drawn as 32-bit, and a missing row length is the visible width
    lay = layout_for(monkeypatch, {"width": 172, "height": 640, "bpp": 8, "stride": 0, "buffer": 0})
    assert (lay.bpp, lay.stride) == (32, 688)


def _no_screen_side_effects(monkeypatch):
    import backend.hardware.screen as screen

    monkeypatch.setattr(screen, "is_auxiliary_lcd_present", lambda: True)
    monkeypatch.setattr(lr, "find_fb_device", lambda writable_only=True: "/dev/fb0")
    monkeypatch.setattr(lr, "get_effective_brightness", lambda: 50)
    monkeypatch.setattr(lr, "set_fb_blank", lambda on: None)
    monkeypatch.setattr(lr, "set_screen_brightness", lambda v: None)
    monkeypatch.setattr(lr.time, "sleep", lambda s: None)
    monkeypatch.setattr(lr, "fb_layout", lambda path: None)


def test_both_renderers_stay_off_when_the_layout_does_not_fit(monkeypatch):
    from backend.state import Z_STATE

    _no_screen_side_effects(monkeypatch)
    monkeypatch.setattr(Z_STATE, "shutting_down", False)
    monkeypatch.setattr(lr, "choose_renderer", lambda setting, present: "chromium")
    lr.render_lcd_loop()  # returns before starting a browser or mapping anything
    lr._run_pil("/dev/fb0")
    assert not Z_STATE.lcd_renderer_active
