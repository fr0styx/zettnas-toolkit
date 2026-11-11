"""SET-15 (Power 2): who switches the NAS off has its own route and says how its sentence was made."""

from unittest.mock import patch

from backend.services import ups_watchdog as wd


def test_nobody_can_is_said_with_a_key(client, auth_headers):
    with (
        patch.object(wd, "shutdown_owner", return_value="kiboto"),
        patch.object(wd, "host_shutdown_paths", return_value=[]),
    ):
        res = client.get("/api/ups/shutdown-path", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["text"]["msg_key"] == "srv.power_nobody"
