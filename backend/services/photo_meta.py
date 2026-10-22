"""Photo details for the viewer's info panel: camera, lens, exposure, GPS, author and maker settings.

Pillow gives the size, mode and color profile without decoding the image. exifread reads the
EXIF blocks Pillow's top-level getexif() leaves out (the Exif and GPS sub-IFDs hold the exposure,
lens, capture time and location) and Fujifilm's maker notes (film simulation and the other
in-camera settings). Every value is optional: a field is present only when the file has it.
"""

from __future__ import annotations

import io
import re
from fractions import Fraction
from typing import Any

from backend.config import logger

# ---------- small helpers ----------


def _val(tags: dict[str, Any], *names: str) -> Any:
    """The first value of the first tag present (exifread keeps values in a list)."""
    for name in names:
        tag = tags.get(name)
        if tag is None:
            continue
        values = getattr(tag, "values", tag)
        if isinstance(values, (list, tuple)):
            if not values:
                continue
            return values[0] if len(values) == 1 else list(values)
        return values
    return None


def _text(tags: dict[str, Any], *names: str) -> str:
    for name in names:
        tag = tags.get(name)
        if tag is None:
            continue
        s = str(getattr(tag, "printable", tag)).strip().strip("\x00").strip()
        if s and not s.startswith("["):
            return s
    return ""


def _num(value: Any) -> float | None:
    """A number from an exifread Ratio, int, float or 'a/b' string."""
    if value is None:
        return None
    try:
        if hasattr(value, "num") and hasattr(value, "den"):
            return None if value.den == 0 else value.num / value.den
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            return None if value.denominator == 0 else value.numerator / value.denominator
        if isinstance(value, str) and "/" in value:
            a, b = value.split("/", 1)
            return float(a) / float(b) if float(b) else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _trim(n: float, digits: int = 1) -> str:
    s = f"{n:.{digits}f}".rstrip("0").rstrip(".")
    return s or "0"


def shutter_text(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return ""
    if seconds >= 0.3:
        return f"{_trim(seconds)} s"
    return f"1/{round(1 / seconds)} s"


def ev_text(ev: float | None) -> str:
    if ev is None:
        return ""
    if abs(ev) < 0.005:
        return "0 EV"
    frac = Fraction(ev).limit_denominator(3)
    if abs(float(frac) - ev) < 0.02 and frac.denominator in (2, 3):
        whole, rest = divmod(abs(frac.numerator), frac.denominator)
        body = f"{whole} {rest}/{frac.denominator}" if whole else f"{rest}/{frac.denominator}"
    else:
        body = _trim(abs(ev), 2)
    return f"{'+' if ev > 0 else '−'}{body} EV"


def _dms(values: Any, ref: str) -> float | None:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        return None
    parts = [_num(v) for v in values]
    if any(p is None for p in parts):
        return None
    deg = parts[0] + parts[1] / 60 + parts[2] / 3600  # type: ignore[operator]
    return -deg if ref.upper() in ("S", "W") else deg


# ---------- Fujifilm maker notes ----------
# Values from the published Fujifilm maker-note tables (as used by ExifTool).

FUJI_FILM_MODE = {
    0x000: "Provia / Standard",
    0x120: "Astia / Soft",
    0x200: "Velvia / Vivid",
    0x400: "Velvia",
    0x500: "Pro Neg. Std",
    0x501: "Pro Neg. Hi",
    0x600: "Classic Chrome",
    0x700: "Eterna",
    0x800: "Classic Negative",
    0x900: "Eterna Bleach Bypass",
    0xA00: "Nostalgic Neg.",
    0xB00: "Reala Ace",
}
# Black-and-white simulations are stored in the Saturation tag instead
FUJI_MONO = {
    0x300: "Monochrome",
    0x301: "Monochrome + R filter",
    0x302: "Monochrome + Ye filter",
    0x303: "Monochrome + G filter",
    0x310: "Sepia",
    0x500: "Acros",
    0x501: "Acros + R filter",
    0x502: "Acros + Ye filter",
    0x503: "Acros + G filter",
}
FUJI_COLOR = {
    0x000: "0",
    0x080: "+1",
    0x100: "+2",
    0x0C0: "+3",
    0x0E0: "+4",
    0x180: "−1",
    0x400: "−2",
    0x4C0: "−3",
    0x4E0: "−4",
}
FUJI_STRENGTH = {0: "Off", 32: "Weak", 64: "Strong"}
FUJI_GRAIN_SIZE = {0: "", 16: "Small", 32: "Large"}
FUJI_SHUTTER = {0: "Mechanical", 1: "Electronic", 2: "Electronic (long exposure)", 3: "Electronic front curtain"}
FUJI_DR_SETTING = {
    0: "Auto",
    1: "Manual",
    0x100: "Standard",
    0x200: "Wide 1",
    0x201: "Wide 2",
    0x8000: "Film simulation",
}


def _mk(tags: dict[str, Any], code: int, *names: str) -> Any:
    return _val(tags, *(f"MakerNote {n}" for n in names), f"MakerNote Tag 0x{code:04X}")


def _int(v: Any) -> int | None:
    n = _num(v)
    return None if n is None else int(n)


def _tone(raw: Any) -> str:
    """Fujifilm highlight/shadow tone: stored as -16 × the setting."""
    n = _num(raw)
    if n is None:
        return ""
    step = -n / 16
    return "0" if step == 0 else f"{'+' if step > 0 else '−'}{_trim(abs(step))}"


def fujifilm_settings(tags: dict[str, Any]) -> list[dict[str, str]]:
    """The in-camera settings a Fujifilm photo was taken with, as label/value rows."""
    rows: list[dict[str, str]] = []

    def add(label: str, value: str) -> None:
        if value:
            rows.append({"label": label, "value": value})

    film = _int(_mk(tags, 0x1401, "FilmMode"))
    sat = _int(_mk(tags, 0x1003, "Saturation"))
    if film is not None and film in FUJI_FILM_MODE:
        add("Film simulation", FUJI_FILM_MODE[film])
    elif sat is not None and sat in FUJI_MONO:
        add("Film simulation", FUJI_MONO[sat])

    dr = _int(_mk(tags, 0x1403, "DevelopmentDynamicRange"))
    dr_set = _int(_mk(tags, 0x1402, "DynamicRangeSetting"))
    if dr:
        add("Dynamic range", f"DR{dr}" + (" (auto)" if dr_set == 0 else ""))
    elif dr_set in FUJI_DR_SETTING:
        add("Dynamic range", FUJI_DR_SETTING[dr_set])

    add("Highlights", _tone(_mk(tags, 0x1041, "HighlightTone")))
    add("Shadows", _tone(_mk(tags, 0x1040, "ShadowTone")))
    if sat is not None and sat in FUJI_COLOR:
        add("Color", FUJI_COLOR[sat])
    sharp = _text(tags, "MakerNote Sharpness")
    if sharp and not sharp.isdigit():
        add("Sharpness", sharp)
    clarity = _num(_mk(tags, 0x100F, "Clarity"))
    if clarity is not None:
        add("Clarity", "0" if clarity == 0 else f"{'+' if clarity > 0 else '−'}{_trim(abs(clarity) / 1000)}")

    chrome = _int(_mk(tags, 0x1048, "ColorChromeEffect"))
    if chrome in FUJI_STRENGTH:
        add("Color Chrome effect", FUJI_STRENGTH[chrome])
    blue = _int(_mk(tags, 0x104E, "ColorChromeFXBlue"))
    if blue in FUJI_STRENGTH:
        add("Color Chrome FX Blue", FUJI_STRENGTH[blue])
    grain = _int(_mk(tags, 0x1047, "GrainEffectRoughness"))
    if grain in FUJI_STRENGTH:
        size = FUJI_GRAIN_SIZE.get(_int(_mk(tags, 0x104C, "GrainEffectSize")) or 0, "")
        add("Grain effect", FUJI_STRENGTH[grain] + (f", {size}" if grain and size else ""))

    wb = _text(tags, "MakerNote WhiteBalance")
    fine = _mk(tags, 0x100A, "WhiteBalanceFineTune")
    if isinstance(fine, list) and len(fine) >= 2:
        r, b = (_num(fine[0]) or 0) / 20, (_num(fine[1]) or 0) / 20
        shift = f"R{'+' if r >= 0 else '−'}{_trim(abs(r))} B{'+' if b >= 0 else '−'}{_trim(abs(b))}"
        add("White balance", f"{wb}, {shift}" if wb else shift)
    else:
        add("White balance", wb)

    shutter = _int(_mk(tags, 0x1050, "ShutterType"))
    if shutter in FUJI_SHUTTER:
        add("Shutter type", FUJI_SHUTTER[shutter])
    add("Focus mode", _text(tags, "MakerNote FocusMode"))
    count = _int(_mk(tags, 0x1438, "ImageCount"))
    if count:
        add("Frame count", f"{count:,}")
    return rows


# ---------- reading a file ----------


def _xmp_rating(path: str) -> int | None:
    """The star rating from embedded XMP, if any (looked for near the start of the file)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(512 * 1024)
    except OSError:
        return None
    m = re.search(rb"xmp:Rating(?:=\"|>)(-?\d)", head)
    return int(m.group(1)) if m else None


def _color_profile(img: Any) -> str:
    icc = img.info.get("icc_profile") if hasattr(img, "info") else None
    if not icc:
        return ""
    try:
        from PIL import ImageCms

        return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
    except Exception as err:  # no LittleCMS in this Pillow, or an unreadable profile
        logger.debug(f"[PhotoMeta] ICC profile not readable: {err}")
        return ""


BIT_DEPTH = {
    "1": 1,
    "L": 8,
    "P": 8,
    "RGB": 8,
    "RGBA": 8,
    "CMYK": 8,
    "YCbCr": 8,
    "LA": 8,
    "I;16": 16,
    "I;16B": 16,
    "I": 32,
    "F": 32,
}


def read_exif(path: str) -> dict[str, Any]:
    """Everything the info panel shows from a photo's EXIF; {} when there is none."""
    try:
        import exifread

        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, details=True, strict=False)
    except Exception as err:
        logger.debug(f"[PhotoMeta] No EXIF in {path}: {err}")
        return {}
    if not tags:
        return {}
    out: dict[str, Any] = {}

    make = _text(tags, "Image Make")
    model = _text(tags, "Image Model")
    if make or model:
        out["camera"] = model if make and model.lower().startswith(make.lower()) else f"{make} {model}".strip()
    lens = _text(tags, "EXIF LensModel")
    if lens:
        out["lens"] = lens
    spec = _val(tags, "EXIF LensSpecification")
    if isinstance(spec, list) and len(spec) == 4:
        f1, f2, a1, a2 = (_num(v) for v in spec)
        if f1 and f2:
            focal = f"{_trim(f1)} mm" if f1 == f2 else f"{_trim(f1)}–{_trim(f2)} mm"
            aperture = ""
            if a1 and a2:
                aperture = f" f/{_trim(a1)}" if a1 == a2 else f" f/{_trim(a1)}–{_trim(a2)}"
            out["lens_spec"] = focal + aperture

    taken = _text(tags, "EXIF DateTimeOriginal", "Image DateTime")
    if taken:
        out["date_taken"] = taken
        m = re.match(r"(\d{4}):(\d\d):(\d\d)[ T](\d\d):(\d\d):(\d\d)", taken)
        if m:
            iso = "{}-{}-{}T{}:{}:{}".format(*m.groups())
            offset = _text(tags, "EXIF OffsetTimeOriginal", "EXIF OffsetTime")
            if re.fullmatch(r"[+-]\d\d:\d\d", offset):
                iso += offset
                out["utc_offset"] = offset
            out["taken_at"] = iso

    exposure = _num(_val(tags, "EXIF ExposureTime"))
    if exposure:
        out["shutter_speed"] = shutter_text(exposure)
    fnum = _num(_val(tags, "EXIF FNumber"))
    if fnum:
        out["aperture"] = f"f/{_trim(fnum)}"
    iso_val = _val(tags, "EXIF ISOSpeedRatings", "EXIF PhotographicSensitivity")
    if iso_val:
        out["iso"] = f"ISO {iso_val}"
    focal = _num(_val(tags, "EXIF FocalLength"))
    if focal:
        out["focal_length"] = f"{_trim(focal)} mm"
    focal35 = _num(_val(tags, "EXIF FocalLengthIn35mmFilm"))
    if focal35 and focal and round(focal35) != round(focal):
        out["focal_length_35mm"] = f"{round(focal35)} mm"
    bias = _num(_val(tags, "EXIF ExposureBiasValue"))
    if bias is not None:
        out["exposure_bias"] = ev_text(bias)
    for key, tag in (
        ("exposure_program", "EXIF ExposureProgram"),
        ("metering_mode", "EXIF MeteringMode"),
        ("flash", "EXIF Flash"),
        ("white_balance", "EXIF WhiteBalance"),
        ("scene_type", "EXIF SceneCaptureType"),
        ("software", "Image Software"),
        ("artist", "Image Artist"),
        ("copyright", "Image Copyright"),
        ("body_serial", "EXIF BodySerialNumber"),
        ("lens_serial", "EXIF LensSerialNumber"),
    ):
        value = _text(tags, tag)
        if value and value.lower() not in ("unknown", "0"):
            out[key] = value
    distance = _num(_val(tags, "EXIF SubjectDistance"))
    if distance and 0 < distance < 4_000_000:
        out["subject_distance"] = f"{_trim(distance, 2)} m"
    orientation = _text(tags, "Image Orientation")
    if orientation and "normal" not in orientation.lower():
        out["orientation"] = orientation

    space = _text(tags, "EXIF ColorSpace")
    interop = _text(tags, "Interoperability InteroperabilityIndex")
    if space == "sRGB":
        out["color_space"] = "sRGB"
    elif interop == "R03":
        out["color_space"] = "Adobe RGB"
    elif space:
        out["color_space"] = space

    lat = _dms(_val(tags, "GPS GPSLatitude"), _text(tags, "GPS GPSLatitudeRef") or "N")
    lon = _dms(_val(tags, "GPS GPSLongitude"), _text(tags, "GPS GPSLongitudeRef") or "E")
    if lat is not None and lon is not None and not (lat == 0 and lon == 0) and abs(lat) <= 90 and abs(lon) <= 180:
        gps: dict[str, Any] = {"lat": round(lat, 6), "lon": round(lon, 6)}
        alt = _num(_val(tags, "GPS GPSAltitude"))
        if alt is not None:
            below = _val(tags, "GPS GPSAltitudeRef") in (1, b"\x01")
            gps["altitude_m"] = round(-alt if below else alt, 1)
        heading = _num(_val(tags, "GPS GPSImgDirection"))
        if heading is not None:
            gps["direction"] = round(heading)
        out["gps"] = gps

    if "fujifilm" in make.lower():
        rows = fujifilm_settings(tags)
        if rows:
            out["maker_settings"] = {"title": "Fujifilm settings", "rows": rows}

    rating = _xmp_rating(path)
    if rating is not None and 0 < rating <= 5:
        out["rating"] = rating
    return out


def extract_image_metadata(file_path: str) -> dict[str, Any]:
    """Size, megapixels, mode, bit depth, color profile and EXIF for the viewer's info panel."""
    meta: dict[str, Any] = {}
    try:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except Exception:
            logger.debug("[PhotoMeta] HEIF support not available", exc_info=True)
        from PIL import Image

        with Image.open(file_path) as img:
            w, h = img.size
            meta["width"] = w
            meta["height"] = h
            meta["dimensions"] = f"{w} × {h}"
            mp = round((w * h) / 1_000_000, 1)
            if mp > 0:
                meta["megapixels"] = f"{mp} MP"
            meta["color_mode"] = img.mode
            depth = BIT_DEPTH.get(img.mode)
            if depth:
                meta["bit_depth"] = depth
            profile = _color_profile(img)
            if profile:
                meta["color_profile"] = profile
    except Exception:
        logger.debug(f"[PhotoMeta] Could not open {file_path}", exc_info=True)
    exif = read_exif(file_path)
    if exif:
        meta["exif"] = exif
    return meta
