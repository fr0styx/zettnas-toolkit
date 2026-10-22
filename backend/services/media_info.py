"""
What is inside a video or audio file, read with PyAV (the ffmpeg libraries).

Used by the explorer's details panel and by the viewer, which decides from it
whether the browser can play the file as it is or needs the converted stream
(backend/services/video_compat.py). Reading the headers takes a few
milliseconds; results are kept in memory per path, size and modification time.
"""

import logging
import os
import threading
from collections import OrderedDict
from typing import Any

logger = logging.getLogger("zettnas.media_info")

_CACHE: OrderedDict[tuple, dict[str, Any] | None] = OrderedDict()
_LOCK = threading.Lock()
_MAX = 512
_HDR_TRANSFER = {16, 18}  # SMPTE ST 2084 (PQ), ARIB STD-B67 (HLG)


def probe(path: str) -> dict[str, Any] | None:
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime_ns)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    info = _probe(path)
    with _LOCK:
        _CACHE[key] = info
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    return info


def _first_frame_rotation(container, stream) -> int:
    """Display rotation in degrees (iPhone portrait clips say -90); only a decoded frame carries it."""
    try:
        for frame in container.decode(stream):
            return int(getattr(frame, "rotation", 0) or 0)
    except Exception:
        logger.debug("No frame to read the rotation from", exc_info=True)
    return 0


def _probe(path: str) -> dict[str, Any] | None:
    import av

    try:
        container = av.open(path)
    except Exception as e:
        logger.info("Not a media file %s: %s", os.path.basename(path), e)
        return None
    with container:
        info: dict[str, Any] = {
            "container": container.format.name,
            "duration": round(container.duration / 1_000_000, 3) if container.duration else None,
            "bitrate": container.bit_rate or None,
            "video": None,
            "audio": None,
            "subtitle_streams": len(container.streams.subtitles),
        }
        if container.streams.audio:
            a = container.streams.audio[0].codec_context
            layout = getattr(a, "layout", None)
            info["audio"] = {
                "codec": a.name,
                "channels": getattr(layout, "nb_channels", None),
                "sample_rate": a.sample_rate,
            }
        if container.streams.video:
            s = container.streams.video[0]
            cc = s.codec_context
            pix = cc.pix_fmt or ""
            fps = float(s.average_rate) if s.average_rate else None
            rotation = _first_frame_rotation(container, s)
            width, height = cc.width, cc.height
            if abs(rotation) % 180 == 90:
                width, height = height, width
            info["video"] = {
                "codec": cc.name,
                "profile": cc.profile,
                "width": width,
                "height": height,
                "fps": round(fps, 3) if fps else None,
                "rotation": rotation,
                "bit_depth": 12 if "12" in pix else (10 if "10" in pix else 8),
                "hdr": getattr(cc, "color_trc", None) in _HDR_TRANSFER,
            }
            if info["duration"] is None and s.duration and s.time_base:
                info["duration"] = round(float(s.duration * s.time_base), 3)
        return info
