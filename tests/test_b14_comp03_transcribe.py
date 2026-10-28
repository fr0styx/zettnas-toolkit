"""B14 COMP-03: voice memos (and, when asked, videos) are indexed with their transcripts."""

import io
import json
import math
import os
import struct
import urllib.error
import wave

import pytest

from backend.services import transcribe
from backend.services.rag_engine import RagSearchEngine

CFG = {"transcribe_endpoint": "http://speech:8000/v3", "transcribe_model": "whisper-base"}


def _tone(path, secs=2.0, rate=22050):
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(secs * rate))
    )
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)


def test_off_until_a_server_is_set_and_videos_only_when_asked():
    assert not transcribe.wanted({}, is_video=False)
    assert transcribe.wanted(CFG, is_video=False)
    assert not transcribe.wanted(CFG, is_video=True)
    assert transcribe.wanted({**CFG, "transcribe_video": True}, is_video=True)
    assert transcribe.url_for("http://s/v3") == "http://s/v3/audio/transcriptions"
    assert transcribe.settings({"transcribe_max_minutes": "x"})["max_secs"] == 30 * 60


def test_the_sound_goes_out_as_16k_mono_wav(tmp_path):
    memo = tmp_path / "memo.wav"
    _tone(memo, secs=2.0)
    pieces = list(transcribe.wav_pieces(str(memo), piece_secs=1))
    assert len(pieces) == 2
    with wave.open(io.BytesIO(pieces[0])) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        assert w.getnframes() == 16000
    assert transcribe.duration_secs(str(memo)) == pytest.approx(2.0, abs=0.1)


def test_a_transcript_is_requested_with_the_model(tmp_path, monkeypatch):
    memo = tmp_path / "memo.wav"
    _tone(memo)
    sent = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        sent.append((req.full_url, req.get_header("Content-type"), req.data))
        return Resp(json.dumps({"text": "fix the roof before winter"}).encode())

    monkeypatch.setattr(transcribe.urllib.request, "urlopen", fake_urlopen)
    assert transcribe.transcript(str(memo), CFG, is_video=False) == "fix the roof before winter"
    url, ctype, body = sent[0]
    assert url == "http://speech:8000/v3/audio/transcriptions" and ctype.startswith("multipart/form-data")
    assert b'name="model"\r\n\r\nwhisper-base' in body and b"RIFF" in body


def test_too_long_or_failing_gives_no_transcript(tmp_path, monkeypatch):
    memo = tmp_path / "memo.wav"
    _tone(memo, secs=2.0)
    monkeypatch.setattr(transcribe, "duration_secs", lambda p: 31 * 60.0)
    assert transcribe.transcript(str(memo), CFG, is_video=False) == ""
    monkeypatch.setattr(transcribe, "duration_secs", lambda p: 2.0)

    def down(req, timeout=None):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(transcribe.urllib.request, "urlopen", down)
    assert transcribe.transcript(str(memo), CFG, is_video=False) == ""
    monkeypatch.setattr(transcribe, "duration_secs", lambda p: (_ for _ in ()).throw(OSError("bad file")))
    assert transcribe.transcript(str(memo), CFG, is_video=False) == ""


def test_the_transcript_reaches_the_index(tmp_path, monkeypatch):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    cfg = dict(engine.get_config())
    cfg.update({"respect_standby": False, **CFG})
    monkeypatch.setattr(engine, "get_config", lambda: cfg)
    monkeypatch.setattr(transcribe, "transcript", lambda path, c, is_video: "the plumber comes on Tuesday")
    memo = tmp_path / "Sprachmemo 12.m4a"
    memo.write_bytes(b"\0" * 64)
    st = os.stat(memo)
    engine._index_single_file(
        str(memo), memo.name, ".m4a", st.st_size, st.st_mtime_ns, None, respect_standby=False, force_wake=True
    )
    conn = engine._get_conn()
    try:
        text = " ".join(r[0] for r in conn.execute("SELECT chunk_text FROM document_chunks"))
    finally:
        conn.close()
    assert "plumber comes on Tuesday" in text
