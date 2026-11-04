"""NPERF-9: a DNG (RAW, Apple ProRAW) shows its embedded JPEG preview as thumbnail and in the viewer."""

import io
import os
import struct

import pytest
from PIL import Image

from backend.services import raw_preview, thumbs


def _jpeg(w, h, color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


def make_dng(previews, orientation=1, raw_sub=True, first_compression=7):
    """A small TIFF laid out like a DNG: IFD0 holds the first preview, a sub-directory the RAW data
    (12-bit, compression 7) and more sub-directories the other previews. previews: (w, h, jpeg, tags)
    where tags is "strip" or "jpeg" (JPEGInterchangeFormat)."""
    blobs = []
    data = bytearray(b"II*\x00\x00\x00\x00\x00")

    def add_blob(b):
        pos = len(data)
        data.extend(b)
        if len(data) % 2:
            data.append(0)
        return pos

    def write_ifd(entries):
        # entries: list of (tag, type, [values]); arrays longer than 4 bytes are stored out of line
        sizes = {3: 2, 4: 4}
        resolved = []
        for tag, typ, vals in entries:
            raw = struct.pack("<" + ("H" if typ == 3 else "I") * len(vals), *vals)
            if len(raw) > 4:
                resolved.append((tag, typ, len(vals), struct.pack("<I", add_blob(raw))))
            else:
                resolved.append((tag, typ, len(vals), raw.ljust(4, b"\x00")))
        pos = len(data)
        data.extend(struct.pack("<H", len(resolved)))
        for tag, typ, count, value in sorted(resolved):
            data.extend(struct.pack("<HHI", tag, typ, count) + value)
        data.extend(b"\x00\x00\x00\x00")
        return pos

    def preview_entries(w, h, jpeg, how, subfile):
        off = add_blob(jpeg)
        e = [(254, 4, [subfile]), (256, 4, [w]), (257, 4, [h]), (258, 3, [8, 8, 8]), (259, 3, [7]), (277, 3, [3])]
        if how == "jpeg":
            e[4] = (259, 3, [6])
            e += [(513, 4, [off]), (514, 4, [len(jpeg)])]
        else:
            e += [(273, 4, [off]), (279, 4, [len(jpeg)])]
        return e

    subs = []
    if raw_sub:
        raw_off = add_blob(b"\x00" * 64)
        subs.append(
            write_ifd(
                [
                    (254, 4, [0]),
                    (256, 4, [4000]),
                    (257, 4, [3000]),
                    (258, 3, [12, 12, 12]),
                    (259, 3, [7]),
                    (277, 3, [3]),
                    (273, 4, [raw_off]),
                    (279, 4, [64]),
                ]
            )
        )
    for w, h, jpeg, how in previews[1:]:
        subs.append(write_ifd(preview_entries(w, h, jpeg, how, 1)))
    w, h, jpeg, how = previews[0]
    first = preview_entries(w, h, jpeg, how, 1) + [(274, 3, [orientation])]
    first = [(259, 3, [first_compression]) if e[0] == 259 else e for e in first]
    if subs:
        first.append((330, 4, subs))
    ifd0 = write_ifd(first)
    data[4:8] = struct.pack("<I", ifd0)
    return bytes(data)


def test_the_preview_that_fits_is_chosen(tmp_path):
    big, small = _jpeg(400, 300, (10, 200, 10)), _jpeg(160, 120, (10, 10, 200))
    path = tmp_path / "a.dng"
    path.write_bytes(make_dng([(400, 300, big, "strip"), (160, 120, small, "jpeg")]))
    with open(path, "rb") as f:
        assert raw_preview.preview(f, 128) == (small, 1)
        assert raw_preview.preview(f, 256) == (big, 1)
        assert raw_preview.preview(f, 2560) == (big, 1)  # none big enough: the largest


def test_a_file_without_a_jpeg_preview_has_none(tmp_path):
    path = tmp_path / "raw-only.dng"
    path.write_bytes(make_dng([(400, 300, _jpeg(40, 30), "strip")], first_compression=1))  # uncompressed: not a JPEG
    with open(path, "rb") as f:
        assert raw_preview.preview(f, 256) is None


@pytest.mark.parametrize("head", [b"", b"GIF89a....", b"II\x2b\x00\x08\x00\x00\x00"])
def test_a_file_that_is_not_tiff_is_refused(tmp_path, head):
    path = tmp_path / "bad.dng"
    path.write_bytes(head)
    with open(path, "rb") as f, pytest.raises(ValueError):
        raw_preview.preview(f, 256)


def test_a_preview_whose_bytes_are_not_jpeg_is_ignored(tmp_path):
    path = tmp_path / "odd.dng"
    path.write_bytes(make_dng([(400, 300, b"\x00\x01not-a-jpeg", "strip")], raw_sub=False))
    with open(path, "rb") as f:
        assert raw_preview.preview(f, 256) is None


def test_a_dng_thumbnail_is_its_preview_turned_upright(tmp_path):
    path = tmp_path / "portrait.dng"
    path.write_bytes(make_dng([(400, 300, _jpeg(400, 300), "strip")], orientation=6))
    assert thumbs.kind(str(path)) == "image"
    data = thumbs.render(str(path), 256)
    with Image.open(io.BytesIO(data)) as im:
        assert im.format == "WEBP" and im.size == (192, 256)


def test_a_dng_without_a_preview_gets_no_thumbnail(tmp_path):
    path = tmp_path / "nothing.dng"
    path.write_bytes(make_dng([(400, 300, b"\x00\x01not-a-jpeg", "strip")], raw_sub=False))
    assert thumbs.render(str(path), 256) is None


def test_the_viewer_treats_a_dng_as_a_picture(client, auth_headers):
    pool = os.environ["POOL_PATH"]
    path = os.path.join(pool, "nperf9.dng")
    with open(path, "wb") as f:
        f.write(make_dng([(400, 300, _jpeg(400, 300), "strip")]))
    try:
        r = client.get("/api/fs/preview", params={"path": path}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["type"] == "image"
        assert r.json()["url"].startswith("/api/fs/preview/image?path=")
        r = client.get("/api/fs/preview/image", params={"path": path}, headers=auth_headers)
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    finally:
        os.remove(path)
