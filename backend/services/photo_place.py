"""When and where a photo was taken (AI-24): the EXIF capture date and GPS position, HEIC included,
a place name for the position found offline, and the dates and places a question names.

taken_at is the camera's clock read as UTC, so a photo taken at 23:30 on 1 June stays on 1 June
whatever the server's time zone; the date filters work on the same scale.

Place names come from backend/data/places.tsv.gz (name, region, country, latitude, longitude per
line), made by scripts/build_places.py from GeoNames (CC BY 4.0). Without the file a photo keeps
its position and gets no name; nothing is looked up online.
"""

from __future__ import annotations

import calendar
import gzip
import io
import logging
import math
import os
import re
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

EXIF_EXTENSIONS = (".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".heic", ".heif", ".png", ".dng")
PLACES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "places.tsv.gz")
MAX_PLACE_KM = 40.0  # farther from any town than this: no name rather than a wrong one
_CELL = 1.0  # degrees per grid cell of the place index

_heif_ready = False


def ensure_heif() -> None:
    """Lets Pillow open HEIC/HEIF photos (iPhone pictures)."""
    global _heif_ready
    if _heif_ready:
        return
    _heif_ready = True
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:
        logger.debug("[PhotoPlace] pillow-heif not available", exc_info=True)


def _ratio(v: Any) -> float:
    num = getattr(v, "num", None)
    den = getattr(v, "den", None)
    if num is not None and den is not None:
        return float(num) / float(den or 1)
    if isinstance(v, str) and "/" in v:
        a, b = v.split("/", 1)
        return float(a) / float(b or 1)
    return float(v)


def _coord(tags: dict, key: str, ref_key: str) -> float | None:
    tag = tags.get(key)
    if tag is None:
        return None
    try:
        vals = list(getattr(tag, "values", tag))
        deg = (
            _ratio(vals[0])
            + (_ratio(vals[1]) / 60.0 if len(vals) > 1 else 0)
            + (_ratio(vals[2]) / 3600.0 if len(vals) > 2 else 0)
        )
    except (TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    ref = str(tags.get(ref_key) or "").strip().upper()
    return -deg if ref in ("S", "W") else deg


def taken_epoch(text: str) -> float | None:
    """'2023:06:01 23:30:12' (EXIF) as the camera's clock read as UTC."""
    m = re.match(r"\s*(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", text or "")
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    if not (1980 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None  # 0000:00:00 and other placeholders
    try:
        return float(calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0)))
    except (ValueError, OverflowError):
        return None


def _exifread_tags(src: str | bytes) -> dict:
    import exifread

    if isinstance(src, bytes):
        return exifread.process_file(io.BytesIO(src), details=False, strict=False)
    with open(src, "rb") as fh:
        return exifread.process_file(fh, details=False, strict=False)


def _pillow_tags(src: str | bytes) -> dict:
    """The same tags read by Pillow, in exifread's names: for files exifread can't parse (some
    HEIC files make its parser give up)."""
    from PIL import Image

    ensure_heif()
    with Image.open(io.BytesIO(src) if isinstance(src, bytes) else src) as img:
        exif = img.getexif()
        sub = exif.get_ifd(0x8769)
        gps = exif.get_ifd(0x8825)
    out: dict[str, Any] = {}
    for key, val in (
        ("EXIF DateTimeOriginal", sub.get(0x9003)),
        ("EXIF DateTimeDigitized", sub.get(0x9004)),
        ("Image DateTime", exif.get(0x0132)),
    ):
        if val:
            out[key] = str(val)
    for key, tag in (
        ("GPS GPSLatitudeRef", 1),
        ("GPS GPSLatitude", 2),
        ("GPS GPSLongitudeRef", 3),
        ("GPS GPSLongitude", 4),
    ):
        if tag in gps:
            out[key] = gps[tag]
    return out


def when_where(src: str | bytes, name: str = "") -> tuple[float | None, float | None, float | None]:
    """(taken_at, latitude, longitude) from a photo's EXIF; None for what it lacks."""
    probe = src if isinstance(src, str) else name
    if not str(probe).lower().endswith(EXIF_EXTENSIONS):
        return None, None, None
    tags: dict = {}
    for reader in (_exifread_tags, _pillow_tags):
        try:
            tags = reader(src)
        except Exception:
            logger.debug(f"[PhotoPlace] {reader.__name__} read no EXIF from {name or src!s:.120}", exc_info=True)
            tags = {}
        if any(k.startswith(("EXIF DateTime", "Image DateTime", "GPS GPSLat")) for k in tags):
            break
    taken = None
    for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
        if key in tags:
            taken = taken_epoch(str(tags[key]))
            if taken is not None:
                break
    lat = _coord(tags, "GPS GPSLatitude", "GPS GPSLatitudeRef")
    lon = _coord(tags, "GPS GPSLongitude", "GPS GPSLongitudeRef")
    if (
        lat is None
        or lon is None
        or not (-90 <= lat <= 90 and -180 <= lon <= 180)
        or (abs(lat) < 1e-6 and abs(lon) < 1e-6)
    ):
        lat = lon = None  # 0,0 is a camera without a fix
    return taken, (round(lat, 6) if lat is not None else None), (round(lon, 6) if lon is not None else None)


# --- offline place names -------------------------------------------------------------------------

_places: dict[tuple[int, int], list[tuple[float, float, str]]] | None = None
_places_lock = threading.Lock()


def _load_places(path: str | None = None) -> dict[tuple[int, int], list[tuple[float, float, str]]]:
    global _places
    if _places is not None and path is None:
        return _places
    grid: dict[tuple[int, int], list[tuple[float, float, str]]] = {}
    p = path or PLACES_FILE
    if os.path.isfile(p):
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 5:
                        continue
                    name, region, country = parts[0], parts[1], parts[2]
                    try:
                        lat, lon = float(parts[3]), float(parts[4])
                    except ValueError:
                        continue
                    label = ", ".join(x for x in (name, region if region != name else "", country) if x)
                    grid.setdefault((math.floor(lat / _CELL), math.floor(lon / _CELL)), []).append((lat, lon, label))
        except (OSError, EOFError):
            logger.warning("[PhotoPlace] the place list could not be read", exc_info=True)
    if path is None:
        _places = grid
    return grid


def use_places(path: str | None) -> None:
    """Loads another place list (tests), or forgets the loaded one (None)."""
    global _places
    with _places_lock:
        _places = _load_places(path) if path else None


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def place_for(lat: float | None, lon: float | None) -> str:
    """'Rome, Lazio, Italy' for a position, from the nearest town in the place list; '' when the
    list is missing or no town is within MAX_PLACE_KM."""
    if lat is None or lon is None:
        return ""
    with _places_lock:
        grid = _load_places()
    if not grid:
        return ""
    cy, cx = math.floor(lat / _CELL), math.floor(lon / _CELL)
    best, best_km = "", MAX_PLACE_KM
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for plat, plon, label in grid.get((cy + dy, ((cx + dx + 180) % 360) - 180), ()):
                d = _km(lat, lon, plat, plon)
                if d < best_km:
                    best, best_km = label, d
    return best


# --- what a caption and a question say ------------------------------------------------------------

MONTHS = {
    # English, German, French, Spanish (and common short forms)
    1: ("january", "jan", "januar", "janvier", "enero"),
    2: ("february", "feb", "februar", "février", "fevrier", "febrero"),
    3: ("march", "mar", "märz", "maerz", "mars", "marzo"),
    4: ("april", "apr", "avril", "abril"),
    5: ("may", "mai", "mayo"),
    6: ("june", "jun", "juni", "juin", "junio"),
    7: ("july", "jul", "juli", "juillet", "julio"),
    8: ("august", "aug", "août", "aout", "agosto"),
    9: ("september", "sep", "sept", "septembre", "septiembre"),
    10: ("october", "oct", "oktober", "octobre", "octubre"),
    11: ("november", "nov", "novembre", "noviembre"),
    12: ("december", "dec", "dezember", "décembre", "decembre", "diciembre"),
}
_MONTH_WORD = {w: m for m, words in MONTHS.items() for w in words}
SEASONS = {
    "summer": (6, 8), "sommer": (6, 8), "été": (6, 8), "ete": (6, 8), "verano": (6, 8), "夏天": (6, 8),
    "winter": (12, 2), "hiver": (12, 2), "invierno": (12, 2), "冬天": (12, 2),
    "spring": (3, 5), "frühling": (3, 5), "printemps": (3, 5), "primavera": (3, 5), "春天": (3, 5),
    "autumn": (9, 11), "fall": (9, 11), "herbst": (9, 11), "automne": (9, 11), "otoño": (9, 11), "秋天": (9, 11),
}  # fmt: skip
LAST_YEAR = (
    "last year",
    "letztes jahr",
    "letzten jahr",
    "vergangenes jahr",
    "l'année dernière",
    "l'an dernier",
    "el año pasado",
    "去年",
)
THIS_YEAR = ("this year", "dieses jahr", "diesem jahr", "cette année", "este año", "今年")
_YEAR = re.compile(r"(?<!\d)(19[89]\d|20\d\d)(?!\d)")
_CJK_MONTH = re.compile(r"(19[89]\d|20\d\d)\s*年\s*(\d{1,2})\s*月")


def _span(y1: int, m1: int, y2: int, m2: int) -> tuple[float, float]:
    """From the first of month m1/y1 to the end of month m2/y2."""
    start = calendar.timegm((y1, m1, 1, 0, 0, 0, 0, 0, 0))
    ny, nm = (y2 + 1, 1) if m2 == 12 else (y2, m2 + 1)
    return float(start), float(calendar.timegm((ny, nm, 1, 0, 0, 0, 0, 0, 0)))


def when_in_question(question: str, now: float | None = None) -> tuple[float, float, str] | None:
    """The time a question names, as (start, end, label): 'June 2023', 'Sommer 2022', '2019',
    'last year', '2023年6月'. None when it names no time, or two different years."""
    q = (question or "").lower()
    this_year = time.gmtime(now or time.time()).tm_year
    m = _CJK_MONTH.search(q)
    if m and 1 <= int(m.group(2)) <= 12:
        y, mo = int(m.group(1)), int(m.group(2))
        return (*_span(y, mo, y, mo), f"{y}-{mo:02d}")
    years = sorted(set(_YEAR.findall(q)))
    if len(years) > 1:
        return None
    year = int(years[0]) if years else None
    if year is None:
        if any(p in q for p in LAST_YEAR):
            year = this_year - 1
        elif any(p in q for p in THIS_YEAR):
            year = this_year
    words = re.findall(r"[^\W\d_]+", q)
    for w in words:
        if w in SEASONS and year:
            m1, m2 = SEASONS[w]
            if m1 > m2:  # winter 2023: December 2023 to February 2024
                return (*_span(year, m1, year + 1, m2), f"{year}-winter")
            return (*_span(year, m1, year, m2), f"{year}-{w}")
    for w in words:
        mo = _MONTH_WORD.get(w)
        if not mo or not year:
            continue
        # "may", "mar" or "sept" are words or short forms: they count only right before the year
        if len(w) <= 4 and not re.search(rf"(?<![\w]){re.escape(w)}\.?\s+{year}(?!\d)", q):
            continue
        return (*_span(year, mo, year, mo), f"{year}-{mo:02d}")
    if year:
        return (*_span(year, 1, year, 12), str(year))
    return None


def when_label(taken_at: float | None) -> str:
    """'June 2023' for a caption (English: the caption is read by the search and the chat)."""
    if taken_at is None:
        return ""
    t = time.gmtime(taken_at)
    return f"{calendar.month_name[t.tm_mon]} {t.tm_year}"


def caption_suffix(taken_at: float | None, place: str) -> str:
    parts = []
    if taken_at is not None:
        parts.append(f"taken {when_label(taken_at)}")
    if place:
        parts.append(f"in {place}")
    return " ".join(parts)


def place_in_question(question: str, labels: list[str]) -> str | None:
    """The place a question names, among the places the photos were taken: a town, region or
    country of a known label, matched as whole words. The longest match wins ('New York' over
    'York')."""
    q = f" {(question or '').lower()} "
    best = None
    for label in labels:
        for part in (p.strip() for p in label.split(",")):
            if len(part) < 3:
                continue
            pl = part.lower()
            if re.search(rf"(?<![\w]){re.escape(pl)}(?![\w])", q) and (best is None or len(pl) > len(best)):
                best = part
    return best


def span_for(value: str | None) -> tuple[float, float] | None:
    """The time a filter chip names: '2023' or '2023-06'."""
    m = re.fullmatch(r"\s*(19[89]\d|20\d\d)(?:-(\d{1,2}))?\s*", value or "")
    if not m:
        return None
    y = int(m.group(1))
    if m.group(2):
        mo = int(m.group(2))
        return _span(y, mo, y, mo) if 1 <= mo <= 12 else None
    return _span(y, 1, y, 12)


PHOTO_WORDS = (
    "photo", "photos", "picture", "pictures", "pic", "pics", "selfie", "selfies", "image", "images",
    "foto", "fotos", "bild", "bilder", "aufnahme", "aufnahmen", "image", "images", "imagen", "imágenes",
    "照片", "相片", "图片",
)  # fmt: skip
_PHOTO_WORD = re.compile(
    "|".join(re.escape(w) if re.search(r"[一-鿿]", w) else rf"(?<![\w]){re.escape(w)}(?![\w])" for w in PHOTO_WORDS)
)


def asks_for_photos(question: str) -> bool:
    """'photos from Rome', 'Fotos vom Sommer 2022', '2023年的照片': a question about pictures, so the
    date and place it names filter the photos."""
    return bool(_PHOTO_WORD.search((question or "").lower()))


# --- photos indexed before dates and places were read ---------------------------------------------

BACKFILL_BATCH = 200


def pending(conn: sqlite3.Connection, limit: int = BACKFILL_BATCH * 4) -> list[tuple]:
    """Photos indexed before AI-24 whose date and position were never read."""
    return conn.execute(
        "SELECT p.file_id, f.canonical_path, f.backing_dev, p.caption_text FROM photo_assets p "
        "JOIN indexed_files f ON f.file_id = p.file_id WHERE p.when_where_done = 0 AND f.parse_status = 'ok' LIMIT ?",
        (limit,),
    ).fetchall()


def read_pending(rows: list[tuple], is_awake, batch: int = BACKFILL_BATCH) -> list[tuple]:
    """Reads the EXIF of up to `batch` of these photos, only on disks that are awake
    (is_awake(backing_dev, path)); a photo on a sleeping disk waits for a night it is awake.
    Returns the updates for apply()."""
    out: list[tuple] = []
    for fid, path, dev, caption in rows:
        if len(out) >= batch:
            break
        if not is_awake(dev or "", path):
            continue
        if not os.path.isfile(path):
            out.append((None, None, None, "", caption, fid))
            continue
        taken, lat, lon = when_where(path, os.path.basename(path))
        place = place_for(lat, lon)
        suffix = caption_suffix(taken, place)
        new_caption = f"{caption}, {suffix}" if suffix and suffix not in (caption or "") else caption
        out.append((taken, lat, lon, place, new_caption, fid))
    return out


def apply(conn: sqlite3.Connection, updates: list[tuple]) -> None:
    conn.executemany(
        "UPDATE photo_assets SET taken_at = ?, gps_lat = ?, gps_lon = ?, location_label = ?, caption_text = ?, "
        "when_where_done = 1 WHERE file_id = ?",
        updates,
    )


def backfill(conn: sqlite3.Connection, is_awake, batch: int = BACKFILL_BATCH) -> tuple[int, int]:
    """pending + read_pending + apply on one connection. Returns (read now, still waiting)."""
    rows = pending(conn, batch * 4)
    updates = read_pending(rows, is_awake, batch)
    apply(conn, updates)
    return len(updates), len(rows) - len(updates)
