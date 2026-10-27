"""B12a (REL-21): a damaged settings file comes back from the data snapshots; a file that only
can't be opened is reported, left as it is, and never overwritten."""

import builtins
import json
import os

import pytest

from backend import fsutil
from backend.services import data_health


@pytest.fixture
def data(tmp_path, monkeypatch):
    from backend import config

    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", str(folder))
    monkeypatch.setattr(fsutil, "RESTORERS", [data_health.restore_json])
    monkeypatch.setattr(fsutil, "_UNREADABLE", set())
    return folder


def _snapshot(folder, name, content, stamp="20261026-030000-daily"):
    snap = folder / "backups" / "daily" / stamp
    snap.mkdir(parents=True, exist_ok=True)
    (snap / name).write_text(content)


def test_a_damaged_file_comes_back_from_the_newest_good_snapshot(data):
    _snapshot(data, "fans.json", json.dumps({"curve": "old"}), "20261025-030000-daily")
    _snapshot(data, "fans.json", json.dumps({"curve": "quiet"}), "20261026-030000-daily")
    _snapshot(data, "fans.json", "{broken", "20261027-030000-daily")  # newest, but damaged too
    (data / "fans.json").write_text("{not json")
    assert fsutil.read_json(str(data / "fans.json"), {}) == {"curve": "quiet"}
    assert any(n.startswith("fans.json.corrupt-") for n in os.listdir(data))  # the damaged one is kept


def test_without_a_snapshot_the_defaults_are_used(data):
    (data / "led.json").write_text("{not json")
    assert fsutil.read_json(str(data / "led.json"), {"on": True}) == {"on": True}


def test_files_outside_the_data_folder_are_not_restored(data, tmp_path):
    other = tmp_path / "elsewhere.json"
    other.write_text("{x")
    assert data_health.restore_json(str(other)) is False


def _cannot_open(monkeypatch, target):
    real_open = builtins.open

    def fake_open(path, *a, **k):
        if os.path.abspath(str(path)) == os.path.abspath(str(target)):
            raise PermissionError(13, "Permission denied")
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)


def test_a_file_that_cannot_be_opened_is_reported_and_not_overwritten(data, monkeypatch):
    target = data / "users-prefs.json"
    target.write_text(json.dumps({"precious": True}))
    seen = []
    monkeypatch.setattr(fsutil, "UNREADABLE_LISTENERS", [lambda path, err: seen.append(err)])
    _cannot_open(monkeypatch, target)
    assert fsutil.read_json(str(target), {"default": 1}) == {"default": 1}
    assert seen and "Permission denied" in seen[0]
    assert not any(".corrupt-" in n for n in os.listdir(data))  # not treated as damaged
    with pytest.raises(OSError, match="not overwritten"):
        fsutil.atomic_write_json(str(target), {"precious": False})
    monkeypatch.undo()
    assert json.loads(target.read_text()) == {"precious": True}  # still there


def test_once_it_can_be_read_again_saving_works(data, monkeypatch):
    target = data / "x.json"
    target.write_text("{}")
    fsutil._UNREADABLE.add(os.path.abspath(str(target)))
    fsutil.atomic_write_json(str(target), {"ok": 1})  # readable now: allowed, and forgotten
    assert fsutil.read_json(str(target)) == {"ok": 1} and os.path.abspath(str(target)) not in fsutil._UNREADABLE


def test_the_start_up_check_restores_damaged_settings(data):
    _snapshot(data, "screen.json", json.dumps({"brightness": 60}))
    (data / "screen.json").write_text("{oops")
    (data / "lost.json").write_text("{oops")
    (data / "fine.json").write_text("{}")
    result = data_health.check_json_files(str(data))
    assert result == {"restored": ["screen.json"], "lost": ["lost.json"]}
    assert json.loads((data / "screen.json").read_text()) == {"brightness": 60}


def test_install_registers_the_restore_once(monkeypatch):
    monkeypatch.setattr(fsutil, "RESTORERS", [])
    data_health.install_json_restore()
    data_health.install_json_restore()
    assert [data_health.restore_json] == fsutil.RESTORERS
