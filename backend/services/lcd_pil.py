"""
The front LCD drawn with Pillow, without a browser.

The Chromium renderer screenshots the web dashboard. This one draws the same four
pages (overview, drive bays, network, array) straight from the cached stats, so the
image needs no Chromium (about 600 MiB) and a frame costs a few milliseconds.

The screen is 640×172 landscape; the framebuffer is mounted portrait, so frames are
rotated a quarter turn clockwise before they are written (the web page does the
same with a CSS rotate).
"""

from __future__ import annotations

import io
import math
import os
import re
import threading
import time
from datetime import datetime
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 640, 172
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
PAGE_NAMES = ("Overview", "Drive bays", "Network", "Array")

# Same palettes as the web LCD themes (frontend/src/styles/02-lcd-themes.css, 03-performance-a11y.css).
THEMES: dict[str, dict[str, str]] = {
    "cyber": {
        "bg": "#0b1118",
        "card": "#131b24",
        "card_hi": "#1c2734",
        "fg": "#eaf1f8",
        "muted": "#94a3b8",
        "ok": "#00f0ff",
        "ok2": "#25c2a0",
        "warn": "#ffb830",
        "crit": "#ff4757",
        "track": "#1e293b",
        "brand": "#00f0ff",
    },
    "amber": {
        "bg": "#120d04",
        "card": "#1f1708",
        "card_hi": "#2b200b",
        "fg": "#fef3c7",
        "muted": "#a67c29",
        "ok": "#ffbe40",
        "ok2": "#e09b20",
        "warn": "#ff8c00",
        "crit": "#e63946",
        "track": "#2a1f0a",
        "brand": "#ffbe40",
    },
    "emerald": {
        "bg": "#04120a",
        "card": "#082012",
        "card_hi": "#0c2e1a",
        "fg": "#e6fced",
        "muted": "#38b56f",
        "ok": "#3bf58b",
        "ok2": "#24d673",
        "warn": "#eab308",
        "crit": "#ef4444",
        "track": "#0e331f",
        "brand": "#3bf58b",
    },
    "sapphire": {
        "bg": "#070e17",
        "card": "#0c1929",
        "card_hi": "#132438",
        "fg": "#f0f7ff",
        "muted": "#6482a6",
        "ok": "#38bdf8",
        "ok2": "#0ea5e9",
        "warn": "#f59e0b",
        "crit": "#ef4444",
        "track": "#15263d",
        "brand": "#38bdf8",
    },
    "amethyst": {
        "bg": "#0e0717",
        "card": "#180e28",
        "card_hi": "#24153b",
        "fg": "#fbf7ff",
        "muted": "#b399cf",
        "ok": "#c084fc",
        "ok2": "#a855f7",
        "warn": "#fb923c",
        "crit": "#f43f5e",
        "track": "#26163d",
        "brand": "#c084fc",
    },
    "crimson": {
        "bg": "#14070a",
        "card": "#220c12",
        "card_hi": "#30131b",
        "fg": "#fff1f2",
        "muted": "#c48995",
        "ok": "#fb7185",
        "ok2": "#f43f5e",
        "warn": "#f59e0b",
        "crit": "#ef4444",
        "track": "#36141e",
        "brand": "#f43f5e",
    },
    "light": {
        "bg": "#f8fafc",
        "card": "#cbd5e1",
        "card_hi": "#dce4ed",
        "fg": "#0a0f1d",
        "muted": "#475569",
        "ok": "#0284c7",
        "ok2": "#059669",
        "warn": "#d97706",
        "crit": "#dc2626",
        "track": "#94a3b8",
        "brand": "#0284c7",
    },
    "yak": {
        "bg": "#09130d",
        "card": "#122116",
        "card_hi": "#192e20",
        "fg": "#eaf1f8",
        "muted": "#7b9483",
        "ok": "#e6a254",
        "ok2": "#d48a37",
        "warn": "#e07a38",
        "crit": "#e63946",
        "track": "#17291c",
        "brand": "#d48a37",
    },
}

_FONT_DIRS = (
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/liberation2",
    "/usr/share/fonts/liberation",
)
_FONT_FILES = {
    "regular": "LiberationSans-Regular.ttf",
    "bold": "LiberationSans-Bold.ttf",
    "mono": "LiberationMono-Regular.ttf",
    "mono_bold": "LiberationMono-Bold.ttf",
}


@lru_cache(maxsize=64)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A Liberation font, or Pillow's built-in font when Liberation is not installed."""
    name = _FONT_FILES.get(kind, _FONT_FILES["regular"])
    for d in _FONT_DIRS:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def palette(prefs: dict | None) -> dict[str, str]:
    """The theme the user picked for the LCD (Appearance), with their accent colour if set."""
    prefs = prefs or {}
    colors = dict(THEMES.get(str(prefs.get("lcd_theme") or "cyber"), THEMES["cyber"]))
    accent = str(prefs.get("lcd_custom_accent") or "").strip()
    if _HEX_COLOR.fullmatch(accent):
        colors.update(brand=accent, ok2=accent)
    return colors


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------


def _w(draw: ImageDraw.ImageDraw, text: str, f) -> float:
    return draw.textlength(text, font=f)


def _fit(draw: ImageDraw.ImageDraw, text: str, f, max_w: float) -> str:
    """Shortens text with an ellipsis so it fits max_w pixels."""
    text = str(text)
    if _w(draw, text, f) <= max_w:
        return text
    while text and _w(draw, text + "…", f) > max_w:
        text = text[:-1]
    return text + "…" if text else ""


def _text(draw, xy, text, f, fill, max_w=None, anchor="la"):
    if max_w is not None:
        text = _fit(draw, text, f, max_w)
    draw.text(xy, text, font=f, fill=fill, anchor=anchor)


def _card(draw, box, c, outline=None):
    draw.rounded_rectangle(box, radius=6, fill=c["card"], outline=outline or c["card_hi"], width=1)


def _badge(draw, right_x, y, text, color, c, f=None):
    """A small outlined label ending at right_x. Returns its left edge."""
    f = f or font("mono_bold", 10)
    w = _w(draw, text, f) + 12
    draw.rounded_rectangle((right_x - w, y, right_x, y + 15), radius=3, fill=c["bg"], outline=color)
    draw.text((right_x - w / 2, y + 8), text, font=f, fill=color, anchor="mm")
    return right_x - w


def _bar(draw, box, pct, color, c):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=2, fill=c["track"])
    pct = max(0.0, min(100.0, float(pct or 0)))
    if pct > 0:
        draw.rounded_rectangle((x0, y0, x0 + max(3, (x1 - x0) * pct / 100), y1), radius=2, fill=color)


def _ring(draw, center, radius, pct, color, c, width=7):
    cx, cy = center
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.arc(box, 0, 360, fill=c["track"], width=width)
    pct = max(0.0, min(100.0, float(pct or 0)))
    if pct > 0:
        draw.arc(box, -90, -90 + 360 * pct / 100, fill=color, width=width)


def _level_color(pct: float, c: dict, warn=80, crit=92) -> str:
    if pct >= crit:
        return c["crit"]
    if pct >= warn:
        return c["warn"]
    return c["ok"]


def _num(value, default=0.0) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _rate(bytes_per_s: float) -> str:
    b = max(0.0, bytes_per_s)
    if b >= 1024**3:
        return f"{b / 1024**3:.1f} GB/s"
    if b >= 1024**2:
        return f"{b / 1024**2:.1f} MB/s"
    if b >= 1024:
        return f"{b / 1024:.0f} KB/s"
    return f"{b:.0f} B/s"


def _status_color(status: str, c: dict) -> str:
    s = (status or "").upper()
    if "ALERT" in s or "CRIT" in s or "FAIL" in s:
        return c["crit"]
    if "WARN" in s:
        return c["warn"]
    return c["ok2"]


def _clock(layout: dict | None, now: datetime | None) -> str:
    layout = layout or {}
    if now is None:
        tz = None
        tz_name = layout.get("timezone")
        if tz_name:
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(str(tz_name))
            except Exception:
                tz = None
        now = datetime.now(tz)
    if str(layout.get("clock_format", "24")) == "12":
        return now.strftime("%I:%M %p").lstrip("0")
    return now.strftime("%H:%M")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def _header(draw, stats, page, c, now):
    name = str(stats.get("name") or "ZettNAS")
    f_name = font("bold", 21)
    _text(draw, (12, 17), name, f_name, c["fg"], max_w=180, anchor="lm")
    x = 12 + min(180, _w(draw, name, f_name)) + 10
    status = str(stats.get("status") or "OK")
    sc = _status_color(status, c)
    f_st = font("bold", 11)
    sw = _w(draw, status, f_st) + 28
    draw.rounded_rectangle((x, 7, x + sw, 27), radius=10, fill=c["card"], outline=sc)
    draw.ellipse((x + 8, 13, x + 16, 21), fill=sc)
    draw.text((x + 20, 17), status, font=f_st, fill=sc, anchor="lm")

    draw.text((WIDTH / 2, 17), _clock(stats.get("layout"), now), font=font("bold", 24), fill=c["fg"], anchor="mm")

    f_dot = font("bold", 9)
    for i in range(len(PAGE_NAMES)):
        x0 = WIDTH - 12 - (len(PAGE_NAMES) - i) * 18
        on = i == page
        draw.rounded_rectangle(
            (x0, 10, x0 + 14, 24),
            radius=3,
            fill=c["brand"] if on else c["card"],
            outline=c["brand"] if on else c["card_hi"],
        )
        draw.text((x0 + 7, 17), str(i + 1), font=f_dot, fill=c["bg"] if on else c["muted"], anchor="mm")


def _section_title(draw, title, badge, badge_color, c, y=48):
    draw.rectangle((12, y - 5, 15, y + 5), fill=c["brand"])
    _text(draw, (22, y), title.upper(), font("bold", 11), c["fg"], max_w=420, anchor="lm")
    if badge:
        _badge(draw, WIDTH - 12, y - 8, badge.upper(), badge_color, c)
    draw.line((12, y + 12, WIDTH - 12, y + 12), fill=c["card_hi"])


def _page_overview(draw, stats, c):
    top, bottom = 40, 120
    gap = 6
    cw = (WIDTH - 24 - gap * 4) / 5
    f_title = font("bold", 10)
    f_big = font("bold", 15)
    f_small = font("regular", 10)

    def card(i, title):
        x0 = 12 + i * (cw + gap)
        _card(draw, (x0, top, x0 + cw, bottom), c)
        _text(draw, (x0 + 8, top + 11), title, f_title, c["fg"], max_w=cw - 16, anchor="lm")
        return x0

    storage = stats.get("storage") or {}
    pct = _num(storage.get("pct"))
    x0 = card(0, "STORAGE")
    _ring(draw, (x0 + 28, top + 50), 19, pct, _level_color(pct, c), c, width=6)
    draw.text((x0 + 28, top + 50), f"{pct:.0f}%", font=font("bold", 11), fill=c["fg"], anchor="mm")
    _text(draw, (x0 + cw - 8, top + 42), str(storage.get("used", "")), f_big, c["fg"], max_w=cw - 60, anchor="rm")
    _text(
        draw,
        (x0 + cw - 8, top + 60),
        "of " + str(storage.get("total", "")),
        f_small,
        c["muted"],
        max_w=cw - 60,
        anchor="rm",
    )

    cpu = stats.get("cpu") or {}
    util = _num(cpu.get("util"))
    temp = cpu.get("temp")
    x0 = card(1, "CPU")
    _ring(draw, (x0 + 28, top + 50), 19, util, _level_color(util, c), c, width=6)
    draw.text((x0 + 28, top + 50), f"{util:.0f}%", font=font("bold", 11), fill=c["fg"], anchor="mm")
    temp_txt = f"{_num(temp):.0f}°C" if temp is not None else "--°C"
    temp_color = _level_color(_num(temp), c, warn=75, crit=90) if temp is not None else c["muted"]
    _text(draw, (x0 + cw - 8, top + 42), temp_txt, f_big, temp_color, anchor="rm")
    load = cpu.get("load_avg") or []
    if load:
        _text(draw, (x0 + cw - 8, top + 60), f"load {_num(load[0]):.2f}", f_small, c["muted"], anchor="rm")

    mem = stats.get("mem") or {}
    mpct = _num(mem.get("pct"))
    x0 = card(2, "MEMORY")
    _ring(draw, (x0 + 28, top + 50), 19, mpct, _level_color(mpct, c), c, width=6)
    draw.text((x0 + 28, top + 50), f"{mpct:.0f}%", font=font("bold", 11), fill=c["fg"], anchor="mm")
    _text(draw, (x0 + cw - 8, top + 42), f"{_num(mem.get('used_gb')):.1f}G", f_big, c["fg"], anchor="rm")
    _text(draw, (x0 + cw - 8, top + 60), f"of {_num(mem.get('total_gb')):.0f}G", f_small, c["muted"], anchor="rm")

    # Fans arrive as RPM numbers (older payloads: {"label", "rpm"} objects)
    fans = []
    for j, fan in enumerate(stats.get("fans") or []):
        if isinstance(fan, dict):
            fans.append((str(fan.get("label") or fan.get("name") or f"Fan {j + 1}"), fan.get("rpm")))
        else:
            fans.append((f"Fan {j + 1}", fan))
    x0 = card(3, "FANS")
    uptime = stats.get("uptime")
    show_uptime = bool(uptime) and uptime != "?"
    if not fans:
        _text(draw, (x0 + 8, top + 46), "n/a", f_big, c["muted"], anchor="lm")
    for j, (label, rpm) in enumerate(fans[: 2 if show_uptime else 3]):
        y = top + 30 + j * 15
        _text(draw, (x0 + 8, y), label, f_small, c["muted"], max_w=cw - 60, anchor="lm")
        rpm_txt = f"{_num(rpm):.0f} rpm" if rpm is not None else "--"
        _text(draw, (x0 + cw - 8, y), rpm_txt, f_small, c["fg"], anchor="rm")
    if show_uptime:
        _text(draw, (x0 + 8, bottom - 9), f"up {uptime}", f_small, c["muted"], max_w=cw - 16, anchor="lm")

    net = stats.get("net") or {}
    x0 = card(4, "NETWORK I/O")
    for j, (label, key) in enumerate((("RX", "rx_bytes_sec"), ("TX", "tx_bytes_sec"))):
        y = top + 40 + j * 22
        _text(draw, (x0 + 8, y), label, font("bold", 10), c["muted"], anchor="lm")
        _text(draw, (x0 + cw - 8, y), _rate(_num(net.get(key))), f_big, c["ok2"], max_w=cw - 34, anchor="rm")

    _drive_strip(draw, stats.get("disks") or [], c, top=bottom + 6)


def _page_streamline(draw, stats, c):
    """The "Streamline Big IP" overview: storage, compute and the address in large type, then the
    drive strip. Same data as the web layout (sl-* elements in index.html)."""
    top, bottom, gap = 40, 120, 6
    widths = (150, 170)
    x_storage = 12
    x_compute = x_storage + widths[0] + gap
    x_ip = x_compute + widths[1] + gap
    f_title = font("bold", 10)
    f_small = font("regular", 10)

    storage = stats.get("storage") or {}
    pct = _num(storage.get("pct"))
    _card(draw, (x_storage, top, x_storage + widths[0], bottom), c)
    _text(draw, (x_storage + 8, top + 11), "STORAGE", f_title, c["fg"], anchor="lm")
    _ring(draw, (x_storage + 32, top + 50), 21, pct, _level_color(pct, c), c, width=7)
    draw.text((x_storage + 32, top + 50), f"{pct:.0f}%", font=font("bold", 12), fill=c["fg"], anchor="mm")
    _text(
        draw,
        (x_storage + widths[0] - 8, top + 40),
        str(storage.get("used", "")),
        font("bold", 15),
        c["fg"],
        max_w=widths[0] - 66,
        anchor="rm",
    )
    _text(
        draw,
        (x_storage + widths[0] - 8, top + 60),
        "/ " + str(storage.get("total", "")),
        f_small,
        c["muted"],
        max_w=widths[0] - 66,
        anchor="rm",
    )

    cpu = stats.get("cpu") or {}
    mem = stats.get("mem") or {}
    _card(draw, (x_compute, top, x_compute + widths[1], bottom), c)
    _text(draw, (x_compute + 8, top + 11), "COMPUTE", f_title, c["fg"], anchor="lm")
    rows = (
        ("CPU", _num(cpu.get("util")), f"{_num(cpu.get('temp')):.0f}°C" if cpu.get("temp") is not None else "--°C"),
        (
            "MEMORY",
            _num(mem.get("pct")),
            f"{_num(mem.get('used_gb')):.1f}G" if mem.get("used_gb") is not None else "--",
        ),
    )
    for j, (label, value, sub_txt) in enumerate(rows):
        y = top + 30 + j * 26
        _text(draw, (x_compute + 8, y), label, f_small, c["muted"], anchor="lm")
        _text(draw, (x_compute + widths[1] - 8, y), f"{value:.0f}%  {sub_txt}", font("bold", 10), c["fg"], anchor="rm")
        _bar(draw, (x_compute + 8, y + 8, x_compute + widths[1] - 8, y + 13), value, _level_color(value, c), c)

    net = stats.get("net") or {}
    _card(draw, (x_ip, top, WIDTH - 12, bottom), c, outline=c["brand"])
    _text(draw, (x_ip + 8, top + 11), "IP ADDRESS", f_title, c["fg"], anchor="lm")
    ip_w = WIDTH - 12 - x_ip - 16
    ip = str(stats.get("ip") or "0.0.0.0")
    size = 30
    while size > 14 and _w(draw, ip, font("bold", size)) > ip_w:
        size -= 2
    draw.text((x_ip + (WIDTH - 12 - x_ip) / 2, top + 44), ip, font=font("bold", size), fill=c["brand"], anchor="mm")
    rates = f"TX: {_rate(_num(net.get('tx_bytes_sec')))}   RX: {_rate(_num(net.get('rx_bytes_sec')))}"
    _text(draw, (x_ip + (WIDTH - 12 - x_ip) / 2, top + 68), rates, f_small, c["muted"], max_w=ip_w, anchor="mm")

    _drive_strip(draw, stats.get("disks") or [], c, top=bottom + 6)


def _disk_state(disk: dict, c: dict) -> tuple[str, str]:
    health = str(disk.get("health") or "").lower()
    if health in ("failing", "failed", "critical", "bad") or disk.get("risk") == "high":
        return "FAIL", c["crit"]
    if health in ("warning", "warn") or disk.get("risk") == "medium":
        return "WARN", c["warn"]
    if disk.get("standby") or health == "standby":
        return "STBY", c["muted"]
    return "OK", c["ok2"]


def _disk_temp(disk: dict) -> str:
    t = disk.get("temp")
    return f"{_num(t):.0f}°C" if t is not None else "--°C"


def _drive_strip(draw, disks, c, top):
    disks = [d for d in disks if isinstance(d, dict)][:6]
    if not disks:
        _text(draw, (12, top + 18), "No drives found", font("regular", 11), c["muted"], anchor="lm")
        return
    gap = 6
    w = (WIDTH - 24 - gap * (len(disks) - 1)) / len(disks)
    for i, d in enumerate(disks):
        x0 = 12 + i * (w + gap)
        label, color = _disk_state(d, c)
        _card(draw, (x0, top, x0 + w, HEIGHT - 6), c)
        draw.rectangle((x0, top + 4, x0 + 3, HEIGHT - 10), fill=color)
        _text(
            draw,
            (x0 + 10, top + 13),
            str(d.get("name") or d.get("dev") or "?"),
            font("bold", 12),
            c["fg"],
            max_w=w - 60,
            anchor="lm",
        )
        _text(draw, (x0 + w - 8, top + 13), _disk_temp(d), font("regular", 11), c["fg"], anchor="rm")
        _text(draw, (x0 + 10, top + 30), label, font("bold", 9), color, anchor="lm")


def _page_bays(draw, stats, c):
    disks = [d for d in (stats.get("disks") or []) if isinstance(d, dict)]
    bad = [d for d in disks if _disk_state(d, c)[0] in ("FAIL", "WARN")]
    if bad:
        _section_title(draw, "Drive bays & SMART", f"{len(bad)} need attention", c["warn"], c)
    else:
        _section_title(draw, "Drive bays & SMART", "All drives healthy", c["ok2"], c)
    slots = max(6, min(8, len(disks)))
    gap = 6
    w = (WIDTH - 24 - gap * (slots - 1)) / slots
    top = 68
    for i in range(slots):
        x0 = 12 + i * (w + gap)
        disk = disks[i] if i < len(disks) else None
        _card(draw, (x0, top, x0 + w, HEIGHT - 6), c)
        _text(
            draw,
            (x0 + w / 2, top + 12),
            f"BAY {i + 1}",
            font("bold", 10),
            c["muted"] if disk else c["track"],
            anchor="mm",
        )
        cx, cy = x0 + w / 2, top + 38
        ring = c["fg"] if disk else c["track"]
        draw.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), outline=ring, width=2)
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=ring)
        if not disk:
            _text(draw, (cx, top + 64), "EMPTY", font("bold", 10), c["track"], anchor="mm")
            continue
        label, color = _disk_state(disk, c)
        _text(
            draw,
            (cx, top + 62),
            str(disk.get("name") or disk.get("dev") or "?"),
            font("bold", 11),
            c["fg"],
            max_w=w - 10,
            anchor="mm",
        )
        _text(draw, (cx - 4, top + 83), _disk_temp(disk), font("regular", 10), c["fg"], anchor="rm")
        _text(draw, (cx + 2, top + 83), label, font("bold", 9), color, anchor="lm")


class _Peaks:
    """Highest network rate seen since start, for the network page."""

    def __init__(self):
        self.lock = threading.Lock()
        self.rx = 0.0
        self.tx = 0.0

    def update(self, rx: float, tx: float) -> tuple[float, float]:
        with self.lock:
            self.rx = max(self.rx, rx)
            self.tx = max(self.tx, tx)
            return self.rx, self.tx


PEAKS = _Peaks()
_LINK_BYTES = 10e9 / 8  # bars are scaled to a 10 GbE link


def _page_network(draw, stats, c):
    net = stats.get("net") or {}
    rx, tx = _num(net.get("rx_bytes_sec")), _num(net.get("tx_bytes_sec"))
    peak_rx, peak_tx = PEAKS.update(rx, tx)
    ifaces = net.get("interfaces") or {}
    badge = f"{len(ifaces)} interface{'s' if len(ifaces) != 1 else ''}" if ifaces else "Interface live"
    _section_title(draw, "Network & storage I/O", badge, c["ok2"], c)
    rows = (("INBOUND (RX)", rx, peak_rx, c["ok2"]), ("OUTBOUND (TX)", tx, peak_tx, c["ok"]))
    for j, (label, rate, peak, color) in enumerate(rows):
        y0 = 68 + j * 51
        _card(draw, (12, y0, WIDTH - 12, y0 + 45), c)
        _text(draw, (24, y0 + 14), label, font("bold", 11), color, anchor="lm")
        _text(draw, (WIDTH - 24, y0 + 14), _rate(rate), font("mono_bold", 17), c["fg"], anchor="rm")
        # Square-root scale so everyday rates are visible next to a 10 GbE ceiling
        _bar(draw, (24, y0 + 26, WIDTH - 24, y0 + 30), 100 * math.sqrt(min(1.0, rate / _LINK_BYTES)), color, c)
        _text(draw, (24, y0 + 38), f"Peak: {_rate(peak)}", font("mono", 9), c["muted"], anchor="lm")
        _text(draw, (WIDTH - 24, y0 + 38), "Scale: 10 GbE", font("mono", 9), c["muted"], anchor="rm")


def _page_array(draw, stats, c):
    unraid = stats.get("unraid") or {}
    available = bool(unraid.get("available"))
    state = str(unraid.get("state") or ("STANDALONE" if not available else "UNKNOWN"))
    healthy = unraid.get("is_healthy", True)
    _section_title(draw, "Array & media ingest", "Unraid" if available else "Standalone", c["ok2"], c)

    y0 = 68
    _card(draw, (12, y0, WIDTH - 12, y0 + 45), c)
    _text(draw, (24, y0 + 11), "ARRAY STATUS", font("bold", 11), c["fg"], anchor="lm")
    _badge(draw, WIDTH - 24, y0 + 4, state.upper(), c["ok2"] if healthy else c["crit"], c)
    dk = unraid.get("disks") or {}
    _text(
        draw,
        (24, y0 + 25),
        f"Disks: {dk.get('total', 0)} assigned • {dk.get('disabled', 0)} disabled • {dk.get('missing', 0)} missing",
        font("regular", 10),
        c["muted"],
        max_w=WIDTH - 48,
        anchor="lm",
    )
    pc = unraid.get("parity_check") or {}
    mover = unraid.get("mover") or {}
    if pc.get("active"):
        label = f"Parity check {_num(pc.get('progress_pct')):.0f}%" + (" (paused)" if pc.get("paused") else "")
        pct = _num(pc.get("progress_pct"))
    elif mover.get("active"):
        total = _num(mover.get("total_files"))
        done = total - _num(mover.get("remain_files"))
        label, pct = "Mover running", (100 * done / total if total else 0)
    else:
        label, pct = "Parity check idle", 0
    _text(draw, (24, y0 + 36), label, font("regular", 9), c["fg"], anchor="lm")
    _bar(draw, (200, y0 + 34, WIDTH - 24, y0 + 38), pct, c["ok"], c)

    y1 = y0 + 51
    _card(draw, (12, y1, WIDTH - 12, HEIGHT - 6), c)
    copy = stats.get("copy_state") or {}
    active = bool(copy.get("active"))
    _text(draw, (24, y1 + 11), "MEDIA INGEST", font("bold", 11), c["fg"], anchor="lm")
    _badge(draw, WIDTH - 24, y1 + 4, "COPYING" if active else "IDLE", c["ok"] if active else c["ok2"], c)
    slots = stats.get("media_slots") or {}

    def slot(name):
        s = slots.get(name) or {}
        size = _num(s.get("size"))
        return f"{name.upper()}: {f'{size / 1e9:.0f} GB' if size else 'empty'}"

    detail = str(copy.get("status") or "") if active else f"{slot('sd')} • {slot('tf')}"
    _text(draw, (24, y1 + 26), detail, font("regular", 10), c["muted"], max_w=WIDTH - 48, anchor="lm")
    if active:
        _bar(draw, (24, y1 + 36, WIDTH - 24, y1 + 40), _num(copy.get("progress")), c["ok"], c)


_PAGES = (_page_overview, _page_bays, _page_network, _page_array)


def render_frame(
    stats: dict | None, page: int | None = None, now: datetime | None = None, prefs: dict | None = None
) -> Image.Image:
    """One 640×172 landscape LCD frame (RGB) for the given stats and page."""
    stats = stats or {}
    if page is None:
        page = (stats.get("lcd") or {}).get("page", 0)
    page = int(_num(page)) % len(_PAGES)
    c = palette(prefs if prefs is not None else stats.get("client_preferences"))
    img = Image.new("RGB", (WIDTH, HEIGHT), c["bg"])
    draw = ImageDraw.Draw(img)
    _header(draw, stats, page, c, now)
    draw_page = _PAGES[page]
    if page == 0 and str((stats.get("layout") or {}).get("style") or "classic") == "streamline":
        draw_page = _page_streamline  # the layout chosen in Settings > Screen Dashboard Style
    try:
        draw_page(draw, stats, c)
    except Exception as exc:  # a bad value must not blank the screen
        _text(draw, (12, 90), f"Display error: {exc}", font("regular", 11), c["crit"], max_w=WIDTH - 24, anchor="lm")
    return img


def to_framebuffer(img: Image.Image) -> Image.Image:
    """Rotates a landscape frame a quarter turn clockwise for the portrait framebuffer."""
    return img.transpose(Image.Transpose.ROTATE_270)


def preview_png(stats: dict | None, page: int | None = None, prefs: dict | None = None) -> bytes:
    buf = io.BytesIO()
    render_frame(stats, page, prefs=prefs).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def seconds_to_next_minute(now: float | None = None) -> float:
    """Time until the clock on the LCD changes (a little after the minute turns)."""
    now = time.time() if now is None else now
    return 60.0 - (now % 60.0) + 0.05


def run_loop(fb: Any, max_wait_s: float, screen_off, state) -> None:
    """
    Draws frames until shutdown. The loop sleeps on the LCD's own wake-up event
    (state.lcd_wake), set by each new stats sample, a page change, a button press, an
    alert or a theme change, and otherwise wakes when the clock's minute turns (at most
    max_wait_s apart). A frame is written only when it differs from the last one.
    """
    wake = getattr(state, "lcd_wake", None) or state.ui_wake
    prev = None
    prev_key = None
    blanked = False
    while not state.shutting_down:
        blanked = screen_off(fb, blanked)
        state.lcd_blanked = blanked  # the stats loop then stops waking it every sample (PERF-20)
        if blanked:
            prev = None
            prev_key = None
            # a button press, a page change or an alert sets the wake event; the blanking schedule
            # changes on the minute (PERF-16, not a poll every second)
            if wake.wait(min(max_wait_s, seconds_to_next_minute())):
                wake.clear()
            continue
        with state.lock:
            stats = dict(state.cached_stats or {})
            page = state.current_lcd_page
        # the same values on the same page in the same minute draw the same frame: skip the render
        # (PERF-16); the minute is part of it for the clock
        key = (page, time.strftime("%Y%m%d%H%M"), repr(sorted(stats.items(), key=lambda kv: str(kv[0]))))
        if key != prev_key:
            frame = to_framebuffer(render_frame(stats, page))
            raw = frame.tobytes()
            if raw != prev:
                fb.write_image(frame)
                prev = raw
            prev_key = key
        if wake.wait(min(max_wait_s, seconds_to_next_minute())):
            wake.clear()
