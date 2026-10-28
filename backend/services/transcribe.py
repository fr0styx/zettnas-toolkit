"""Transcripts of voice memos and videos for the AI index (COMP-03).

A Whisper model on a speech server that speaks the OpenAI API (an OpenVINO Model Server on the
iGPU, LocalAI, faster-whisper-server, ...) turns speech into text, and the index stores that text,
so "what did I say about the roof in that voice memo" finds the file.

Off until a server is set (rag config "transcribe_endpoint"). Audio files are transcribed when it
is set; videos only with "transcribe_video", since a film library would keep the GPU busy for
days. Files longer than "transcribe_max_minutes" (default 30) are left to their file name.

The sound is decoded with PyAV (the ffmpeg libraries the image already has), turned into 16 kHz
mono WAV and sent in ten-minute pieces, each one taking its turn on the GPU behind chat and search
(gpu_queue.INDEX).
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
import uuid
import wave
from collections.abc import Iterator
from typing import Any

from backend.config import logger

RATE = 16000
PIECE_SECS = 600
DEFAULT_MAX_MINUTES = 30
TIMEOUT_SECS = 600.0


def settings(cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        max_minutes = int(cfg.get("transcribe_max_minutes") or DEFAULT_MAX_MINUTES)
    except (TypeError, ValueError):
        max_minutes = DEFAULT_MAX_MINUTES
    return {
        "endpoint": str(cfg.get("transcribe_endpoint") or "").strip().rstrip("/"),
        "model": str(cfg.get("transcribe_model") or "").strip() or "whisper",
        "video": bool(cfg.get("transcribe_video", False)),
        "max_secs": max(1, min(600, max_minutes)) * 60,
    }


def wanted(cfg: dict[str, Any], is_video: bool) -> bool:
    s = settings(cfg)
    return bool(s["endpoint"]) and (s["video"] or not is_video)


def url_for(endpoint: str) -> str:
    return endpoint if endpoint.endswith("/audio/transcriptions") else f"{endpoint}/audio/transcriptions"


def duration_secs(path: str) -> float | None:
    import av

    with av.open(path) as container:
        if not container.streams.audio:
            return None
        if container.duration:
            return container.duration / 1_000_000  # av.time_base
        stream = container.streams.audio[0]
        if stream.duration and stream.time_base:
            return float(stream.duration * stream.time_base)
    return None


def _wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_pieces(path: str, piece_secs: int = PIECE_SECS) -> Iterator[bytes]:
    """The file's first audio track as 16 kHz mono WAV, piece_secs at a time."""
    import av

    piece_bytes = piece_secs * RATE * 2
    with av.open(path) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        pcm = bytearray()
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                pcm += bytes(out.planes[0])[: out.samples * 2]
            while len(pcm) >= piece_bytes:
                yield _wav(bytes(pcm[:piece_bytes]))
                del pcm[:piece_bytes]
        for out in resampler.resample(None):
            pcm += bytes(out.planes[0])[: out.samples * 2]
        if pcm:
            yield _wav(bytes(pcm))


def _multipart(fields: dict[str, str], wav: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode()
        + wav
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send_piece(url: str, model: str, wav: bytes) -> str:
    body, ctype = _multipart({"model": model, "response_format": "json"}, wav)
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": ctype, "User-Agent": "ZettNAS-RAG-Engine/2.0"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as resp:  # noqa: S310 (the configured server only)
        raw = resp.read().decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.strip()  # response_format text
    return str(data.get("text") or "").strip() if isinstance(data, dict) else ""


def transcript(path: str, cfg: dict[str, Any], is_video: bool) -> str:
    """The file's spoken text, or "" (not wanted, too long, no sound, or the server failed)."""
    if not wanted(cfg, is_video):
        return ""
    s = settings(cfg)
    try:
        secs = duration_secs(path)
    except Exception:
        logger.debug(f"[Transcribe] could not read {path}", exc_info=True)
        return ""
    if not secs or secs > s["max_secs"]:
        return ""
    from backend.services import gpu_queue

    texts = []
    t0 = time.monotonic()
    try:
        for wav in wav_pieces(path):
            gpu_queue.wait_turn(gpu_queue.INDEX)
            with gpu_queue.use(gpu_queue.INDEX):
                texts.append(send_piece(url_for(s["endpoint"]), s["model"], wav))
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.info(f"[Transcribe] the speech server failed ({getattr(e, 'reason', e)})")
        return ""
    text = " ".join(t for t in texts if t).strip()
    logger.info(f"[Transcribe] {len(text)} characters from {secs:.0f} s of sound in {time.monotonic() - t0:.0f} s")
    return text
