"""Drive Health: findings the owner acknowledged stop setting the verdict until their numbers change."""

import pytest

from backend.services import drive_acks, drive_health
from backend.services.drive_notes import BadNotes


@pytest.fixture(autouse=True)
def acks_file(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_acks, "ACKS_FILE", str(tmp_path / "drive_acks.json"))


def _finding(code="reallocated_stable", severity="watch", n=8):
    return {
        "code": code,
        "key": code,
        "params": {"n": n},
        "severity": severity,
        "kind": "replace",
        "title": f"{n} replaced",
        "detail": "",
        "action": "",
    }


def _result(*findings):
    return {
        "from_history": False,
        **drive_health.summarize(sorted(findings, key=lambda f: -drive_health.ORDER[f["severity"]])),
    }


def test_an_acknowledged_finding_no_longer_sets_the_verdict():
    result = _result(_finding(), _finding("crc_errors", "watch", 3))
    assert result["verdict"] == "watch"
    drive_acks.acknowledge("wd-1", "reallocated_stable", {"n": 8}, "watch", "8 replaced")
    still = drive_acks.apply_acks(result, "WD-1")
    assert still["verdict"] == "watch" and still["summary"] == "3 replaced"  # the other one leads now
    drive_acks.acknowledge("WD-1", "crc_errors", {"n": 3}, "watch")
    calm = drive_acks.apply_acks(result, " wd-1 ")
    assert calm["verdict"] == "ok" and calm["label_key"] == "ok"
    acked = {f["code"]: f for f in calm["findings"]}["reallocated_stable"]
    assert acked["severity"] == "ok" and acked["acknowledged"]["severity"] == "watch"
    assert result["verdict"] == "watch"  # the original is left as it was


def test_it_counts_again_when_the_numbers_change():
    drive_acks.acknowledge("S1", "reallocated_stable", {"n": 8}, "watch")
    grown = drive_acks.apply_acks(_result(_finding(n=9)), "S1")
    assert grown["verdict"] == "watch"
    # acknowledging the new number replaces the old acknowledgement
    drive_acks.acknowledge("S1", "reallocated_stable", {"n": 9}, "watch")
    assert list(drive_acks.acks_for("S1")) == [drive_acks.fingerprint("reallocated_stable", {"n": 9})]


def test_taking_it_back_shows_it_again_even_on_a_stored_verdict():
    drive_acks.acknowledge("S1", "reallocated_stable", {"n": 8}, "soon")
    stored = drive_acks.apply_acks(_result(_finding(severity="soon")), "S1")
    assert stored["verdict"] == "ok"
    assert drive_acks.apply_acks(stored, "S1") is stored  # nothing new: the same result
    assert drive_acks.forget("S1", "reallocated_stable") is True
    back = drive_acks.apply_acks(stored, "S1")
    assert back["verdict"] == "soon" and "acknowledged" not in back["findings"][0]
    assert drive_acks.forget("S1", "reallocated_stable") is False
    assert drive_acks.all_acks() == {}


@pytest.mark.parametrize(
    "args, why",
    [
        (("S1", "smart_failed", {}, "now"), "replace now"),
        (("../x", "crc_errors", {}, "watch"), "serial"),
        (("S1", "bad code!", {}, "watch"), "Unknown finding"),
        (("S1", "crc_errors", {"x": "y" * 500}, "watch"), "Unknown finding"),
    ],
)
def test_what_cant_be_acknowledged(args, why):
    with pytest.raises(BadNotes, match=why):
        drive_acks.acknowledge(*args)


def test_a_finding_that_says_replace_now_is_never_set_aside():
    drive_acks.acknowledge("S1", "unreadable_sectors", {"n": 2}, "soon")
    worse = drive_acks.apply_acks(_result(_finding("unreadable_sectors", "now", 2)), "S1")
    assert worse["verdict"] == "now"


def test_limits_and_a_broken_file(monkeypatch, tmp_path):
    monkeypatch.setattr(drive_acks, "MAX_PER_DRIVE", 1)
    drive_acks.acknowledge("S1", "a", {}, "watch")
    with pytest.raises(BadNotes, match="too many"):
        drive_acks.acknowledge("S1", "b", {}, "watch")
    (tmp_path / "drive_acks.json").write_text("{oops")
    assert drive_acks.acks_for("S1") == {}
    assert drive_acks.acks_for("", None) == {}
    assert drive_acks.apply_acks({"findings": []}, "S1") == {"findings": []}


def test_the_api(client, auth_headers):
    body = {"serial": "S5", "code": "crc_errors", "params": {"n": 3}, "severity": "watch", "title": "Cable errors"}
    r = client.post("/api/drives/acks", headers=auth_headers, json=body)
    assert r.status_code == 200 and r.json()["fingerprint"].startswith("crc_errors:")
    bad = client.post("/api/drives/acks", headers=auth_headers, json={**body, "severity": "now"})
    assert bad.status_code == 400
    r = client.post("/api/drives/acks/forget", headers=auth_headers, json={"serial": "S5", "code": "crc_errors"})
    assert r.json() == {"forgotten": True}


def test_stored_readings_follow_the_acknowledgements(monkeypatch):
    from backend.hardware import disks

    monkeypatch.setattr(disks, "_discover_disks", lambda: [{"dev": "sdq", "serial": "Q1"}])
    detail = {"serial": "Hidden while in standby", "drive_health": _result(_finding())}
    monkeypatch.setitem(disks._DETAIL_CACHE, "sdq", (__import__("time").time(), detail))
    assert disks.cached_smart_detail("sdq", 60)["drive_health"]["verdict"] == "watch"
    drive_acks.acknowledge("Q1", "reallocated_stable", {"n": 8}, "watch")
    assert disks.cached_smart_detail("sdq", 60)["drive_health"]["verdict"] == "ok"
    assert disks._drive_serials("nope") == []
    assert disks._with_acks("sdq", {"error": "x"}) == {"error": "x"}
