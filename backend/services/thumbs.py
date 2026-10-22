"""
Thumbnails and screen-sized previews for the file explorer and viewer.

Photos (including Apple HEIC/HEIF) are decoded with Pillow, videos with PyAV
(the ffmpeg libraries): one frame about a second in, turned upright. Results
are WebP files cached on disk under data/cache/thumbs, keyed by path, size,
modification time and the requested size, so an edited file gets a fresh
thumbnail. The cache is trimmed, oldest first, when it grows past
ZETTNAS_THUMB_CACHE_MB (default 1024 MB). Files that can't be decoded are
remembered too, so a broken file isn't retried on every visit.
"""

import hashlib
import io
import logging
import os
import threading
import time
from typing import Optional

from backend import config

logger = logging.getLogger("zettnas.thumbs")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".3gp", ".mts", ".m2ts", ".wmv", ".mpg", ".mpeg"}
THUMB_SIZE = 256
MAX_SIZE = 3840
_VERSION = "1"
_PRUNE_EVERY = 200

_image_slots = threading.BoundedSemaphore(max(2, min(4, (os.cpu_count() or 2) // 2)))
_video_slots = threading.BoundedSemaphore(2)
_state_lock = threading.Lock()
_writes = 0
_heif_ready = False


def kind(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


def cache_dir() -> str:
    return os.environ.get("ZETTNAS_THUMB_CACHE_DIR") or os.path.join(config.DATA_DIR, "cache", "thumbs")


def cache_limit_bytes() -> int:
    try:
        mb = int(os.environ.get("ZETTNAS_THUMB_CACHE_MB", "1024"))
    except ValueError:
        mb = 1024
    return max(16, mb) * 1024 * 1024


def _key(path: str, st: os.stat_result, limit: int) -> str:
    raw = f"{_VERSION}|{path}|{st.st_size}|{st.st_mtime_ns}|{limit}"
    return hashlib.sha256(raw.encode("utf-8", "surrogateescape")).hexdigest()


def _paths(key: str) -> tuple[str, str]:
    base = os.path.join(cache_dir(), key[:2], key)
    return base + ".webp", base + ".fail"


def get(path: str, limit: int = THUMB_SIZE) -> bytes | None:
    """WebP bytes no larger than `limit` on the longest side, or None if the file can't be decoded."""
    limit = max(32, min(int(limit), MAX_SIZE))
    st = os.stat(path)
    hit, fail = _paths(_key(path, st, limit))
    try:
        with open(hit, "rb") as f:
            data = f.read()
        try:
            os.utime(hit)  # recently used: trimmed last
        except OSError:
            logger.debug("Could not touch %s", hit, exc_info=True)
        return data
    except FileNotFoundError:
        logger.debug("No cached thumbnail for %s", os.path.basename(path))
    if os.path.exists(fail):
        return None
    data = render(path, limit)
    _store(hit if data else fail, data or b"")
    return data


def render(path: str, limit: int) -> bytes | None:
    from PIL import Image

    k = kind(path)
    try:
        if k == "video":
            with _video_slots:
                img = _video_frame(path)
        else:
            with _image_slots:
                img = _open_image(path, limit)
        if img is None:
            return None
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        if max(img.size) > limit:
            img.thumbnail((limit, limit), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=80 if limit <= THUMB_SIZE else 86, method=4)
        return buf.getvalue()
    except Exception as e:
        logger.info("No preview for %s: %s", os.path.basename(path), e)
        return None


def _open_image(path: str, limit: int):
    global _heif_ready
    from PIL import Image, ImageOps

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
    with _state_lock:
        _writes += 1
        due = _writes % _PRUNE_EVERY == 0
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
    if total <= limit:
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
    logger.info("Thumbnail cache trimmed by %.1f MB", freed / 1048576)
    return freed
