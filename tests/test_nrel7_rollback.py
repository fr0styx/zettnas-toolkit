"""NREL-7: a rollback keeps the Recycle Bin and encrypted folders, refuses when it would harm,
and copies in a job."""

import time

import pytest

from backend.fsutil import ENCRYPTED_HIDDEN
from backend.services import snapshot_service as snaps
from tests.test_b12a_snapshots_default import FakePal  # noqa: F401  (the same stand-in pool)


@pytest.fixture
def pal(tmp_path, monkeypatch):
    p = FakePal(tmp_path)
    monkeypatch.setattr(snaps, "_pal", lambda: p)
    monkeypatch.setattr(snaps, "SCHEDULES_FILE", str(tmp_path / "schedules.json"))
    monkeypatch.setattr(snaps, "_set_previous_versions", lambda share, on: None)
    monkeypatch.setattr("backend.services.encrypted_folders.listing", lambda: [])
    return p


def _setup(pal):
    (pal.live / "a.jpg").write_text("old a")
    (pal.live / ".RecycleBin").mkdir()
    (pal.live / ENCRYPTED_HIDDEN).mkdir()
    (pal.live / ENCRYPTED_HIDDEN / "old-cipher").write_text("x")
    pal.create_snapshot("tank", "photos", "photos@auto-20261027-1000")
    (pal.live / "a.jpg").write_text("new a")
    (pal.live / ".RecycleBin" / "deleted-today.jpg").write_text("keep me")
    (pal.live / ENCRYPTED_HIDDEN / "new-cipher").write_text("keep me too")


def test_the_bin_and_encrypted_folders_stay(pal):
    _setup(pal)
    snaps.rollback("photos@auto-20261027-1000", pal=pal, pool_id="tank")
    assert (pal.live / "a.jpg").read_text() == "old a"
    assert (pal.live / ".RecycleBin" / "deleted-today.jpg").read_text() == "keep me"
    assert (pal.live / ENCRYPTED_HIDDEN / "new-cipher").read_text() == "keep me too"


def test_refuses_with_an_encrypted_folder_open(pal, monkeypatch):
    _setup(pal)
    monkeypatch.setattr(
        "backend.services.encrypted_folders.listing",
        lambda: [
            {"name": "Taxes", "share": "photos", "unlocked": True},
            {"name": "x", "share": "other", "unlocked": True},
        ],
    )
    with pytest.raises(RuntimeError, match="Lock the encrypted folders.*Taxes.*nothing was changed"):
        snaps.rollback("photos@auto-20261027-1000", pal=pal, pool_id="tank")
    assert (pal.live / "a.jpg").read_text() == "new a" and len(pal.created) == 1  # no safety snapshot either


def test_refuses_without_room_for_the_copy(pal, monkeypatch):
    _setup(pal)

    class Usage:
        free = 3

    monkeypatch.setattr(snaps.shutil, "disk_usage", lambda p: Usage)
    with pytest.raises(RuntimeError, match="Not enough free space"):
        snaps.rollback("photos@auto-20261027-1000", pal=pal, pool_id="tank")
    assert (pal.live / "a.jpg").read_text() == "new a"


def test_in_the_background_it_is_a_job(pal):
    from backend.services.jobs import job_manager

    _setup(pal)
    (pal.live / "album").mkdir()
    res = snaps.rollback("photos@auto-20261027-1000", pal=pal, pool_id="tank", owner="ana", background=True)
    assert res["job_id"].startswith("job:") and res["safety_snapshot"].startswith("photos@before-rollback-")
    for _ in range(200):
        done = [j for j in job_manager.list(everyone=True)["history"] if j["id"] == res["job_id"]]
        if done:
            break
        time.sleep(0.02)
    assert done and done[0]["status"] == "done" and done[0]["title_id"] == "jobs.t.rollback"
    assert (pal.live / "a.jpg").read_text() == "old a" and not (pal.live / "album").exists()


def test_a_failed_copy_ends_the_job_with_its_error(pal, monkeypatch):
    from backend.services.jobs import job_manager

    _setup(pal)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(snaps.shutil, "copy2", boom)
    res = snaps.rollback("photos@auto-20261027-1000", pal=pal, pool_id="tank", background=True)
    for _ in range(200):
        done = [j for j in job_manager.list(everyone=True)["history"] if j["id"] == res["job_id"]]
        if done:
            break
        time.sleep(0.02)
    assert done and done[0]["status"] == "error" and "disk full" in done[0]["error"]
