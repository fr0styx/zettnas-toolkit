"""
Videos converted for browsers that can't play the original.

iPhones record HEVC (H.265), which Safari and some Chrome/Edge builds play but
Firefox and many Windows and Linux browsers don't; MKV/AVI files and AC-3/DTS/PCM
audio have the same problem. When the browser plays the video but not the audio or
the container, the video is copied as it is and only the audio becomes AAC (COPY);
otherwise the video becomes H.264 too (FULL), at up to 720p, with Intel Quick Sync
when /dev/dri is passed through, else libx264 "veryfast".

A clip is converted once into data/cache/video as a complete MP4, which the browser
buffers and seeks like any file: clips up to two minutes on the spot, longer ones in
the background while the first viewing streams live as fragmented MP4 (the viewer
restarts that stream to seek). At most two conversions run at once.
"""

import logging
import os
import queue
import threading
import time
from collections.abc import Iterator
from fractions import Fraction

from backend.services import media_info

logger = logging.getLogger("kiboto.video_compat")

MAX_LONG_SIDE = 1280
_slots = threading.BoundedSemaphore(2)
_encoder_choice: dict[str, str] = {}
_RENDER_NODE = "/dev/dri/renderD128"


def _hwenc_allowed() -> bool:
    from backend import config

    return config.SETTINGS.video_hwenc != "off"


def pick_encoder() -> str:
    """h264_qsv (Intel Quick Sync) when the GPU is passed through and works, else libx264.

    Quick Sync converted a 1080p iPhone clip at about 11x real time against 5x for
    libx264, and leaves the CPU free. KIBOTO_VIDEO_HWENC=off forces software.
    """
    if "codec" in _encoder_choice:
        return _encoder_choice["codec"]
    codec = "libx264"
    if _hwenc_allowed() and os.path.exists(_RENDER_NODE):
        try:
            import av

            ctx = av.CodecContext.create("h264_qsv", "w")
            ctx.width, ctx.height, ctx.pix_fmt = 256, 144, "nv12"
            ctx.time_base = Fraction(1, 30)
            ctx.open()
            frame = av.VideoFrame(256, 144, "nv12")
            frame.pts = 0
            ctx.encode(frame)
            ctx.encode(None)
            codec = "h264_qsv"
        except Exception as e:
            logger.info("Quick Sync unavailable, converting videos on the CPU: %s", e)
    _encoder_choice["codec"] = codec
    logger.info("Video conversion encoder: %s", codec)
    return codec


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


COPY, FULL = "copy", "full"  # copy: the video as it is, only the audio made AAC; full: H.264 too (NVID-1)


class _VideoOut:
    """The video track: copied packet by packet (COPY) or re-encoded to H.264 (FULL)."""

    def __init__(self, out, vin, path: str, mode: str):
        from av.video.stream import VideoStream

        self.out, self.vin, self.mode = out, vin, mode
        self.origin: float | None = None  # COPY: the source time the output starts at
        self.last_pts = -1
        if mode == COPY:
            self.vout = out.add_stream_from_template(vin)  # codec and its side data (rotation) kept
            if vin.codec_context.name == "hevc":
                self.vout.codec_tag = "hvc1"  # the tag browsers want for HEVC in MP4
            return
        fps = vin.average_rate or Fraction(30, 1)
        self.w, self.h = _scaled(vin.codec_context.width, vin.codec_context.height)
        codec = pick_encoder()
        self.pix = "nv12" if codec == "h264_qsv" else "yuv420p"
        vout = out.add_stream(codec, rate=fps)
        if not isinstance(vout, VideoStream):
            raise TypeError(f"{codec} is not a video encoder")
        vout.width, vout.height, vout.pix_fmt = self.w, self.h, self.pix
        vout.codec_context.time_base = Fraction(1, 90_000)
        # Keep the display rotation (iPhone portrait clips). It must be set before the
        # first packet is written, which may be audio, so take it from the file's details.
        rot = int((((media_info.probe(path) or {}).get("video") or {}).get("rotation")) or 0)
        if rot:
            try:
                vout.set_display_rotation(rot)
            except Exception:
                logger.debug("Could not keep the rotation", exc_info=True)
        gop = str(max(12, int(round(float(fps)) * 2)))
        if codec == "h264_qsv":
            # no B-frames: Quick Sync's reordered timestamps are refused by a complete (non-fragmented) MP4
            vout.options = {"preset": "veryfast", "global_quality": "25", "look_ahead": "0", "g": gop, "bf": "0"}
        else:
            vout.options = {"preset": "veryfast", "crf": "23", "g": gop}
        # opened now, before any packet: the audio may be written first, and a complete MP4's
        # header needs the video encoder's settings by then
        vout.codec_context.open()
        self.vout = vout

    def packet(self, packet, start: float) -> None:
        if self.mode == COPY:
            self._copy(packet)
            return
        import av

        for frame in packet.decode():
            if not isinstance(frame, av.VideoFrame) or (frame.time is not None and frame.time < start):
                continue
            t = (frame.time or 0.0) - start
            scaled = frame.reformat(width=self.w, height=self.h, format=self.pix)
            # Timestamps from the stream's start point, always increasing
            self.last_pts = max(self.last_pts + 1, int(round(max(0.0, t) * 90_000)))
            scaled.pts, scaled.time_base = self.last_pts, Fraction(1, 90_000)
            for p in self.vout.encode(scaled):
                self.out.mux(p)

    def _copy(self, packet) -> None:
        stamp = packet.dts if packet.dts is not None else packet.pts
        if stamp is None:
            return  # the demuxer's flush packet
        if self.origin is None:
            self.origin = float(stamp * packet.time_base)  # the keyframe a seek landed on
        shift = int(round(self.origin / packet.time_base))
        packet.pts = None if packet.pts is None else packet.pts - shift
        packet.dts = None if packet.dts is None else packet.dts - shift
        packet.stream = self.vout
        self.out.mux(packet)

    def start_time(self, start: float) -> float | None:
        """Where the audio is measured from: the requested second (FULL) or the keyframe (COPY)."""
        return start if self.mode == FULL else self.origin

    def flush(self) -> None:
        if self.mode == FULL:
            for p in self.vout.encode():
                self.out.mux(p)


class _AudioOut:
    """The audio track, always AAC stereo 48 kHz (PCM, AC-3, DTS and the like don't play in browsers)."""

    def __init__(self, out, ain):
        import av

        self.out = out
        self.aout = out.add_stream("aac", rate=48000)
        self.aout.layout = "stereo"
        self.resampler = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        self.next_pts: int | None = None

    def packet(self, packet, origin: float | None) -> None:
        import av

        if origin is None:
            return  # COPY: not until the video's first keyframe says where the output starts
        for frame in packet.decode():
            if not isinstance(frame, av.AudioFrame) or (frame.time is not None and frame.time < origin):
                continue
            if self.next_pts is None:
                self.next_pts = int(round(max(0.0, (frame.time or origin) - origin) * 48_000))
            frame.pts = None
            for rf in self.resampler.resample(frame):
                rf.pts, rf.time_base = self.next_pts, Fraction(1, 48_000)
                self.next_pts += rf.samples
                for p in self.aout.encode(rf):
                    self.out.mux(p)

    def flush(self) -> None:
        for p in self.aout.encode():
            self.out.mux(p)


def _convert(path: str, start: float, sink, mode: str = FULL, fragmented: bool = True) -> None:
    """Writes the converted video to `sink`: a _Sink for a live fragmented stream from `start`,
    or a file name for a complete MP4 with its index at the front (the cache)."""
    import av

    with av.open(path) as src:
        if not src.streams.video:
            raise ValueError("no video stream")
        vin = src.streams.video[0]
        vin.thread_type = "AUTO"
        ain = src.streams.audio[0] if src.streams.audio else None
        if start > 0:
            src.seek(int(start * 1_000_000))  # nearest keyframe before; earlier frames are dropped below
        flags = "frag_keyframe+empty_moov+default_base_moof" if fragmented else "+faststart"
        with av.open(sink, "w", format="mp4", options={"movflags": flags}) as out:
            video = _VideoOut(out, vin, path, mode)
            audio = _AudioOut(out, ain) if ain is not None else None
            stop = getattr(sink, "stop", None)
            for packet in src.demux(*([vin] + ([ain] if ain is not None else []))):
                if stop is not None and stop.is_set():
                    break
                if packet.stream is vin or packet.stream.index == vin.index:
                    video.packet(packet, start)
                elif audio is not None:
                    audio.packet(packet, video.start_time(start))
            video.flush()
            if audio is not None:
                audio.flush()


def stream(path: str, start: float = 0.0, mode: str = FULL) -> tuple[Iterator[bytes], threading.Event]:
    """(chunks, stop): iterate the chunks; set stop when the client disconnects."""
    if not _slots.acquire(blocking=False):
        raise Busy("Two videos are already being converted")
    q: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
    stop = threading.Event()

    def worker():
        try:
            _convert(path, max(0.0, start), _Sink(q, stop), mode)
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


# --- converted clips kept on disk (NVID-1) ---------------------------------------------------
# A clip converted once is kept as a complete MP4 with its index at the front, so the browser
# buffers, seeks and replays it like any video file instead of restarting a live conversion.
SHORT_S = 120.0  # clips up to two minutes are converted on the spot (about a second) before playing
CACHE_MAX_S = 20 * 60.0  # longer ones stream live, and up to this length are kept for next time
_VERSION = "1"
_preparing: set[str] = set()
_prep_lock = threading.Lock()


def cache_dir() -> str:
    from backend import config

    return os.path.join(config.DATA_DIR, "cache", "video")


def cache_limit_bytes() -> int:
    from backend import config

    return max(64, config.SETTINGS.video_cache_mb) * 1024 * 1024


def _cache_file(path: str, mode: str) -> str:
    import hashlib

    st = os.stat(path)
    raw = f"{_VERSION}|{path}|{st.st_size}|{st.st_mtime_ns}|{mode}"
    return os.path.join(cache_dir(), hashlib.sha256(raw.encode("utf-8", "surrogateescape")).hexdigest() + ".mp4")


def cached(path: str, mode: str) -> str | None:
    """The kept conversion of this version of the file, or None."""
    target = _cache_file(path, mode)
    if not os.path.exists(target):
        return None
    try:
        if time.time() - os.stat(target).st_mtime > 86400:
            os.utime(target)  # recently watched: trimmed last
    except OSError:
        logger.debug("Could not touch %s", target, exc_info=True)
    return target


def ready(path: str) -> dict[str, bool]:
    """Which conversions of the file are kept, for the viewer to pick."""
    return {mode: cached(path, mode) is not None for mode in (COPY, FULL)}


def convert_file(path: str, mode: str) -> str:
    """Converts the clip into the cache (waiting for a free slot) and returns the file."""
    done = cached(path, mode)
    if done:
        return done
    target = _cache_file(path, mode)
    os.makedirs(cache_dir(), exist_ok=True)
    tmp = f"{target}.{os.getpid()}.{threading.get_ident()}.tmp"
    if not _slots.acquire(timeout=120):
        raise Busy("Two videos are already being converted")
    try:
        _convert(path, 0.0, tmp, mode, fragmented=False)
        os.replace(tmp, target)
    finally:
        _slots.release()
        if os.path.exists(tmp):
            os.remove(tmp)
    prune()
    return target


def prepare(path: str, mode: str, duration: float | None) -> bool:
    """Converts a clip into the cache in the background, shown in the Jobs centre; False when it
    is kept already, being prepared, or too long to keep."""
    if (duration or 0) > CACHE_MAX_S or cached(path, mode):
        return False
    key = f"{mode}|{path}"
    with _prep_lock:
        if key in _preparing:
            return False
        _preparing.add(key)

    def work():
        from backend.services.jobs import job_manager

        job = job_manager.register(
            "video", "Converting a video for this browser", title_id="jobs.t.video", title_params={}
        )
        job_manager.update(job.id, detail=os.path.basename(path))
        try:
            convert_file(path, mode)
            job_manager.finish(job.id)
        except (OSError, ValueError, Busy) as e:
            logger.warning("Could not keep a converted copy of %s: %s", path, e)
            job_manager.finish(job.id, "error", str(e))
        finally:
            with _prep_lock:
                _preparing.discard(key)

    threading.Thread(target=work, name="video-prepare", daemon=True).start()
    return True


def prune(limit: int | None = None) -> int:
    """Removes the least recently watched conversions until the cache is under its limit."""
    limit = cache_limit_bytes() if limit is None else limit
    try:
        names = [os.path.join(cache_dir(), n) for n in os.listdir(cache_dir()) if n.endswith(".mp4")]
    except FileNotFoundError:
        return 0
    entries = []
    for p in names:
        try:
            st = os.stat(p)
        except OSError:
            continue
        entries.append((st.st_mtime, st.st_size, p))
    total = sum(e[1] for e in entries)
    freed = 0
    for _mtime, size, p in sorted(entries):
        if total - freed <= limit:
            break
        try:
            os.remove(p)
            freed += size
        except OSError:
            logger.debug("Could not remove %s", p, exc_info=True)
    return freed
