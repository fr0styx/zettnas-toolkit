"""SET-13: "export my data" hands over the event-log entries that name a person, and erasing an
account replaces the name in them."""

import json
import pathlib

import pytest

from backend import db, event_store, state
from backend.services import user_data


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "history.db"))
    monkeypatch.setattr(state, "EVENTS_FILE", str(tmp_path / "events.json"))
    monkeypatch.setattr(event_store, "_state", {"table_in": "", "pruned": 0.0})
    monkeypatch.setattr(state.Z_STATE, "event_log", [])
    state._event_unsaved.clear()
    state._event_recent.clear()
    state.add_event(
        "warning", "Event log cleared", "marta cleared the event log.", state.event_text("log_cleared", who="marta")
    )
    state.add_event("info", "Freeze lifted", "Freeze lifted by Marta", state.event_text("guard_lifted", by="Marta"))
    state.add_event(
        "info", "Backup finished: Photos", "ok", {"title_key": "alert.backup_ok.title", "params": {"name": "Photos"}}
    )
    state.add_event(
        "warning", "Sign-in", "An alert about al and the alarm", state.event_text("default_login", who="al")
    )
    state.add_event("info", "Smart test", "Started by martassen on sda")
    yield state


def test_export_has_the_entries_that_name_the_person(log):
    marta = {"id": "u-1", "username": "marta"}
    mine = user_data._event_log(marta)
    assert [e["title"] for e in mine] == ["Freeze lifted", "Event log cleared"]
    assert user_data._event_log({"username": ""}) == []
    # a short name counts only as a value, not as a piece of other words
    assert [e["title"] for e in user_data._event_log({"username": "al"})] == ["Sign-in"]
    assert "event_log" in user_data.STORES and "event_log" in user_data.PARTS


def test_erasing_replaces_the_name_and_keeps_the_entries(log):
    marta = {"id": "u-1", "username": "marta"}
    done = user_data.erase_user_data(marta, ("event_log",))
    assert done == {"event_log": 2}
    alias = [e for e in event_store.newest() if e["title"] == "Event log cleared"][0]["details"]["params"]["who"]
    assert alias.startswith("erased-") and len(alias) == 17
    everywhere = json.dumps(event_store.newest()) + json.dumps(state.events_snapshot())
    everywhere += pathlib.Path(state.EVENTS_FILE).read_text()
    assert "marta " not in everywhere.lower() and '"marta"' not in everywhere.lower()
    assert f"{alias} cleared the event log." in everywhere and f"Freeze lifted by {alias}" in everywhere
    assert "martassen" in everywhere and len(event_store.newest()) == 5  # another person, and nothing went
    assert user_data._event_log(marta) == []
    assert user_data.erase_user_data({"id": "u-9", "username": ""}, ("event_log",)) == {"event_log": 0}


def test_a_store_that_cannot_be_written_is_reported(log, monkeypatch):
    def broken(*_a):
        raise OSError("read-only")

    monkeypatch.setattr(event_store, "forget_user", broken)
    done = user_data.erase_user_data({"id": "u-1", "username": "marta"}, ("event_log",))
    assert done == {"event_log": {"error": "Could not remove their name from the event log."}}
    monkeypatch.setattr(db, "DB_PATH", "/nonexistent-folder/history.db")
    monkeypatch.setattr(event_store, "_state", {"table_in": "", "pruned": 0.0})
    assert event_store.for_user("marta") == []
