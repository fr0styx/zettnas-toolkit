"""B12b (REL-25): copies and moves are saved, so one cut off by a restart comes back as
"interrupted" with resume, undo and dismiss; each clears only that transfer's unfinished files."""

import json
import os
import threading
import time

import pytest

from backend import config
from backend.services import fs_transfer as ft
from backend.services.jobs import _TRANSFER_STATUS


@pytest.fixture
def root(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    pool.mkdir()
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    monkeypatch.setattr(ft, "TRANSFERS_FILE", str(tmp_path / "transfers.json"))
    return pool


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _wait(manager, task_id):
    for _ in range(200):
        task = manager.get_task(task_id)
        if task and task["status"] not in ("pending", "running", "paused"):
            return task
        time.sleep(0.02)
    raise AssertionError("the transfer did not finish")


def _crashed(root, tmp_path, action="copy", existed=None, **extra):
    """A saved transfer that was running when ZettNAS stopped, loaded by a new manager."""
    rec = {
        "id": "t1",
        "action": action,
        "sources": [str(root / "src" / "album")],
        "destination": str(root / "dst"),
        "collision_policy": "merge",
        "status": "running",
        "owner": "admin",
        "created_at": time.time(),
        "existed": [False] if existed is None else existed,
        **extra,
    }
    (tmp_path / "transfers.json").write_text(json.dumps({"tasks": [rec]}))
    manager = ft.TransferTaskManager()
    assert manager.load_interrupted() == 1
    return manager


def test_a_running_transfer_is_saved_and_comes_back_interrupted(root, tmp_path, monkeypatch):
    _write(root / "src" / "a.txt", "a")
    gate = threading.Event()
    real = ft.execute_transfer

    def held(*args, **kwargs):
        gate.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(ft, "execute_transfer", held)
    manager = ft.TransferTaskManager()
    task = manager.submit_transfer([str(root / "src" / "a.txt")], str(root / "dst"), owner="Admin")
    saved = json.loads((tmp_path / "transfers.json").read_text())["tasks"]
    assert saved[0]["id"] == task.id and saved[0]["status"] in ("pending", "running") and saved[0]["existed"] == [False]

    after_restart = ft.TransferTaskManager()  # ZettNAS started again while it ran
    assert after_restart.load_interrupted() == 1
    back = after_restart.get_task(task.id)
    assert back["status"] == "interrupted" and back["owner"] == "admin" and back["can_undo"] is True
    assert after_restart.load_interrupted() == 0  # loaded once
    assert _TRANSFER_STATUS["interrupted"] == "error"
    gate.set()
    assert _wait(manager, task.id)["status"] == "completed"
    assert json.loads((tmp_path / "transfers.json").read_text())["tasks"][-1]["status"] == "completed"


def test_resume_clears_the_unfinished_file_and_runs_again(root, tmp_path):
    _write(root / "src" / "album" / "a.jpg", "a")
    _write(root / "src" / "album" / "b.jpg", "b")
    _write(root / "dst" / "album" / "a.jpg", "a")
    _write(root / "dst" / "album" / ".b.jpg.zettnas-part", "half")
    manager = _crashed(root, tmp_path)
    new = manager.resume_interrupted("t1")
    assert new is not None and new.id != "t1" and new.owner == "admin"
    assert _wait(manager, new.id)["status"] == "completed"
    assert sorted(os.listdir(root / "dst" / "album")) == ["a.jpg", "b.jpg"]
    assert manager.get_task("t1") is None


def test_a_move_that_had_finished_needs_no_rerun(root, tmp_path):
    _write(root / "dst" / "album" / "a.jpg", "a")  # the source is already gone
    manager = _crashed(root, tmp_path, action="move")
    done = manager.resume_interrupted("t1")
    assert done.id == "t1" and manager.get_task("t1")["status"] == "completed"


def test_undoing_a_copy_puts_the_copies_in_the_recycle_bin(root, tmp_path):
    _write(root / "src" / "album" / "a.jpg", "a")
    _write(root / "dst" / "album" / "a.jpg", "a")
    manager = _crashed(root, tmp_path)
    res = manager.undo_interrupted("t1")
    assert res["binned"] == 1 and not (root / "dst" / "album").exists()
    assert os.listdir(root / ".RecycleBin" / "files")[0].endswith("_album")
    assert (root / "src" / "album" / "a.jpg").exists() and manager.get_task("t1") is None


def test_undo_keeps_what_was_merged_into_an_existing_folder(root, tmp_path):
    _write(root / "src" / "album" / "a.jpg", "a")
    _write(root / "dst" / "album" / "mine.jpg", "was there")
    manager = _crashed(root, tmp_path, existed=[True])
    assert manager.get_task("t1")["can_undo"] is False
    assert manager.undo_interrupted("t1")["kept"] == ["album"]
    assert (root / "dst" / "album" / "mine.jpg").exists()


def test_undo_without_a_bin_removes_only_a_copy_of_a_file_still_there(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path / "elsewhere")])
    monkeypatch.setattr(ft, "TRANSFERS_FILE", str(tmp_path / "transfers.json"))
    base = tmp_path / "pool"
    _write(base / "dst" / "album" / "a.jpg", "a")
    manager = _crashed(base, tmp_path)  # its source is gone: the copy is all there is
    assert manager.undo_interrupted("t1")["kept"] == ["album"] and (base / "dst" / "album").exists()


def test_undoing_a_move_brings_the_items_back(root, tmp_path):
    _write(root / "src" / "album" / "left.jpg", "not moved yet")
    _write(root / "dst" / "album" / "moved.jpg", "moved")
    manager = _crashed(root, tmp_path, action="move")
    res = manager.undo_interrupted("t1")
    [back] = res["tasks"]
    assert _wait(manager, back)["status"] == "completed"
    assert sorted(os.listdir(root / "src" / "album")) == ["left.jpg", "moved.jpg"]
    assert not (root / "dst" / "album").exists()


def test_dismiss_clears_unfinished_files_and_keeps_moved_ones(root, tmp_path):
    _write(root / "dst" / ".album.zettnas-stage-abc123" / "moved.jpg", "only copy")
    _write(root / "dst" / ".album.zettnas-part", "half")
    _write(root / "dst" / "other" / ".x.zettnas-part", "not this transfer's")
    manager = _crashed(root, tmp_path, action="move")
    assert manager.dismiss_interrupted("t1") == {"removed": 1, "kept": 1}
    assert (root / "dst" / "album (incomplete move)" / "moved.jpg").read_text() == "only copy"
    assert (root / "dst" / "other" / ".x.zettnas-part").exists()  # only its own targets are read
    assert manager.dismiss_interrupted("t1") is None


def test_a_copy_stage_and_nested_part_files_are_removed(root, tmp_path):
    _write(root / "dst" / "album" / ".sub.zettnas-stage-abc123" / "x.jpg", "partial copy")
    _write(root / "dst" / "album" / "deep" / ".y.jpg.zettnas-part", "half")
    _write(root / "dst" / "album" / "keep.jpg", "done")
    manager = _crashed(root, tmp_path)
    assert manager.dismiss_interrupted("t1") == {"removed": 2, "kept": 0}
    assert sorted(os.listdir(root / "dst" / "album")) == ["deep", "keep.jpg"]


def test_a_missing_destination_has_nothing_to_sweep(root, tmp_path):
    manager = _crashed(root, tmp_path)
    assert ft.sweep_leftovers(manager._interrupted("t1")) == {"removed": 0, "kept": 0}


def test_damaged_saved_transfers_are_skipped(root, tmp_path):
    (tmp_path / "transfers.json").write_text(json.dumps({"tasks": [{"no": "id"}, {"id": "x", "status": "odd"}]}))
    manager = ft.TransferTaskManager()
    assert manager.load_interrupted() == 0 and manager.get_task("x")["status"] == "failed"
    (tmp_path / "transfers.json").write_text("[1, 2]")
    assert ft.TransferTaskManager().load_interrupted() == 0


def test_only_interrupted_transfers_can_be_undone_or_dismissed(root):
    manager = ft.TransferTaskManager()
    assert manager.resume_interrupted("nope") is None
    assert manager.undo_interrupted("nope") is None
    assert manager.dismiss_interrupted("nope") is None


def test_the_routes(client, auth_headers, root, tmp_path, monkeypatch):
    _write(root / "dst" / "album" / "a.jpg", "a")
    manager = _crashed(root, tmp_path, action="move")
    monkeypatch.setattr(ft, "transfer_manager", manager)
    assert client.post("/api/fs/transfers/nope/undo", headers=auth_headers).status_code == 404
    assert client.post("/api/fs/transfers/nope/dismiss", headers=auth_headers).status_code == 404
    assert client.post("/api/fs/transfers/nope/resume", headers=auth_headers).status_code == 404
    res = client.post("/api/fs/transfers/t1/resume", headers=auth_headers).json()
    assert res["resumed"] and res["task"]["status"] == "completed"
    manager = _crashed(root, tmp_path, action="move")
    monkeypatch.setattr(ft, "transfer_manager", manager)
    assert client.post("/api/fs/transfers/t1/dismiss", headers=auth_headers).json()["status"] == "ok"
    manager = _crashed(root, tmp_path, action="copy")
    monkeypatch.setattr(ft, "transfer_manager", manager)
    assert client.post("/api/fs/transfers/t1/undo", headers=auth_headers).json()["binned"] == 1
