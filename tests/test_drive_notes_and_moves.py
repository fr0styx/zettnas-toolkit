"""Drive Health: the owner's purchase and warranty details, and history that follows a drive by its
serial number when its device name changes."""

import json
import time

import pytest

from backend import db
from backend.services import drive_notes


@pytest.fixture
def notes_file(tmp_path, monkeypatch):
    path = tmp_path / "drive_notes.json"
    monkeypatch.setattr(drive_notes, "NOTES_FILE", str(path))
    return path


def test_details_are_kept_by_serial(notes_file):
    saved = drive_notes.save("WD-ABC123", "2024-05-01", "2027-05-01", "  bay 3, order 991\x07 ")
    assert saved == {"bought": "2024-05-01", "warranty_until": "2027-05-01", "note": "bay 3, order 991"}
    assert drive_notes.all_notes() == {"WD-ABC123": saved}
    assert json.loads(notes_file.read_text())["WD-ABC123"]["note"] == "bay 3, order 991"
    # all empty removes them
    assert drive_notes.save("WD-ABC123") is None
    assert drive_notes.all_notes() == {}


@pytest.mark.parametrize(
    "args, why",
    [
        (("../etc", "", "", ""), "serial"),
        (("S1", "31.05.2026", "", ""), "date like"),
        (("S1", "1980-01-01", "", ""), "between 1990"),
        (("S1", "2025-01-01", "2024-01-01", ""), "can't end before"),
    ],
)
def test_bad_details_are_refused(notes_file, args, why):
    with pytest.raises(drive_notes.BadNotes, match=why):
        drive_notes.save(*args)


def test_a_long_note_is_cut_and_a_broken_file_starts_empty(notes_file):
    assert len(drive_notes.save("S2", note="x" * 900)["note"]) == drive_notes.NOTE_MAX
    notes_file.write_text("{not json")
    assert drive_notes.all_notes() == {}
    notes_file.write_text("[1, 2]")
    assert drive_notes.all_notes() == {}


def test_too_many_drives(notes_file, monkeypatch):
    monkeypatch.setattr(drive_notes, "MAX_DRIVES", 1)
    drive_notes.save("S1", note="a")
    with pytest.raises(drive_notes.BadNotes, match="Too many"):
        drive_notes.save("S2", note="b")
    assert drive_notes.save("S1", note="c") == {"note": "c"}  # an existing one can still change


def test_the_api(client, auth_headers, notes_file):
    r = client.put(
        "/api/drives/notes", headers=auth_headers, json={"serial": "S9", "bought": "2025-02-03", "note": "top bay"}
    )
    assert r.status_code == 200 and r.json() == {"serial": "S9", "notes": {"bought": "2025-02-03", "note": "top bay"}}
    assert client.get("/api/drives/notes", headers=auth_headers).json() == {"notes": {"S9": r.json()["notes"]}}
    bad = client.put("/api/drives/notes", headers=auth_headers, json={"serial": "S9", "bought": "soon"})
    assert bad.status_code == 400 and "date" in bad.json()["detail"]


# --- the history follows the drive ------------------------------------------------------------


def _rows(dev):
    with db.history_session() as conn:
        return [
            tuple(r) for r in conn.execute("SELECT ts, serial FROM smart_history WHERE dev = ? ORDER BY ts", (dev,))
        ]


def _log(ts, dev, serial, realloc=0):
    db.log_smart_metrics(ts, dev, 35.0, {"realloc": realloc, "serial": serial})


@pytest.fixture
def history():
    db.init_db()
    db._SERIAL_AT.clear()
    with db.history_session() as conn:
        conn.execute("DELETE FROM smart_history WHERE dev LIKE 'mv%' OR dev LIKE '~MV%'")
    yield int(time.time()) - 7200
    with db.history_session() as conn:
        conn.execute("DELETE FROM smart_history WHERE dev LIKE 'mv%' OR dev LIKE '~MV%'")


def test_two_drives_that_swap_names_keep_their_own_history(history):
    t0 = history
    _log(t0, "mva", "MV-X")
    _log(t0, "mvb", "MV-Y", realloc=4)
    # after a reboot the names are swapped
    _log(t0 + 60, "mva", "MV-Y", realloc=4)
    _log(t0 + 60, "mvb", "MV-X")
    # (nothing changed within ten minutes, so no new rows: each name now has the other's row)
    assert _rows("mva") == [(t0, "MV-Y")]
    assert _rows("mvb") == [(t0, "MV-X")]
    assert db.get_smart_history_samples("mva", days=1)[0]["reallocated_sectors"] == 4


def test_a_replaced_drive_starts_fresh_and_the_old_one_comes_back(history):
    t0 = history
    _log(t0, "mvc", "MV-OLD", realloc=7)
    _log(t0 + 60, "mvc", "MV-NEW")  # another drive in the same slot
    assert _rows("mvc") == [(t0 + 60, "MV-NEW")]
    assert _rows("~MV-OLD") == [(t0, "MV-OLD")]
    _log(t0 + 120, "mvd", "MV-OLD", realloc=8)  # the old one is plugged in again elsewhere
    assert _rows("mvd") == [(t0, "MV-OLD"), (t0 + 120, "MV-OLD")]
    assert _rows("~MV-OLD") == []
    assert "~MV-OLD" not in db.query_all_smart_velocities()


def test_unknown_serials_change_nothing(history):
    t0 = history
    _log(t0, "mve", "MV-Z")
    _log(t0 + 60, "mve", "Unknown", realloc=1)
    assert _rows("mve") == [(t0, "MV-Z"), (t0 + 60, None)]
