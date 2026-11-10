"""
Thumbnails and screen-sized previews for the file explorer and viewer.

Photos (including Apple HEIC/HEIF) are decoded with Pillow, videos with PyAV
(the ffmpeg libraries): one frame about a second in, turned upright. Results
are WebP files cached on disk under data/cache/thumbs, keyed by path, size,
modification time and the requested size, so an edited file gets a fresh
thumbnail. The cache is trimmed, oldest first, when it grows past
KIBOTO_THUMB_CACHE_MB (default 1024 MB). Files that can't be decoded are
remembered too, so a broken file isn't retried on every visit.
"""

import hashlib
import io
import logging
import os
import threading
import time
from typing import Optional

from backend import config, legacy_names

logger = logging.getLogger("kiboto.thumbs")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif", ".heic", ".heif", ".dng"}
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".3gp", ".mts", ".m2ts", ".wmv", ".mpg", ".mpeg"}
THUMB_SIZE = 256
MAX_SIZE = 3840
_VERSION = "1"
_PRUNE_EVERY = 200
_RECOUNT_EVERY = 5000

_image_slots = threading.BoundedSemaphore(max(2, min(4, (os.cpu_count() or 2) // 2)))
_video_slots = threading.BoundedSemaphore(2)
_state_lock = threading.Lock()
_writes = 0
_approx_bytes: int | None = None
_on_screen = 0  # thumbnails someone is looking at right now; work made ahead of time waits for them
SCREEN_WAIT_S = 10.0  # the cache's size since the last walk plus what was written
_heif_ready = False


def kind(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def cache_dir() -> str:
    return legacy_names.getenv("KIBOTO_THUMB_CACHE_DIR") or os.path.join(config.DATA_DIR, "cache", "thumbs")


def cache_limit_bytes() -> int:
    return max(16, config.SETTINGS.thumb_cache_mb) * 1024 * 1024


def _key(path: str, st: os.stat_result, limit: int) -> str:
    raw = f"{_VERSION}|{path}|{st.st_size}|{st.st_mtime_ns}|{limit}"
    return hashlib.sha256(raw.encode("utf-8", "surrogateescape")).hexdigest()


def _paths(key: str) -> tuple[str, str]:
    base = os.path.join(cache_dir(), key[:2], key)
    return base + ".webp", base + ".fail"


TOUCH_EVERY_SECS = 86400.0


def cached(path: str, limit: int = THUMB_SIZE) -> bool:
    """True when the thumbnail, or the note that the file can't be decoded, is already cached."""
    limit = max(32, min(int(limit), MAX_SIZE))
    hit, fail = _paths(_key(path, os.stat(path), limit))
    return os.path.exists(hit) or os.path.exists(fail)


def _yield_to_screen() -> None:
    """Background work waits (a while) for the thumbnails on someone's screen to be made first."""
    deadline = time.time() + SCREEN_WAIT_S
    while _on_screen > 0 and time.time() < deadline:
        time.sleep(0.05)


def _render_for(path: str, limit: int, background: bool) -> bytes | None:
    global _on_screen
    if background:
        _yield_to_screen()
        return render(path, limit)
    with _state_lock:
        _on_screen += 1
    try:
        return render(path, limit)
    finally:
        with _state_lock:
            _on_screen -= 1


def get(path: str, limit: int = THUMB_SIZE, background: bool = False) -> bytes | None:
    """WebP bytes no larger than `limit` on the longest side, or None if the file can't be decoded.
    `background` (made ahead of time, NPERF-8) lets the thumbnails on screen go first."""
    limit = max(32, min(int(limit), MAX_SIZE))
    from backend.fsutil import ENCRYPTED_ROOT

    if os.path.realpath(path).startswith(ENCRYPTED_ROOT + os.sep):
        return render(path, limit)  # an encrypted folder's pictures are never kept readable (NSEC-3)
    st = os.stat(path)
    hit, fail = _paths(_key(path, st, limit))
    try:
        with open(hit, "rb") as f:
            data = f.read()
        try:
            # recently used, so trimmed last: touched at most once a day, not on every hit (PERF-26)
            if time.time() - os.stat(hit).st_mtime > TOUCH_EVERY_SECS:
                os.utime(hit)
        except OSError:
            logger.debug("Could not touch %s", hit, exc_info=True)
        return data
    except FileNotFoundError:
        logger.debug("No cached thumbnail for %s", os.path.basename(path))
    if os.path.exists(fail):
        return None
    data = _render_for(path, limit, background)
    _store(hit if data else fail, data or b"")
    return data


def render(path: str, limit: int) -> bytes | None:
    k = kind(path)
    try:
        if k == "video":
            with _video_slots:
                img = _video_frame(path)
        else:
            with _image_slots:
                img = _open_image(path, limit)
        return None if img is None else encode(img, limit)
    except Exception as e:
        logger.info("No preview for %s: %s", os.path.basename(path), e)
        return None


def encode(img, limit: int) -> bytes:
    """A decoded picture as WebP no larger than `limit` on its longest side."""
    from PIL import Image

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    if max(img.size) > limit:
        img.thumbnail((limit, limit), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80 if limit <= THUMB_SIZE else 86, method=4)
    return buf.getvalue()


def _open_raw(path: str, limit: int):
    """A DNG's embedded JPEG preview, turned upright (NPERF-9)."""
    from PIL import Image

    from backend.services import raw_preview

    with open(path, "rb") as f:
        found = raw_preview.preview(f, limit)
    if found is None:
        return None
    data, orientation = found
    img = Image.open(io.BytesIO(data))
    img.draft("RGB", (limit, limit))
    img.load()
    turn = {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }.get(orientation)
    return img.transpose(turn) if turn is not None else img


def _open_image(path: str, limit: int):
    global _heif_ready
    from PIL import Image, ImageOps

    if os.path.splitext(path)[1].lower() == ".dng":
        return _open_raw(path, limit)
    if not _heif_ready:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except Exception:
            logger.debug("HEIF support unavailable", exc_info=True)
        _heif_ready = True
    img = Image.open(path)
    try:
        img.draft("RGB", (limit, limit))  # JPEG: decode at a reduced scale, much faster
    except Exception:
        logger.debug("draft mode unavailable for %s", path, exc_info=True)
    img.load()
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        logger.debug("exif_transpose failed for %s", path, exc_info=True)
    return img


def _video_frame(path: str):
    import av

    with av.open(path) as container:
        if not container.streams.video:
            return None
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        duration = container.duration / 1_000_000 if container.duration else 0
        target = min(1.0, duration * 0.1) if duration else 0
        if target > 0:
            try:
                container.seek(int(target * 1_000_000))
            except Exception:
                container.seek(0)
        for frame in container.decode(stream):
            img = frame.to_image()
            rotation = getattr(frame, "rotation", 0) or 0
            if rotation:
                img = img.rotate(rotation, expand=True)  # display rotation from the file (iPhone portrait clips)
            return img
    return None


def _store(target: str, data: bytes) -> None:
    global _writes
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = f"{target}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except OSError as e:
        logger.warning("Could not cache thumbnail: %s", e)
        return
    global _approx_bytes
    with _state_lock:
        _writes += 1
        if _approx_bytes is None:
            due = _writes % _PRUNE_EVERY == 0
        else:
            # walk the cache only when it may be full (or now and then to correct the count), not
            # every few hundred writes: a library-sized cache holds hundreds of thousands (NPERF-8)
            _approx_bytes += len(data)
            due = _approx_bytes > cache_limit_bytes() or _writes % _RECOUNT_EVERY == 0
    if due:
        threading.Thread(target=prune, name="thumb-prune", daemon=True).start()


def prune(limit: int | None = None) -> int:
    """Deletes the least recently used entries until the cache is under 80% of its limit. Returns bytes freed."""
    limit = cache_limit_bytes() if limit is None else limit
    entries = []
    total = 0
    for root, _dirs, files in os.walk(cache_dir()):
        for name in files:
            p = os.path.join(root, name)
            try:
                st = os.stat(p)
            except OSError:
                logger.debug("Cache entry vanished: %s", p)
                continue
            if name.endswith(".tmp") and time.time() - st.st_mtime < 300:
                continue
            entries.append((st.st_mtime, st.st_size, p))
            total += st.st_size
    global _approx_bytes
    if total <= limit:
        _approx_bytes = total
        return 0
    freed = 0
    goal = total - int(limit * 0.8)
    for _mtime, size, p in sorted(entries):
        if freed >= goal:
            break
        try:
            os.remove(p)
            freed += size
        except OSError:
            logger.debug("Could not remove %s", p, exc_info=True)
    _approx_bytes = total - freed
    logger.info("Thumbnail cache trimmed by %.1f MB", freed / 1048576)
    return freed
