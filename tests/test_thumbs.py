"""Thumbnails for the explorer: photos, HEIC, video frames, the disk cache and the endpoint."""

import io
import os
from unittest.mock import patch

import pytest
from PIL import Image

from backend.services import thumbs


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETTNAS_THUMB_CACHE_DIR", str(tmp_path / "cache"))


def _webp_size(data):
    im = Image.open(io.BytesIO(data))
    assert im.format == "WEBP"
    return im.size


def _video(path, w=320, h=240, frames=30):
    import av

    with av.open(str(path), "w") as out:
        st = out.add_stream("mpeg4", rate=10)
        st.width, st.height, st.pix_fmt = w, h, "yuv420p"
        for i in range(frames):
            img = Image.new("RGB", (w, h), (min(255, i * 8), 80, 160))
            for packet in st.encode(av.VideoFrame.from_image(img)):
                out.mux(packet)
        for packet in st.encode():
            out.mux(packet)


def test_photo_thumbnail_is_small_and_cached(tmp_path):
    src = tmp_path / "IMG_1.jpg"
    Image.new("RGB", (4000, 3000), (200, 30, 30)).save(src, quality=90)
    data = thumbs.get(str(src))
    assert max(_webp_size(data)) == 256
    with patch.object(thumbs, "render", side_effect=AssertionError("should come from the cache")):
        assert thumbs.get(str(src)) == data
    # an edited file gets a fresh thumbnail
    Image.new("RGB", (1000, 2000), (0, 0, 0)).save(src)
    os.utime(src, (1, 1_900_000_000))
    assert _webp_size(thumbs.get(str(src))) == (128, 256)


def test_heic_thumbnail(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    if not pillow_heif.libheif_info().get("HEIF"):
        pytest.skip("no HEIF encoder in this build")
    pillow_heif.register_heif_opener()
    src = tmp_path / "IMG_7149.HEIC"
    Image.new("RGB", (1200, 1600), (10, 120, 90)).save(src, format="HEIF")
    assert _webp_size(thumbs.get(str(src))) == (192, 256)


def test_video_thumbnail_is_a_frame(tmp_path):
    pytest.importorskip("av")
    src = tmp_path / "clip.mov"
    _video(src)
    data = thumbs.get(str(src))
    assert _webp_size(data) == (256, 192)
    assert thumbs.kind("a/IMG_0843.MOV") == "video"
    assert thumbs.kind("a/notes.txt") is None


def test_broken_file_is_not_retried(tmp_path):
    src = tmp_path / "broken.mp4"
    src.write_bytes(b"not a video")
    assert thumbs.get(str(src)) is None
    with patch.object(thumbs, "render", side_effect=AssertionError("failure should be remembered")):
        assert thumbs.get(str(src)) is None


def test_cache_is_trimmed_oldest_first(tmp_path):
    d = tmp_path / "cache" / "ab"
    d.mkdir(parents=True)
    for i in range(10):
        p = d / f"{i:02d}.webp"
        p.write_bytes(b"x" * 1000)
        os.utime(p, (1000 + i, 1000 + i))
    freed = thumbs.prune(limit=5000)
    left = sorted(os.listdir(d))
    assert freed == 6000
    assert left == ["06.webp", "07.webp", "08.webp", "09.webp"]


def test_endpoint(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    root.mkdir()
    Image.new("RGB", (800, 600), (1, 2, 3)).save(root / "a.png")
    (root / "song.mp3").write_bytes(b"ID3" + b"\0" * 2000)
    (root / "broken.mov").write_bytes(b"nope")
    with patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)]):
        r = client.get("/api/fs/preview/image", params={"path": str(root / "a.png"), "thumb": 1}, headers=auth_headers)
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
        assert r.headers["cache-control"].startswith("private")
        r = client.get(
            "/api/fs/preview/image", params={"path": str(root / "a.png"), "max_dim": 400}, headers=auth_headers
        )
        assert _webp_size(r.content) == (400, 300)
        # no thumbnail: say so instead of sending the whole file into an <img>
        r = client.get(
            "/api/fs/preview/image", params={"path": str(root / "song.mp3"), "thumb": 1}, headers=auth_headers
        )
        assert r.status_code == 415
        r = client.get(
            "/api/fs/preview/image", params={"path": str(root / "broken.mov"), "thumb": 1}, headers=auth_headers
        )
        assert r.status_code == 415
