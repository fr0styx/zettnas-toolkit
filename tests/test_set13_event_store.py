"""SET-13: events have an identity. An id, a kind and a link; kept 90 days in history.db; a
repeat is counted on its entry instead of dropped; what events.json held is carried over."""

import json
import pathlib
import re

import pytest

from backend import db, event_store, state

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "history.db"))
    monkeypatch.setattr(state, "EVENTS_FILE", str(tmp_path / "events.json"))
    monkeypatch.setattr(event_store, "_state", {"table_in": "", "pruned": 0.0, "said": 0.0})
    monkeypatch.setattr(state, "_event_next_id", 1)
    monkeypatch.setattr(state.Z_STATE, "event_log", [])
    clock = {"t": 1_700_000_000}
    monkeypatch.setattr(state.time, "time", lambda: clock["t"])
    state._event_unsaved.clear()
    state._event_recent.clear()
    yield clock
    state._event_unsaved.clear()
    state._event_recent.clear()


def test_an_entry_has_an_id_a_kind_and_the_place_that_deals_with_it(log):
    first = state.add_event("info", "Power is back", "Mains power returned.", state.event_text("ups_power_back"))
    second = state.add_event("warning", "Something", "No text key here")
    assert (first, second) == (1, 2)
    newest, older = state.events_snapshot()
    assert newest == {"id": 2, "ts": log["t"], "level": "warning", "title": "Something", "message": "No text key here"}
    assert older["kind"] == "ups_power_back" and older["link"] == "power" and older["id"] == 1
    stored = event_store.newest()
    assert [e["id"] for e in stored] == [2, 1] and stored[1]["details"]["title_key"] == "ev.ups_power_back.title"
    assert json.loads(pathlib.Path(state.EVENTS_FILE).read_text())[0]["id"] == 2  # an older build still reads it


def test_a_repeat_is_counted_and_a_different_message_is_kept(log):
    state.add_event("warning", "Address blocked", "10.0.0.7 after 5 wrong passwords")
    log["t"] += 20
    # a second address within a minute was dropped: same level and title
    state.add_event("warning", "Address blocked", "10.0.0.9 after 5 wrong passwords")
    log["t"] += 20
    state.add_event("info", "Something else", "in between")
    log["t"] += 20
    again = state.add_event("warning", "Address blocked", "10.0.0.7 after 5 wrong passwords")
    events = state.events_snapshot()
    assert again == 1 and [e["id"] for e in events] == [1, 3, 2]  # the repeated entry is the newest again
    assert events[0]["count"] == 2 and events[0]["last_ts"] == log["t"] and events[0]["ts"] == log["t"] - 60
    assert "count" not in events[2]
    assert event_store.newest()[0]["count"] == 2
    log["t"] += state.EVENT_REPEAT_SECS  # after an hour it is a new entry, as before
    assert state.add_event("warning", "Address blocked", "10.0.0.7 after 5 wrong passwords") == 4


def test_one_title_cannot_flood_the_log(log):
    for n in range(state.EVENT_FLOOD + 12):
        state.add_event("error", "Copy failed", f"file {n}")
    events = state.events_snapshot()
    assert len(events) == state.EVENT_FLOOD
    assert events[0]["count"] == 13 and events[0]["message"] == f"file {state.EVENT_FLOOD - 1}"
    log["t"] += 61
    state.add_event("error", "Copy failed", "file later")
    assert len(state.events_snapshot()) == state.EVENT_FLOOD + 1


def test_the_log_survives_a_restart_and_goes_on_counting_from_there(log):
    for n in range(3):
        log["t"] += 5
        state.add_event("info", f"Entry {n}", "x", state.event_text("vm_created"))
    state.Z_STATE.event_log = []
    state._load_events()
    assert [e["id"] for e in state.events_snapshot()] == [3, 2, 1]
    assert state.events_snapshot()[0]["link"] == "vms"
    assert state.add_event("info", "After the restart", "y") == 4


def test_what_the_old_file_held_is_carried_over_once(log):
    old = [
        {
            "ts": log["t"] - 100,
            "level": "error",
            "title": "Newest",
            "message": "c",
            "details": {"title_key": "ev.copy_failed.title"},
        },
        {"ts": log["t"] - 200, "level": "info", "title": "Middle", "message": "b"},
        {"ts": log["t"] - 300, "level": "info", "title": "Oldest", "message": "a"},
    ]
    pathlib.Path(state.EVENTS_FILE).write_text(json.dumps(old))
    state._load_events()
    events = state.events_snapshot()
    assert [(e["id"], e["title"]) for e in events] == [(3, "Newest"), (2, "Middle"), (1, "Oldest")]
    assert events[0]["kind"] == "copy_failed" and events[0]["link"] == "cards"
    state.flush_events()
    state._load_events()  # the file now carries ids: nothing is carried over twice
    assert len(event_store.newest()) == 3 and len(state.events_snapshot()) == 3
    # an older build ran in between and wrote an entry without an id
    with_one_more = [{"ts": log["t"], "level": "info", "title": "From the older build", "message": "d"}, *events]
    pathlib.Path(state.EVENTS_FILE).write_text(json.dumps(with_one_more))
    state._load_events()
    assert [(e["id"], e["title"]) for e in state.events_snapshot()][0] == (4, "From the older build")
    assert state.add_event("info", "Next", "e") == 5


def test_the_file_is_the_list_when_the_store_cannot_be_read(log, monkeypatch):
    pathlib.Path(state.EVENTS_FILE).write_text(
        json.dumps(
            [
                {"ts": 2, "level": "info", "title": "B", "message": ""},
                {"ts": 1, "level": "info", "title": "A", "message": ""},
            ]
        )
    )
    monkeypatch.setattr(db, "DB_PATH", "/nonexistent-folder/history.db")
    monkeypatch.setattr(event_store, "_state", {"table_in": "", "pruned": 0.0, "said": 0.0})
    state._load_events()
    assert [(e["id"], e["title"]) for e in state.events_snapshot()] == [(2, "B"), (1, "A")]
    assert state.add_event("info", "C", "still works") == 3  # recording never fails the caller
    assert [e["title"] for e in json.loads(pathlib.Path(state.EVENTS_FILE).read_text())] == ["C", "B", "A"]
    assert 3 in state._event_unsaved  # kept for the next write
    monkeypatch.setattr(db, "DB_PATH", str(pathlib.Path(state.EVENTS_FILE).parent / "history.db"))
    state.flush_events()
    assert [e["id"] for e in event_store.newest()] == [3] and not state._event_unsaved
    pathlib.Path(state.EVENTS_FILE).write_text("{ not json")
    assert state._read_events_file() == []


def test_entries_are_kept_ninety_days(log):
    state.add_event("info", "Old", "from long ago")
    log["t"] += (event_store.RETENTION_DAYS + 1) * 86400
    event_store._state["pruned"] = 0.0
    state.add_event("info", "New", "today")
    assert [e["title"] for e in event_store.newest()] == ["New"]
    assert event_store.newest(limit=10, before_id=2) == [] and event_store.newest(level="error") == []
    assert event_store.newest(limit=10, level="info")[0]["id"] == 2


def test_clearing_forgets_the_repeat_memory_too(log):
    state.add_event("error", "Fan stalled", "fan 2")
    state.clear_events()
    assert state.events_snapshot() == [] and event_store.newest() == []
    # a fault that continues stayed out of the cleared log for up to an hour
    state.add_event("error", "Fan stalled", "fan 2")
    assert len(state.events_snapshot()) == 1 and "count" not in state.events_snapshot()[0]


def test_kinds_and_links():
    assert event_store.kind_of({"title_key": "alert.pool.fixed.title"}) == "pool.fixed"
    assert event_store.kind_of({"msg_key": "ev.net_trial.msg"}) == "net_trial"
    assert event_store.kind_of({"kind": "backup_done"}) == "backup_done"
    assert event_store.kind_of(None) == "" and event_store.kind_of({"title_key": "toast.x"}) == ""
    assert event_store.link_of("pool.fixed") == "storage" and event_store.link_of("ups_copy_resumed") == "power"
    assert event_store.link_of("vm_created", {"link": "backup"}) == "backup"
    assert event_store.link_of("reboot") == ""


# kinds that have no page of their own: their entry opens in the Event Log
NO_PLACE = {"reboot", "shutdown", "log_cleared"}


def test_every_kind_the_server_writes_has_a_place_the_interface_can_open():
    names = set()
    for path in (ROOT / "backend").rglob("*.py"):
        names |= set(re.findall(r"event_text\(\s*\"([a-z0-9_]+)\"", path.read_text(encoding="utf-8")))
    assert len(names) > 60
    router = (ROOT / "frontend" / "src" / "router.js").read_text(encoding="utf-8")
    routes = set(re.findall(r"^\s+'?([a-z/]+)'?: \(\) =>", router, re.M))
    nowhere = {n for n in names if not event_store.link_of(n)}
    assert nowhere == NO_PLACE, (
        f"decide where these kinds lead (backend/event_store.py LINKS): {sorted(nowhere ^ NO_PLACE)}"
    )
    unknown = {place for _, place in event_store.LINKS if place not in routes}
    assert not unknown, f"the interface cannot open {sorted(unknown)} (frontend/src/router.js)"
