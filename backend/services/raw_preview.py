"""The JPEG preview inside a DNG (Adobe's RAW format, which iPhones save as Apple ProRAW).

A DNG is a TIFF file: besides the RAW sensor data it carries ready-made 8-bit JPEG previews,
usually one at full size. Browsers and Pillow can't show the RAW data, so thumbnails and the
viewer use the preview that fits: the smallest one at least as large as asked for, else the
largest. Only the TIFF directories are read, then that one JPEG, never the RAW data.
"""

import struct
from typing import IO

RAW_EXTS = {".dng"}

_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8}
_INT_FORMATS = {3: "H", 4: "I", 13: "I", 16: "Q"}
_WIDTH, _HEIGHT, _BITS, _COMPRESSION, _ORIENTATION = 256, 257, 258, 259, 274
_STRIP_OFFSETS, _SAMPLES, _STRIP_BYTES, _SUB_IFDS = 273, 277, 279, 330
_JPEG_OFFSET, _JPEG_LENGTH = 513, 514
_JPEG_COMPRESSIONS = {6, 7}
_MAX_IFDS = 32


class _Reader:
    def __init__(self, f: IO[bytes]):
        self.f = f
        f.seek(0)
        head = f.read(8)
        if len(head) < 8 or head[:2] not in (b"II", b"MM"):
            raise ValueError("not a TIFF file")
        self.e = "<" if head[:2] == b"II" else ">"
        if struct.unpack(self.e + "H", head[2:4])[0] != 42:
            raise ValueError("not a TIFF file")
        self.first = struct.unpack(self.e + "I", head[4:8])[0]

    def ifd(self, offset: int) -> tuple[dict[int, list[int]], int]:
        """The integer tags of one directory, and the offset of the next one (0 at the end)."""
        f, e = self.f, self.e
        f.seek(offset)
        raw = f.read(2)
        if len(raw) < 2:
            raise ValueError("truncated directory")
        tags: dict[int, list[int]] = {}
        for _ in range(min(struct.unpack(e + "H", raw)[0], 1024)):
            entry = f.read(12)
            if len(entry) < 12:
                raise ValueError("truncated directory")
            tag, typ, count, value = struct.unpack(e + "HHI4s", entry)
            fmt = _INT_FORMATS.get(typ)
            if fmt is None or count > 4096:
                continue
            size = _TYPE_SIZES[typ] * count
            if size > 4:
                here = f.tell()
                f.seek(struct.unpack(e + "I", value)[0])
                value = f.read(size)
                f.seek(here)
            if len(value) >= size:
                tags[tag] = list(struct.unpack(e + fmt * count, value[:size]))
        nxt = f.read(4)
        return tags, (struct.unpack(e + "I", nxt)[0] if len(nxt) == 4 else 0)

    def directories(self) -> list[dict[int, list[int]]]:
        """Every directory: the main chain and their sub-directories, a bounded number."""
        found: list[dict[int, list[int]]] = []
        todo, seen = [self.first], set()
        while todo and len(found) < _MAX_IFDS:
            offset = todo.pop(0)
            if not offset or offset in seen:
                continue
            seen.add(offset)
            tags, nxt = self.ifd(offset)
            found.append(tags)
            todo.extend(tags.get(_SUB_IFDS, []))
            todo.append(nxt)
        return found


def _jpeg_at(tags: dict[int, list[int]]) -> tuple[int, int] | None:
    """(offset, length) of the directory's whole-picture 8-bit JPEG, or None."""
    if tags.get(_COMPRESSION, [0])[0] not in _JPEG_COMPRESSIONS:
        return None
    if any(b != 8 for b in tags.get(_BITS, [8])) or tags.get(_SAMPLES, [3])[0] not in (1, 3):
        return None
    if _JPEG_OFFSET in tags and _JPEG_LENGTH in tags:
        return tags[_JPEG_OFFSET][0], tags[_JPEG_LENGTH][0]
    offsets, counts = tags.get(_STRIP_OFFSETS, []), tags.get(_STRIP_BYTES, [])
    if len(offsets) == 1 and len(counts) == 1:
        return offsets[0], counts[0]
    return None


def preview(f: IO[bytes], limit: int) -> tuple[bytes, int] | None:
    """The best JPEG preview for a picture `limit` pixels on its longest side, and the file's
    orientation (EXIF numbering, 1 = upright); None when the file has none."""
    reader = _Reader(f)
    dirs = reader.directories()
    orientation = dirs[0].get(_ORIENTATION, [1])[0] if dirs else 1
    found = []
    for tags in dirs:
        at = _jpeg_at(tags)
        if at:
            longest = max(tags.get(_WIDTH, [0])[0], tags.get(_HEIGHT, [0])[0])
            found.append((longest, at))
    if not found:
        return None
    big_enough = [c for c in found if c[0] >= limit]
    _longest, (offset, length) = min(big_enough) if big_enough else max(found)
    f.seek(offset)
    data = f.read(length)
    if not data.startswith(b"\xff\xd8"):
        return None
    return data, orientation
