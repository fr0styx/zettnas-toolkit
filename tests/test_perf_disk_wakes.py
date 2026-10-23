"""Less disk wake time: no guard-file checks on sleeping disks, spin-up rescans rate-limited (PERF-7)."""

import os
from pathlib import Path
from unittest.mock import patch

from backend.services import rag_engine, rag_standby
from backend.services import ransomware_guard as rg


def _guard(tmp_path):
    guard = rg.RansomwareGuard(state_file=str(tmp_path / "guard.json"))
    guard.state.update(enabled=True, canaries=True, frozen=False)
    hits = []
    guard._react = lambda reason, src: hits.append(src["example"])
    p = tmp_path / rg.CANARY_NAME
    p.write_bytes(b"x")
    st = os.stat(p)
    guard.state["canary_files"] = {str(p): {"size": st.st_size + 1, "mtime": st.st_mtime_ns}}  # looks changed
    return guard, hits


def test_guard_files_on_a_sleeping_disk_are_not_touched(tmp_path):
    guard, hits = _guard(tmp_path)
    with (
        patch.object(rag_standby, "resolve_path_backing_dev", return_value="sdb"),
        patch.object(rag_standby, "is_backing_disk_in_standby", return_value=True),
        patch.object(rg.os, "stat", side_effect=AssertionError("touched a sleeping disk")),
    ):
        assert guard.check_canaries() is False
    assert hits == []


def test_guard_files_on_an_unknown_disk_are_still_checked(tmp_path):
    guard, hits = _guard(tmp_path)
    with (
        patch.object(rag_standby, "resolve_path_backing_dev", return_value=rag_standby.UNKNOWN_BACKING_DEV),
        patch.object(rag_standby, "is_backing_disk_in_standby", return_value=True),
    ):
        assert guard.check_canaries() is True
    assert hits


def test_spin_up_rescans_a_disk_at_most_every_six_hours(tmp_path):
    with patch.object(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        engine = rag_engine.RagSearchEngine(db_path=str(tmp_path / "rag.db"))
        folder = Path(tmp_path) / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("# Note\nhello", encoding="utf-8")
        engine.update_config({"enabled": True, "auto_learn_on_spinup": True, "watched_paths": [str(folder)]})
        asleep = {"v": True}
        with (
            patch.object(rag_standby, "resolve_path_backing_dev", return_value="sda"),
            patch.object(rag_standby, "is_backing_disk_in_standby", side_effect=lambda _p: asleep["v"]),
            patch.object(rag_standby, "get_sleeping_disks_list", side_effect=lambda: ["sda"] if asleep["v"] else []),
            patch.object(engine, "get_deferred_queue", return_value=[]),
        ):
            engine._known_sleeping_devs = {"sda"}
            asleep["v"] = False
            first = engine.check_and_trigger_spinup_auto_learn(background=False)
            assert first["triggered"] is True
            asleep["v"] = True
            engine.check_and_trigger_spinup_auto_learn(background=False)
            asleep["v"] = False
            again = engine.check_and_trigger_spinup_auto_learn(background=False)
            assert again["triggered"] is False
            engine._last_spinup_rescan["sda"] -= rag_engine.SPINUP_RESCAN_COOLDOWN_SECS + 1
            asleep["v"] = True
            engine.check_and_trigger_spinup_auto_learn(background=False)
            asleep["v"] = False
            assert engine.check_and_trigger_spinup_auto_learn(background=False)["triggered"] is True
