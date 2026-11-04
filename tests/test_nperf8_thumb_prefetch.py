"""NPERF-8: photo and video thumbnails made ahead of time, by folder and in the background."""

import os
import sqlite3
import types

import pytest

from backend.services import thumb_prefetch, thumbs


@pytest.fixture(autouse=True)
def _empty_queue():
    thumb_prefetch._queue.clear()
    thumb_prefetch._queued.clear()
    yield
    thumb_prefetch._queue.clear()
    thumb_prefetch._queued.clear()


def _touch(folder, *names):
    for n in names:
        (folder / n).write_bytes(b"x")


def test_a_folder_lists_its_photos_and_videos_by_name(tmp_path):
    _touch(tmp_path, "b.mov", "a.HEIC", "notes.txt", ".hidden.jpg", "c.jpg")
    (tmp_path / "sub.jpg").mkdir()
    assert thumb_prefetch.folder_media(str(tmp_path)) == [str(tmp_path / n) for n in ("a.HEIC", "b.mov", "c.jpg")]
    assert thumb_prefetch.folder_media(str(tmp_path / "missing")) == []


def test_an_open_encrypted_folder_is_never_queued(monkeypatch, tmp_path):
    _touch(tmp_path, "a.jpg")
    monkeypatch.setattr(thumb_prefetch, "_encrypted", lambda p: True)
    assert thumb_prefetch.folder_media(str(tmp_path)) == []


def test_the_folder_just_opened_goes_first_and_nothing_twice(monkeypatch, tmp_path):
    monkeypatch.setattr(thumb_prefetch, "_ensure_worker", lambda: None)
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    _touch(one, "a.jpg", "b.mp4")
    _touch(two, "c.jpg")
    assert thumb_prefetch.queue_folder(str(one)) == 2
    assert thumb_prefetch.queue_folder(str(two)) == 1
    assert thumb_prefetch.queue_folder(str(one)) == 0  # already waiting
    assert list(thumb_prefetch._queue) == [str(two / "c.jpg"), str(one / "a.jpg"), str(one / "b.mp4")]


def test_the_queue_keeps_its_newest_entries_when_full(monkeypatch, tmp_path):
    monkeypatch.setattr(thumb_prefetch, "_ensure_worker", lambda: None)
    monkeypatch.setattr(thumb_prefetch, "MAX_QUEUE", 2)
    _touch(tmp_path, "a.jpg", "b.jpg", "c.jpg")
    assert thumb_prefetch.queue_folder(str(tmp_path)) == 2
    assert len(thumb_prefetch._queue) == 2 and len(thumb_prefetch._queued) == 2


def test_draining_makes_only_the_missing_thumbnails(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(thumbs, "cached", lambda p: p.endswith("a.jpg"))
    monkeypatch.setattr(thumbs, "get", lambda p, **kw: made.append(p) or b"webp")
    _touch(tmp_path, "a.jpg", "b.mov")
    thumb_prefetch.queue_folder(str(tmp_path))
    for w in list(thumb_prefetch._workers):
        w.join(5)
    assert made == [str(tmp_path / "b.mov")]
    assert not thumb_prefetch._queue and not thumb_prefetch._queued


def test_a_file_that_is_gone_or_broken_makes_nothing(monkeypatch):
    def gone(p):
        raise FileNotFoundError(p)

    monkeypatch.setattr(thumbs, "cached", gone)
    assert thumb_prefetch.make("/nope.jpg") is False
    monkeypatch.setattr(thumbs, "cached", lambda p: False)
    monkeypatch.setattr(thumbs, "get", lambda p, **kw: None)
    assert thumb_prefetch.make("/broken.jpg") is False


class _Engine:
    def __init__(self, path, rows):
        self.path = path
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE indexed_files (file_id INTEGER PRIMARY KEY, canonical_path TEXT, modality TEXT,"
            " parse_status TEXT, backing_dev TEXT)"
        )
        conn.executemany("INSERT INTO indexed_files VALUES (?, ?, ?, ?, ?)", rows)
        conn.commit()
        conn.close()

    def _get_conn(self):
        return sqlite3.connect(self.path)


def _backfill(tmp_path, monkeypatch, rows, idle=lambda: True):
    made = []
    monkeypatch.setattr(thumb_prefetch, "make", lambda p: made.append(p) or True)
    monkeypatch.setattr(thumb_prefetch, "_encrypted", lambda p: p.startswith("/mnt/encrypted/"))
    bf = thumb_prefetch.Backfill(
        _Engine(str(tmp_path / "idx.db"), rows), idle, asleep=lambda dev: dev == "sdc", workers=1
    )
    return bf, made


def test_the_backfill_makes_photos_and_videos_on_awake_disks_only(tmp_path, monkeypatch):
    rows = [
        (1, "/mnt/user/p/a.jpg", "image", "ok", "sdb"),
        (2, "/mnt/user/p/b.mov", "video", "ok", "sdb"),
        (3, "/mnt/user/p/c.pdf", "document", "ok", "sdb"),
        (4, "/mnt/user/p/d.jpg", "image", "ok", "sdc"),
        (5, "/mnt/user/p/e.jpg", "image", "error", "sdb"),
        (6, "/mnt/encrypted/f.jpg", "image", "ok", "sdb"),
    ]
    bf, made = _backfill(tmp_path, monkeypatch, rows)
    assert bf.step() == "more"
    assert made == ["/mnt/user/p/a.jpg", "/mnt/user/p/b.mov"]
    assert (bf.cursor, bf.made, bf.deferred) == (6, 2, 1)
    assert bf.step() == "done"
    assert (bf.cursor, bf.made, bf.deferred) == (0, 0, 0)  # the next pass starts over


def test_the_backfill_waits_while_the_system_is_busy(tmp_path, monkeypatch):
    rows = [(i, f"/mnt/user/p/{i}.jpg", "image", "ok", "sdb") for i in range(1, 26)]
    answers = iter([True] + [False] * 5)
    bf, made = _backfill(tmp_path, monkeypatch, rows, idle=lambda: next(answers, False))
    assert bf.step() == "busy"  # checked again after 20 files
    assert len(made) == 20 and bf.cursor == 20
    assert bf.step() == "busy" and len(made) == 20


def test_the_backfill_loop_pauses_by_state(monkeypatch):
    bf = thumb_prefetch.Backfill(None, lambda: True)
    states = iter(["more", "busy", "done"])

    def step():
        state = next(states, None)
        if state is None:
            raise sqlite3.OperationalError("locked")
        return state

    bf.step = step
    pauses = []

    def sleep(s):
        pauses.append(s)
        if len(pauses) == 4:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        bf.run_forever(sleep)
    assert pauses == [
        thumb_prefetch.STEP_PAUSE_S,
        thumb_prefetch.BUSY_PAUSE_S,
        thumb_prefetch.PASS_PAUSE_S,
        thumb_prefetch.BUSY_PAUSE_S,
    ]


def test_cached_sees_a_thumbnail_or_a_failure_note(monkeypatch, tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    hit, fail = tmp_path / "h.webp", tmp_path / "h.fail"
    monkeypatch.setattr(thumbs, "_paths", lambda key: (str(hit), str(fail)))
    assert thumbs.cached(str(src)) is False
    fail.write_bytes(b"")
    assert thumbs.cached(str(src)) is True


def test_the_cache_is_walked_only_when_it_may_be_full(monkeypatch, tmp_path):
    monkeypatch.setenv("ZETTNAS_THUMB_CACHE_DIR", str(tmp_path))
    walks = []
    monkeypatch.setattr(
        thumbs.threading, "Thread", lambda target, **kw: types.SimpleNamespace(start=lambda: walks.append(1))
    )
    monkeypatch.setattr(thumbs, "cache_limit_bytes", lambda: 1000)
    monkeypatch.setattr(thumbs, "_approx_bytes", None)
    assert thumbs.prune() == 0 and thumbs._approx_bytes == 0  # first walk: the count starts
    monkeypatch.setattr(thumbs, "_writes", 1)
    for i in range(3):
        thumbs._store(str(tmp_path / "ab" / f"{i}.webp"), b"x" * 100)
    assert walks == [] and thumbs._approx_bytes == 300
    thumbs._store(str(tmp_path / "ab" / "big.webp"), b"x" * 800)
    assert walks == [1]  # over the limit now
    (tmp_path / "ab" / "old.webp").write_bytes(b"y" * 10)
    os.utime(tmp_path / "ab" / "old.webp", (1, 1))
    freed = thumbs.prune()
    assert freed > 0 and thumbs._approx_bytes <= 800


def test_encode_makes_a_small_webp():
    from PIL import Image

    data = thumbs.encode(Image.new("P", (600, 300)), 256)
    with Image.open(__import__("io").BytesIO(data)) as im:
        assert im.format == "WEBP" and max(im.size) == 256


def test_a_versioned_thumbnail_is_kept_for_a_year_and_folders_can_be_queued(client, auth_headers, monkeypatch):
    from PIL import Image

    pool = os.environ["POOL_PATH"]
    folder = os.path.join(pool, "nperf8")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "a.jpg")
    Image.new("RGB", (40, 30), (10, 200, 30)).save(path)
    queued = []
    monkeypatch.setattr(thumb_prefetch, "queue_folder", lambda p: queued.append(p) or 1)
    try:
        r = client.get("/api/fs/preview/image", params={"path": path, "thumb": 1, "v": "123"}, headers=auth_headers)
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        r = client.get("/api/fs/preview/image", params={"path": path, "thumb": 1}, headers=auth_headers)
        assert "max-age=86400" in r.headers["cache-control"]
        r = client.post("/api/fs/thumbs/prefetch", json={"path": folder}, headers=auth_headers)
        assert r.status_code == 200 and r.json() == {"status": "ok", "queued": 1}
        assert queued and os.path.realpath(queued[0]) == os.path.realpath(folder)
        r = client.post("/api/fs/thumbs/prefetch", json={"path": path}, headers=auth_headers)
        assert r.status_code == 400
    finally:
        os.remove(path)
        os.rmdir(folder)


def test_work_made_ahead_waits_for_thumbnails_on_screen(monkeypatch):
    import threading
    import time

    monkeypatch.setattr(thumbs, "SCREEN_WAIT_S", 2.0)
    order = []
    started = threading.Event()

    def render(path, limit):
        if path == "screen":
            started.set()
            time.sleep(0.3)
        order.append(path)
        return b"x"

    monkeypatch.setattr(thumbs, "render", render)
    on_screen = threading.Thread(target=lambda: thumbs._render_for("screen", 256, False))
    on_screen.start()
    started.wait(2)
    thumbs._render_for("ahead", 256, True)
    on_screen.join()
    assert order == ["screen", "ahead"] and thumbs._on_screen == 0
