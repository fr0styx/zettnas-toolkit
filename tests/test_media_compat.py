"""Video details for the explorer and videos converted while playing for browsers that can't play them."""

import io
from unittest.mock import patch

import pytest
from PIL import Image

av = pytest.importorskip("av")

from backend.services import media_info, video_compat  # noqa: E402


def _video(path, w=320, h=240, seconds=3, rate=10, rotation=0, audio=True):
    with av.open(str(path), "w") as out:
        st = out.add_stream("mpeg4", rate=rate)
        st.width, st.height, st.pix_fmt = w, h, "yuv420p"
        if rotation:
            st.set_display_rotation(rotation)
        ast = out.add_stream("aac", rate=48000) if audio else None
        if ast is not None:
            ast.layout = "stereo"
        for i in range(seconds * rate):
            frame = av.VideoFrame.from_image(Image.new("RGB", (w, h), (i * 7 % 255, 80, 160)))
            for p in st.encode(frame):
                out.mux(p)
        for p in st.encode():
            out.mux(p)
        if ast is not None:
            silence = av.AudioFrame(format="fltp", layout="stereo", samples=1024)
            for plane in silence.planes:
                plane.update(bytes(plane.buffer_size))
            silence.sample_rate = 48000
            for i in range(seconds * 48000 // 1024):
                silence.pts = i * 1024
                for p in ast.encode(silence):
                    out.mux(p)
            for p in ast.encode():
                out.mux(p)


def _decode(data):
    with av.open(io.BytesIO(data)) as c:
        s = c.streams.video[0]
        frames = list(c.decode(s))
        return s.codec_context.name, frames, (c.streams.audio[0].codec_context.name if c.streams.audio else None)


def test_probe_reports_codec_size_duration_and_rotation(tmp_path):
    src = tmp_path / "IMG_0001.MOV"
    _video(src, rotation=-90)
    info = media_info.probe(str(src))
    assert info["video"]["codec"] == "mpeg4"
    assert info["video"]["rotation"] == -90
    assert (info["video"]["width"], info["video"]["height"]) == (240, 320)  # as shown: portrait
    assert 2.5 <= info["duration"] <= 3.5
    assert info["audio"]["codec"] == "aac"
    (tmp_path / "notes.txt").write_text("hello")
    assert media_info.probe(str(tmp_path / "notes.txt")) is None


def test_compat_stream_is_h264_aac_and_keeps_rotation(tmp_path):
    src = tmp_path / "clip.mov"
    _video(src, rotation=-90)
    chunks, _stop = video_compat.stream(str(src), 0)
    codec, frames, audio = _decode(b"".join(chunks))
    assert codec == "h264" and audio == "aac"
    assert len(frames) >= 25
    assert frames[0].rotation == -90


def test_compat_stream_starts_where_asked(tmp_path):
    src = tmp_path / "clip.mp4"
    _video(src, seconds=4, audio=False)
    chunks, _stop = video_compat.stream(str(src), 2.0)
    _codec, frames, _audio = _decode(b"".join(chunks))
    assert 15 <= len(frames) <= 22  # about the last two seconds
    assert frames[0].time < 0.5  # timestamps start at zero; the viewer adds the offset


def test_endpoints(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    root.mkdir()
    _video(root / "a.mov", audio=False)
    (root / "notes.txt").write_text("x")
    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(root)]):
        r = client.get("/api/fs/media/info", params={"path": str(root / "a.mov")}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["video"]["codec"] == "mpeg4"
        assert (
            client.get("/api/fs/media/info", params={"path": str(root / "notes.txt")}, headers=auth_headers).status_code
            == 415
        )
        r = client.get("/api/fs/stream/compat", params={"path": str(root / "a.mov")}, headers=auth_headers)
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        assert _decode(r.content)[0] == "h264"
        assert (
            client.get(
                "/api/fs/stream/compat", params={"path": str(root / "notes.txt")}, headers=auth_headers
            ).status_code
            == 415
        )
        with patch.object(video_compat, "stream", side_effect=video_compat.Busy("busy")):
            r = client.get("/api/fs/stream/compat", params={"path": str(root / "a.mov")}, headers=auth_headers)
            assert r.status_code == 503
