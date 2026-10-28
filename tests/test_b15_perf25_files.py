"""B15 PERF-25: file search that never wakes a sleeping disk, gzipped JSON, paged listings and
capped folder sizes."""

import gzip
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.api.files import details, search


@pytest.fixture(autouse=True)
def _empty_search_cache():
    search._SEARCH_CACHE.clear()
    yield
    search._SEARCH_CACHE.clear()


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "share"
    (root / "docs").mkdir(parents=True)
    for i in range(5):
        (root / "docs" / f"report_{i}.txt").write_text("x")
    (root / "other.txt").write_text("y")
    (root / ".hidden_report.txt").write_text("z")
    return root


def _index_with(tmp_path, rows):
    db = tmp_path / "index.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE indexed_files (canonical_path TEXT, parent_dir TEXT, file_name TEXT, size_bytes INTEGER,"
        " mtime_ns INTEGER)"
    )
    conn.executemany(
        "INSERT INTO indexed_files VALUES (?, ?, ?, ?, ?)",
        [(p, os.path.dirname(p), os.path.basename(p), 10, 2_000_000_000) for p in rows],
    )
    conn.commit()
    conn.close()
    return SimpleNamespace(db_path=str(db), _get_conn=lambda readonly=False: sqlite3.connect(db))


def _allow_all():
    return patch.object(search, "user_can_access_path", lambda *a, **k: True)


def test_an_awake_disk_is_walked(tree):
    with _allow_all(), patch.object(search, "_asleep", lambda root: False):
        found, partial = search._search([str(tree)], "report", True, None)
    assert sorted(i["name"] for i in found) == [f"report_{i}.txt" for i in range(5)]  # hidden left out
    assert partial is None


def test_a_sleeping_disk_is_answered_from_the_index_without_touching_it(tree, tmp_path):
    engine = _index_with(
        tmp_path,
        [f"{tree}/docs/report_9.txt", f"{tree}/.cache/report_x.txt", f"{tmp_path}/elsewhere/report_y.txt"],
    )

    def no_disk(*_a, **_k):
        raise AssertionError("the sleeping disk was read")

    with (
        _allow_all(),
        patch.object(search, "_asleep", lambda root: True),
        patch("backend.services.rag_engine._RAG_ENGINE", engine),
        patch.object(search.os, "scandir", no_disk),
    ):
        found, partial = search._search([str(tree)], "REPORT".lower(), True, None)
    assert [i["path"] for i in found] == [f"{tree}/docs/report_9.txt"]  # hidden and outside left out
    assert partial == "asleep"


def test_without_an_index_a_sleeping_disk_gives_nothing_rather_than_waking(tree):
    with (
        _allow_all(),
        patch.object(search, "_asleep", lambda root: True),
        patch("backend.services.rag_engine._RAG_ENGINE", None),
    ):
        assert search._search([str(tree)], "report", True, None) == ([], "asleep")


def test_a_capped_walk_says_so_and_the_index_fills_in(tree, tmp_path):
    engine = _index_with(tmp_path, [f"{tree}/deep/report_far.txt"])
    with (
        _allow_all(),
        patch.object(search, "_asleep", lambda root: False),
        patch.object(search, "MAX_SCANNED", 2),
        patch("backend.services.rag_engine._RAG_ENGINE", engine),
    ):
        found, partial = search._search([str(tree)], "report", True, None)
    assert partial == "capped"
    assert f"{tree}/deep/report_far.txt" in [i["path"] for i in found]


def test_later_pages_reuse_the_first_walk(client, auth_headers, tree):
    walks = []
    real = search._search

    def counting(*a):
        walks.append(1)
        return real(*a)

    with (
        patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(tree)]),
        _allow_all(),
        patch.object(search, "_asleep", lambda root: False),
        patch.object(search, "_search", counting),
    ):
        first = client.get(f"/api/fs/search?q=report&path={tree}&limit=2", headers=auth_headers).json()
        second = client.get(f"/api/fs/search?q=report&path={tree}&limit=2&offset=2", headers=auth_headers).json()
        again = client.get(f"/api/fs/search?q=report&path={tree}&limit=2", headers=auth_headers).json()
    assert first["total"] == second["total"] == 5
    assert {i["name"] for i in first["items"]}.isdisjoint(i["name"] for i in second["items"])
    assert first["partial"] is None
    assert len(walks) == 2  # page 2 came from memory; a new first page searched again
    assert again["total"] == 5


def test_json_answers_are_gzipped_and_streams_are_not():
    import asyncio

    from backend.auth import JsonGzip

    async def run(content_type, body, accept=b"gzip, br"):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", content_type)]})
            await send({"type": "http.response.body", "body": body[:10], "more_body": True})
            await send({"type": "http.response.body", "body": body[10:]})

        sent = []

        async def send(m):
            sent.append(m)

        scope = {"type": "http", "method": "GET", "headers": [(b"accept-encoding", accept)]}
        await JsonGzip(app)(scope, None, send)
        return sent

    big = b'{"items": [' + b'"a",' * 600 + b'"b"]}'
    sent = asyncio.run(run(b"application/json", big))
    headers = dict(sent[0]["headers"])
    assert headers[b"content-encoding"] == b"gzip"
    assert gzip.decompress(sent[1]["body"]) == big
    assert int(headers[b"content-length"]) == len(sent[1]["body"])

    small = asyncio.run(run(b"application/json", b'{"ok": true, "pad": "................"}'))
    assert b"content-encoding" not in dict(small[0]["headers"])

    stream = asyncio.run(run(b"text/event-stream", big))
    assert len(stream) == 3 and stream[1]["more_body"] is True  # passed straight through, unbuffered

    plain = asyncio.run(run(b"application/json", big, accept=b"identity"))
    assert len(plain) == 3


def test_listing_pages_only_when_asked(client, auth_headers, tree):
    with patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(tree)]):
        whole = client.get(f"/api/browse?path={tree}/docs", headers=auth_headers)
        page = client.get(f"/api/browse?path={tree}/docs&limit=2&offset=1", headers=auth_headers)
    assert whole.status_code == 200 and page.status_code == 200
    assert "total" not in whole.json()
    assert page.json()["total"] == len(whole.json()["dirs"])
    assert page.json()["dirs"] == whole.json()["dirs"][1:3]


def test_a_huge_folder_size_stops_and_says_at_least(client, auth_headers, tree):
    details._FOLDER_SIZE_CACHE.clear()
    with (
        patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(tree)]),
        patch.object(details, "FOLDER_SIZE_MAX_ENTRIES", 2),
        patch("backend.services.rag_standby.is_backing_disk_in_standby", lambda *a, **k: False),
    ):
        r = client.post("/api/fs/folder-size", json={"path": str(tree)}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["at_least"] is True
    assert str(tree) not in details._FOLDER_SIZE_CACHE  # a partial count is not remembered
    details._FOLDER_SIZE_CACHE.clear()
