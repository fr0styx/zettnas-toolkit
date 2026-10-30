"""NARC-9: what an unfinished chunked upload leaves in a share is noted in the data folder and
removed after a restart or a day, never from a sleeping disk."""

import os

import pytest

from backend.services import upload_staging as us


@pytest.fixture
def index(tmp_path, monkeypatch):
    monkeypatch.setattr(us, "INDEX", str(tmp_path / "upload_staging.json"))
    monkeypatch.setattr(us, "_asleep", lambda p: False)
    return tmp_path


def _parts(root, uid):
    staging = root / f".zettnas_staging_{uid}_a.bin"
    staging.mkdir()
    (staging / "chunk_000000").write_bytes(b"x")
    temp = root / f".zettnas_tmp_{uid}_a.bin"
    temp.write_bytes(b"y")
    return str(staging), str(temp)


def test_left_from_before_a_restart_is_removed(index, monkeypatch):
    s, t = _parts(index, "old")
    us.note("old", [s, t], now=us.PROCESS_START - 10)
    s2, t2 = _parts(index, "live")
    us.note("live", [s2, t2], now=us.PROCESS_START + 5)
    assert us.sweep(now=us.PROCESS_START + 60, force=True) == ["old"]
    assert not os.path.exists(s) and not os.path.exists(t)
    assert os.path.exists(s2) and os.path.exists(t2)  # still going on
    assert us.sweep(now=us.PROCESS_START + 5 + us.TTL_S + 1, force=True) == ["live"]  # a day old


def test_a_finished_upload_is_forgotten(index):
    s, t = _parts(index, "done")
    us.note("done", [s, t])
    us.forget("done")
    us.forget("never")
    assert us.sweep(now=us.PROCESS_START + us.TTL_S * 2, force=True) == []
    assert os.path.exists(s)  # nothing noted: nothing touched


def test_sleeping_disks_and_other_files_are_left(index, monkeypatch):
    s, t = _parts(index, "zz")
    other = index / "photo.jpg"
    other.write_bytes(b"z")
    us.note("zz", [s, t, str(other)], now=us.PROCESS_START - 10)
    monkeypatch.setattr(us, "_asleep", lambda p: True)
    assert us.sweep(now=us.PROCESS_START + 60, force=True) == []
    monkeypatch.setattr(us, "_asleep", lambda p: False)
    assert us.sweep(now=us.PROCESS_START + 60, force=True) == ["zz"]
    assert other.exists()  # only the upload's own .zettnas_ parts go


def test_the_sweep_runs_at_most_hourly(index, monkeypatch):
    monkeypatch.setattr(us, "_last_sweep", [0.0])
    assert us.sweep(now=10_000) == [] and us._last_sweep[0] == 10_000
    us.note("x", [], now=0)
    assert us.sweep(now=10_100) == []  # too soon
    assert us.sweep(now=10_000 + us.SWEEP_EVERY_S) == ["x"]


def test_the_api_notes_and_forgets(client, auth_headers, index, monkeypatch, tmp_path):
    from backend import config

    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path)])
    monkeypatch.setattr("backend.api.files.uploads.ALLOWED_BROWSE_ROOTS", [str(tmp_path)])
    r = client.post(
        "/api/fs/upload/init", headers=auth_headers, json={"path": str(share), "filename": "a.bin", "total_size": 3}
    )
    assert r.status_code == 200, r.text
    uid = r.json()["upload_id"]
    assert uid in us._load()
    assert (
        client.post(
            f"/api/fs/upload/chunk?upload_id={uid}&chunk_index=0", headers=auth_headers, content=b"abc"
        ).status_code
        == 200
    )
    done = client.post("/api/fs/upload/complete", headers=auth_headers, json={"upload_id": uid})
    assert done.status_code == 200, done.text
    assert uid not in us._load() and (share / "a.bin").read_bytes() == b"abc"


def test_the_sleep_check_asks_about_the_folder(monkeypatch):
    seen = []
    monkeypatch.setattr("backend.services.rag_standby.is_backing_disk_in_standby", lambda p: seen.append(p) or True)
    assert us._asleep("/mnt/user/photos/.zettnas_tmp_x") is True and seen == ["/mnt/user/photos"]

    def broken(p):
        raise OSError("no")

    monkeypatch.setattr("backend.services.rag_standby.is_backing_disk_in_standby", broken)
    assert us._asleep("/mnt/user/photos/x") is False


def test_a_part_that_cant_be_removed_is_tried_again(index, monkeypatch):
    s, t = _parts(index, "stuck")
    us.note("stuck", [s, t], now=us.PROCESS_START - 10)

    def refuse(path):
        raise OSError("busy")

    monkeypatch.setattr(us, "_remove", refuse)
    assert us.sweep(now=us.PROCESS_START + 60, force=True) == []
    assert "stuck" in us._load()


def test_the_scheduler_runs_it(monkeypatch):
    from backend.services import scheduler

    calls = []
    monkeypatch.setattr(us, "sweep", lambda now: calls.append(now))
    scheduler._run_upload_sweep(5.0)

    def broken(now):
        raise OSError("disk gone")

    monkeypatch.setattr(us, "sweep", broken)
    scheduler._run_upload_sweep(6.0)  # logged, not raised
    assert calls == [5.0]
