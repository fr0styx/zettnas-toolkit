"""
Videos converted while they play, for browsers that can't play the original.

iPhones record HEVC (H.265), which Safari and some Chrome/Edge builds play but
Firefox and many Windows and Linux browsers don't; MKV/AVI files and AC-3/DTS
audio have the same problem. This streams the file as fragmented MP4 with
H.264 video and AAC audio, starting at any second (the viewer restarts the
stream to seek). Encoding uses libx264 "veryfast" at up to 720p, about 7x
real time for a 1080p iPhone clip on a typical NAS CPU. At most two
conversions run at once.
"""

import logging
import queue
import threading
from collections.abc import Iterator
from fractions import Fraction

from backend.services import media_info

logger = logging.getLogger("zettnas.video_compat")

MAX_LONG_SIDE = 1280
_slots = threading.BoundedSemaphore(2)


class Busy(RuntimeError):
    pass


class _Sink:
    """File-like object the MP4 muxer writes into; hands chunks to the HTTP response."""

    def __init__(self, q: "queue.Queue[bytes | None]", stop: threading.Event):
        self.q = q
        self.stop = stop

    def write(self, data) -> int:
        if self.stop.is_set():
            raise BrokenPipeError("client went away")
        self.q.put(bytes(data))
        return len(data)

    def flush(self) -> None:
        return None


def _scaled(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, MAX_LONG_SIDE / max(width, height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def _convert(path: str, start: float, sink: _Sink) -> None:
    import av

    with av.open(path) as src:
        if not src.streams.video:
            raise ValueError("no video stream")
        vin = src.streams.video[0]
        vin.thread_type = "AUTO"
        ain = src.streams.audio[0] if src.streams.audio else None
        if start > 0:
            src.seek(int(start * 1_000_000))  # nearest keyframe before; earlier frames are dropped below
        fps = vin.average_rate or Fraction(30, 1)
        with av.open(
            sink, "w", format="mp4", options={"movflags": "frag_keyframe+empty_moov+default_base_moof"}
        ) as out:
            w, h = _scaled(vin.codec_context.width, vin.codec_context.height)
            vout = out.add_stream("libx264", rate=fps)
            vout.width, vout.height, vout.pix_fmt = w, h, "yuv420p"
            vout.codec_context.time_base = Fraction(1, 90_000)
            # Keep the display rotation (iPhone portrait clips). It must be set before the
            # first packet is written, which may be audio, so take it from the file's details.
            details = media_info.probe(path) or {}
            rot = int(((details.get("video") or {}).get("rotation")) or 0)
            if rot:
                try:
                    vout.set_display_rotation(rot)
                except Exception:
                    logger.debug("Could not keep the rotation", exc_info=True)
            vout.options = {"preset": "veryfast", "crf": "23", "g": str(max(12, int(round(float(fps)) * 2)))}
            aout = None
            resampler = None
            if ain is not None:
                aout = out.add_stream("aac", rate=48000)
                aout.layout = "stereo"
                resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
            last_vpts = -1
            next_apts = None
            streams = [vin] + ([ain] if ain is not None else [])
            for packet in src.demux(*streams):
                if sink.stop.is_set():
                    break
                for frame in packet.decode():
                    if isinstance(frame, av.VideoFrame):
                        if frame.time is not None and frame.time < start:
                            continue
                        t = (frame.time or 0.0) - start
                        scaled = frame.reformat(width=w, height=h, format="yuv420p")
                        # Timestamps from the stream's start point, always increasing
                        last_vpts = max(last_vpts + 1, int(round(max(0.0, t) * 90_000)))
                        scaled.pts, scaled.time_base = last_vpts, Fraction(1, 90_000)
                        for p in vout.encode(scaled):
                            out.mux(p)
                    elif isinstance(frame, av.AudioFrame) and aout is not None and resampler is not None:
                        if frame.time is not None and frame.time < start:
                            continue
                        if next_apts is None:
                            next_apts = int(round(max(0.0, (frame.time or start) - start) * 48_000))
                        frame.pts = None
                        for rf in resampler.resample(frame):
                            rf.pts, rf.time_base = next_apts, Fraction(1, 48_000)
                            next_apts += rf.samples
                            for p in aout.encode(rf):
                                out.mux(p)
            for p in vout.encode():
                out.mux(p)
            if aout is not None:
                for p in aout.encode():
                    out.mux(p)


def stream(path: str, start: float = 0.0) -> tuple[Iterator[bytes], threading.Event]:
    """(chunks, stop): iterate the chunks; set stop when the client disconnects."""
    if not _slots.acquire(blocking=False):
        raise Busy("Two videos are already being converted")
    q: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
    stop = threading.Event()

    def worker():
        try:
            _convert(path, max(0.0, start), _Sink(q, stop))
        except BrokenPipeError:
            logger.debug("Viewer closed the converted stream of %s", path)
        except Exception as e:
            logger.warning("Video conversion failed for %s: %s", path, e)
        finally:
            _slots.release()
            q.put(None)

    threading.Thread(target=worker, name="video-compat", daemon=True).start()

    def chunks() -> Iterator[bytes]:
        try:
            while True:
                item = q.get()
                if item is None:
                    return
                yield item
        finally:
            stop.set()
            while not q.empty():  # unblock the worker so it notices the stop
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    return chunks(), stop
