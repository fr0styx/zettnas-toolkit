"""The practice run keeps its answer for the page (SET-15, Power B4)."""

from unittest.mock import patch

from backend.services import ups_watchdog as uw


def test_the_last_practice_run_is_kept_with_its_answer(tmp_path):
    with patch.object(uw, "_practice_file", return_value=str(tmp_path / "p.json")):
        assert uw.last_practice() == {}
        path = {
            "by": "kiboto",
            "ok": False,
            "detail": "Nothing shuts it down.",
            "text": {"msg_key": "power_nobody", "params": {}},
        }
        with (
            patch.object(uw, "shutdown_path_report", return_value=path),
            patch.object(uw, "log_ups_event"),
            patch.object(uw, "add_event"),
        ):
            res = uw.trigger_outage_simulation(15)
        uw.end_simulation_drill()
        rec = uw.last_practice()
        assert (
            rec["ok"] is False
            and rec["text"] == path["text"]
            and rec["detail"] == "Nothing shuts it down."
            and rec["at"] > 0
        )
        assert res["practice"] == rec


def test_a_failed_write_does_not_stop_the_practice_run(tmp_path):
    with (
        patch.object(uw, "_practice_file", return_value=str(tmp_path / "missing" / "dir" / "p.json")),
        patch("backend.fsutil.atomic_write_json", side_effect=OSError("read-only")),
    ):
        uw._remember_practice({"ok": True})  # logged, not raised
        assert uw.last_practice() == {}


def test_the_api_returns_the_last_practice_run(client, auth_headers):
    with patch.object(uw, "last_practice", return_value={"at": 1.0, "ok": True, "text": None, "detail": "x"}):
        r = client.get("/api/ups/practice", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
