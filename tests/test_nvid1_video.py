"""NVID-1: a video the browser can't play is converted once and kept as a plain MP4; when only its
audio (or container) is the problem the video is kept as it is and only the audio becomes AAC."""

import io
import os
import time
from fractions import Fraction

import av
import pytest
from PIL import Image

from backend.services import jobs, media_info, video_compat
from backend.services.jobs import job_manager


def _clip(path, seconds=1.0, fps=20):
    """A small H.264 video with PCM audio in a MOV, like the clips that need converting."""
    with av.open(str(path), "w", format="mov") as out:
        v = out.add_stream("libx264", rate=fps)
        v.width, v.height, v.pix_fmt = 160, 120, "yuv420p"
        a = out.add_stream("pcm_s16le", rate=44100)
        a.layout = "mono"
        for i in range(int(seconds * fps)):
            frame = av.VideoFrame.from_image(Image.new("RGB", (160, 120), ((i * 9) % 255, 80, 160)))
            frame.pts = i
            for p in v.encode(frame):
                out.mux(p)
        for p in v.encode():
            out.mux(p)
        samples = int(seconds * 44100)
        audio = av.AudioFrame(format="s16", layout="mono", samples=samples)
        audio.planes[0].update(bytes(audio.planes[0].buffer_size))
        audio.sample_rate, audio.pts, audio.time_base = 44100, 0, Fraction(1, 44100)
        for p in a.encode(audio):
            out.mux(p)
        for p in a.encode():
            out.mux(p)
    return str(path)


def _frames(data_or_path):
    src = av.open(io.BytesIO(data_or_path) if isinstance(data_or_path, bytes) else data_or_path)
    try:
        return sum(1 for _ in src.decode(video=0))
    finally:
        src.close()


@pytest.fixture()
def clip(tmp_path, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setitem(video_compat._encoder_choice, "codec", "libx264")
    monkeypatch.setattr(jobs, "HISTORY_FILE", str(tmp_path / "jobs_history.json"))
    monkeypatch.setattr(job_manager, "_history", [])
    monkeypatch.setattr(job_manager, "_history_loaded", True)
    return _clip(tmp_path / "clip.MOV")


def test_copy_keeps_the_video_and_makes_the_audio_aac(clip):
    out = video_compat.convert_file(clip, video_compat.COPY)
    info = media_info.probe(out)
    assert info["video"]["codec"] == "h264" and (info["video"]["width"], info["video"]["height"]) == (160, 120)
    assert info["audio"]["codec"] == "aac"
    assert _frames(out) == _frames(clip) == 20
    assert video_compat.ready(clip) == {"copy": True, "full": False}
    assert video_compat.cached(clip, video_compat.COPY) == out


def test_full_converts_everything_with_every_frame(clip):
    out = video_compat.convert_file(clip, video_compat.FULL)
    info = media_info.probe(out)
    assert info["video"]["codec"] == "h264" and info["audio"]["codec"] == "aac"
    assert _frames(out) == 20


@pytest.mark.parametrize("mode", ["copy", "full"])
def test_the_live_stream_carries_every_frame_from_where_it_starts(clip, mode):
    chunks, _stop = video_compat.stream(clip, 0.0, mode)
    assert _frames(b"".join(chunks)) == 20
    chunks, _stop = video_compat.stream(clip, 0.5, mode)
    assert 0 < _frames(b"".join(chunks)) <= 20


def test_a_changed_file_is_converted_again(clip):
    first = video_compat.convert_file(clip, video_compat.COPY)
    os.utime(clip, (time.time() + 10, time.time() + 10))
    assert (
        video_compat.cached(clip, video_compat.COPY) is None
        and video_compat.convert_file(clip, video_compat.COPY) != first
    )


def test_the_cache_keeps_to_its_size_least_recently_watched_first(clip, tmp_path):
    a = video_compat.convert_file(clip, video_compat.COPY)
    b = video_compat.convert_file(clip, video_compat.FULL)
    os.utime(a, (1, 1))
    assert video_compat.prune(limit=os.path.getsize(b)) > 0
    assert not os.path.exists(a) and os.path.exists(b)
    assert video_compat.prune(limit=10**9) == 0


def test_a_long_clip_is_prepared_in_the_background_as_a_job(clip, monkeypatch):
    assert video_compat.prepare(clip, video_compat.COPY, duration=video_compat.CACHE_MAX_S + 1) is False
    assert video_compat.prepare(clip, video_compat.COPY, duration=300) is True
    deadline = time.time() + 30
    while video_compat._preparing and time.time() < deadline:
        time.sleep(0.05)
    assert video_compat.cached(clip, video_compat.COPY)
    (job,) = [j for j in job_manager.list(everyone=True)["history"] if j["kind"] == "video"]
    assert job["status"] == "done" and job["detail"] == "clip.MOV"
    assert video_compat.prepare(clip, video_compat.COPY, duration=300) is False  # kept already


def test_the_converted_file_is_served_with_ranges(client, auth_headers, monkeypatch, tmp_path):
    from backend import config

    monkeypatch.setitem(video_compat._encoder_choice, "codec", "libx264")
    pool = os.environ["POOL_PATH"]
    path = _clip(os.path.join(pool, "nvid1.MOV"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    try:
        r = client.get("/api/fs/media/info", params={"path": path}, headers=auth_headers)
        assert r.json()["converted"] == {"copy": False, "full": False}
        r = client.get("/api/fs/video/converted", params={"path": path, "mode": "copy"}, headers=auth_headers)
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        r = client.get(
            "/api/fs/video/converted",
            params={"path": path, "mode": "copy"},
            headers={**auth_headers, "Range": "bytes=0-99"},
        )
        assert r.status_code == 206 and len(r.content) == 100
        assert (
            client.get("/api/fs/video/converted", params={"path": path, "mode": "x"}, headers=auth_headers).status_code
            == 400
        )
        prepared = []
        monkeypatch.setattr(video_compat, "SHORT_S", 0.0)
        monkeypatch.setattr(video_compat, "prepare", lambda *a: prepared.append(a) or True)
        r = client.get("/api/fs/video/converted", params={"path": path, "mode": "full"}, headers=auth_headers)
        assert r.status_code == 202 and prepared
        r = client.get("/api/fs/stream/compat", params={"path": path, "mode": "copy"}, headers=auth_headers)
        assert r.status_code == 200 and _frames(r.content) == 20
    finally:
        os.remove(path)
