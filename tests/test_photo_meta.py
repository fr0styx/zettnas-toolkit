"""Photo details for the viewer (backend/services/photo_meta.py)."""

from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational

from backend.services import photo_meta as pm


def make_photo(path, gps=True):
    img = Image.new("RGB", (64, 48), (120, 90, 60))
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "FUJIFILM"
    exif[ExifTags.Base.Model] = "X-S20"
    exif[ExifTags.Base.Artist] = "Someone"
    exif[ExifTags.Base.Orientation] = 6
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    sub[ExifTags.Base.ExposureTime] = IFDRational(1, 500)
    sub[ExifTags.Base.FNumber] = IFDRational(28, 5)
    sub[ExifTags.Base.ISOSpeedRatings] = 400
    sub[ExifTags.Base.FocalLength] = IFDRational(55, 1)
    sub[ExifTags.Base.FocalLengthIn35mmFilm] = 83
    sub[ExifTags.Base.ExposureBiasValue] = IFDRational(67, 100)
    sub[ExifTags.Base.DateTimeOriginal] = "2024:05:01 10:20:30"
    sub[ExifTags.Base.OffsetTimeOriginal] = "+02:00"
    sub[ExifTags.Base.LensModel] = "XF18-55mmF2.8-4 R LM OIS"
    sub[ExifTags.Base.LensSpecification] = (
        IFDRational(18, 1),
        IFDRational(55, 1),
        IFDRational(28, 10),
        IFDRational(4, 1),
    )
    sub[ExifTags.Base.ExposureProgram] = 4
    sub[ExifTags.Base.ColorSpace] = 1
    if gps:
        g = exif.get_ifd(ExifTags.IFD.GPSInfo)
        g[ExifTags.GPS.GPSLatitudeRef] = "N"
        g[ExifTags.GPS.GPSLatitude] = (IFDRational(48, 1), IFDRational(51, 1), IFDRational(3013, 100))
        g[ExifTags.GPS.GPSLongitudeRef] = "E"
        g[ExifTags.GPS.GPSLongitude] = (IFDRational(2, 1), IFDRational(17, 1), IFDRational(4013, 100))
        g[ExifTags.GPS.GPSAltitudeRef] = b"\x00"
        g[ExifTags.GPS.GPSAltitude] = IFDRational(350, 10)
    img.save(path, "JPEG", exif=exif.tobytes())
    return path


def test_reads_exposure_lens_time_and_location(tmp_path):
    meta = pm.extract_image_metadata(str(make_photo(tmp_path / "a.jpg")))
    assert meta["dimensions"] == "64 × 48" and meta["bit_depth"] == 8
    ex = meta["exif"]
    assert ex["camera"] == "FUJIFILM X-S20"
    assert ex["lens"] == "XF18-55mmF2.8-4 R LM OIS"
    assert ex["lens_spec"] == "18–55 mm f/2.8–4"
    assert ex["shutter_speed"] == "1/500 s"
    assert ex["aperture"] == "f/5.6"
    assert ex["iso"] == "ISO 400"
    assert ex["focal_length"] == "55 mm" and ex["focal_length_35mm"] == "83 mm"
    assert ex["exposure_bias"] == "+2/3 EV"
    assert ex["exposure_program"] == "Shutter Priority"
    assert ex["taken_at"] == "2024-05-01T10:20:30+02:00" and ex["utc_offset"] == "+02:00"
    assert ex["color_space"] == "sRGB"
    assert ex["artist"] == "Someone"
    assert ex["orientation"].startswith("Rotated 90")
    assert ex["gps"]["lat"] == 48.858369 and ex["gps"]["lon"] == 2.294481
    assert ex["gps"]["altitude_m"] == 35.0


def test_photo_without_exif_still_has_size(tmp_path):
    p = tmp_path / "plain.png"
    Image.new("RGBA", (10, 20)).save(p)
    meta = pm.extract_image_metadata(str(p))
    assert meta["dimensions"] == "10 × 20" and "exif" not in meta


def test_number_formatting():
    assert pm.shutter_text(1 / 500) == "1/500 s"
    assert pm.shutter_text(2.5) == "2.5 s"
    assert pm.ev_text(-1 / 3) == "−1/3 EV"
    assert pm.ev_text(1.5) == "+1 1/2 EV"
    assert pm.ev_text(0) == "0 EV"


class Tag:
    def __init__(self, values, printable=None):
        self.values = values if isinstance(values, list) else [values]
        self.printable = printable if printable is not None else str(values)


def test_fujifilm_recipe_from_maker_notes():
    tags = {
        "MakerNote Tag 0x1401": Tag(0xA00),  # film mode
        "MakerNote Saturation": Tag(0x4C0, "1216"),
        "MakerNote Tag 0x1403": Tag(200),
        "MakerNote Tag 0x1402": Tag(1),
        "MakerNote Tag 0x1041": Tag(-32),
        "MakerNote Tag 0x1040": Tag(24),
        "MakerNote Tag 0x100F": Tag(-2000),
        "MakerNote Tag 0x1048": Tag(64),
        "MakerNote Tag 0x104E": Tag(0),
        "MakerNote Tag 0x1047": Tag(32),
        "MakerNote Tag 0x104C": Tag(16),
        "MakerNote WhiteBalance": Tag(0, "Auto"),
        "MakerNote WhiteBalanceFineTune": Tag([40, -60], "[40, -60]"),
        "MakerNote Tag 0x1050": Tag(1),
        "MakerNote Tag 0x1438": Tag(1848),
    }
    rows = {r["label"]: r["value"] for r in pm.fujifilm_settings(tags)}
    assert rows == {
        "Film simulation": "Nostalgic Neg.",
        "Dynamic range": "DR200",
        "Highlights": "+2",
        "Shadows": "−1.5",
        "Color": "−3",
        "Clarity": "−2",
        "Color Chrome effect": "Strong",
        "Color Chrome FX Blue": "Off",
        "Grain effect": "Weak, Small",
        "White balance": "Auto, R+2 B−3",
        "Shutter type": "Electronic",
        "Frame count": "1,848",
    }


def test_black_and_white_simulations_come_from_saturation():
    rows = pm.fujifilm_settings({"MakerNote Saturation": Tag(0x501, "1281")})
    assert {"label": "Film simulation", "value": "Acros + R filter"} in rows
