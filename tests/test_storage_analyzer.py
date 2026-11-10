"""Storage analyzer: where a share's space goes, by folder, file and kind; started on request."""

import os
import threading
import time

import pytest

from backend.services import storage_analyzer as sa


def _file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_it_adds_up_folders_files_and_kinds(tmp_path):
    _file(tmp_path / "Movies" / "a.mkv", 5000)
    _file(tmp_path / "Movies" / "Old" / "b.mp4", 3000)
    _file(tmp_path / "Photos" / "2024" / "c.jpg", 700)
    _file(tmp_path / "notes.txt", 10)
    _file(tmp_path / ".zfs" / "snapshot" / "x.bin", 9999)  # snapshots aren't the share's files
    os.symlink(tmp_path / "Movies", tmp_path / "link")  # links are not followed
    r = sa.analyze(str(tmp_path))
    assert r["complete"] and r["files"] == 4 and r["bytes"] == 8710
    folders = {f["path"]: f["bytes"] for f in r["folders"]}
    assert folders["Movies"] == 8000 and folders["Movies/Old"] == 3000 and folders["Photos/2024"] == 700
    assert r["largest"][0] == {"path": "Movies/a.mkv", "bytes": 5000}
    assert r["kinds"]["video"] == {"bytes": 8000, "files": 2}
    assert r["kinds"]["photo"]["files"] == 1 and r["kinds"]["document"]["files"] == 1
    assert sa.kind_of("README") == "other" and sa.kind_of("x.ISO") == "disk_image"


def test_cancelling_stops_it_and_says_so(tmp_path):
    _file(tmp_path / "a" / "b.bin", 10)
    stop = threading.Event()
    stop.set()
    r = sa.analyze(str(tmp_path), cancel=stop)
    assert r["complete"] is False


def test_the_api_starts_one_job_per_share_and_keeps_the_result(client, auth_headers, tmp_path, monkeypatch):
    _file(tmp_path / "Media" / "film.mkv", 1234)
    monkeypatch.setattr(sa, "RESULT_DIR", str(tmp_path / "results"))
    from backend.api import storage as storage_api

    monkeypatch.setattr(storage_api, "_share_root", lambda name: str(tmp_path) if name == "media" else None)
    assert client.post("/api/storage/analysis", json={"share": "nope"}, headers=auth_headers).status_code == 404
    r = client.post("/api/storage/analysis", json={"share": "media"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["job_id"].startswith("job:")
    deadline = time.time() + 10
    while time.time() < deadline:
        got = client.get("/api/storage/analysis/media", headers=auth_headers).json()
        if got["result"] and not got["running"]:
            break
        time.sleep(0.05)
    assert got["result"]["bytes"] == 1234 and got["result"]["share"] == "media"
    jobs = client.get("/api/jobs", headers=auth_headers).json()
    assert any(j["kind"] == "storage_analysis" and j["status"] == "done" for j in jobs["history"])


def test_a_second_start_while_running_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(sa, "RESULT_DIR", str(tmp_path / "results"))
    gate = threading.Event()
    monkeypatch.setattr(sa, "analyze", lambda root, cancel, progress: (gate.wait(5), {"complete": True})[1])
    sa.start("busy", str(tmp_path))
    with pytest.raises(RuntimeError):
        sa.start("busy", str(tmp_path))
    gate.set()
    deadline = time.time() + 5
    while sa.running("busy") and time.time() < deadline:
        time.sleep(0.02)
    assert not sa.running("busy")
