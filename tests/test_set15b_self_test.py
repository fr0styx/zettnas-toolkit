"""SET-15 (Power B3): the battery test is refused where nothing can send it, and writes no history row then."""

from unittest.mock import patch

import pytest

from backend.hardware import ups


def test_nothing_sent_is_refused_and_not_logged():
    with (
        patch.object(ups, "load_ups_config", return_value={"mode": "usb_hid", "port": 3551}),
        patch.object(ups.subprocess, "run", side_effect=FileNotFoundError),
        patch.object(ups, "log_ups_event") as log,
        pytest.raises(ups.SelfTestNotSent),
    ):
        ups.run_ups_self_test()
    log.assert_not_called()


def test_the_route_says_why(client, auth_headers):
    with patch.object(ups, "run_ups_self_test", side_effect=ups.SelfTestNotSent("usb_hid")):
        res = client.post("/api/ups/self-test", headers=auth_headers)
    assert res.status_code == 409
    assert "not sent" in res.json()["detail"]


def test_an_accepted_test_is_logged_as_sent():
    done = type("R", (), {"returncode": 0})()
    with (
        patch.object(ups, "load_ups_config", return_value={"mode": "usb_hid", "port": 3551}),
        patch.object(ups.subprocess, "run", return_value=done),
        patch.object(ups, "read_ups_status", return_value={"battery_charge_pct": 90}),
        patch.object(ups, "log_ups_event") as log,
    ):
        res = ups.run_ups_self_test()
    assert log.call_args.kwargs["status"] == "SENT"
    assert res["status"] == ""
