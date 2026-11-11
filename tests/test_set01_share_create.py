"""SET-01: creating a share says what is wrong, and Time Machine is one request.

- A refused folder, name or client list used to come back as "Something went wrong on the server".
- The page used to send a second request for Time Machine that replaced the share's settings (its
  people lists were dropped), carried no size limit, and hid its own failure.
"""

from unittest.mock import MagicMock, patch

from backend.api import storage
from backend.services.samba_engine import SambaShareConfig


def _platform(create=None):
    adapter = MagicMock()
    adapter.get_capabilities.return_value.is_observer_mode = False
    adapter.create_share.side_effect = create
    adapter.create_share.return_value = {"name": "tm", "status": "created"}
    return adapter


def _post(client, auth_headers, **body):
    return client.post("/api/storage/shares", json={"name": "tm", **body}, headers=auth_headers)


def test_a_refused_share_says_why(client, auth_headers):
    refused = ValueError("The folder /etc cannot be shared: it is outside the storage.")
    with patch.object(storage, "get_storage_platform", return_value=_platform(refused)):
        res = _post(client, auth_headers, path="/etc")
    assert res.status_code == 400
    assert "outside the storage" in res.text and "went wrong" not in res.text


def test_time_machine_needs_smb_and_a_size_limit(client, auth_headers):
    adapter = _platform()
    with patch.object(storage, "get_storage_platform", return_value=adapter):
        no_limit = _post(client, auth_headers, timemachine=True)
        no_smb = _post(client, auth_headers, timemachine=True, quota_gb=500, export_smb=False)
    assert no_limit.status_code == 400 and "size limit" in no_limit.text
    assert no_smb.status_code == 400 and "SMB" in no_smb.text
    adapter.create_share.assert_not_called()


def test_time_machine_keeps_the_people_lists_and_gets_the_limit(client, auth_headers):
    engine = MagicMock()
    engine.get_share.return_value = SambaShareConfig(
        name="tm", path="/mnt/storage/tm", read_only=False, valid_users="anna ben", write_list="anna"
    )
    with (
        patch.object(storage, "get_storage_platform", return_value=_platform()),
        patch("backend.services.samba_engine.get_samba_engine", return_value=engine),
        patch("backend.services.nas_name.refresh") as announced,
    ):
        res = _post(client, auth_headers, timemachine=True, quota_gb=500)
    assert res.status_code == 200, res.text
    saved = engine.add_or_update_share.call_args.args[0]
    assert saved.timemachine is True and saved.timemachine_quota_gb == 500
    assert saved.valid_users == "anna ben" and saved.write_list == "anna"
    announced.assert_called_once()


def test_a_time_machine_failure_is_told(client, auth_headers):
    engine = MagicMock()
    engine.get_share.return_value = None
    with (
        patch.object(storage, "get_storage_platform", return_value=_platform()),
        patch("backend.services.samba_engine.get_samba_engine", return_value=engine),
    ):
        missing = _post(client, auth_headers, timemachine=True, quota_gb=500)
    engine.get_share.return_value = SambaShareConfig(name="tm", path="/mnt/storage/tm")
    engine.add_or_update_share.side_effect = ValueError("no room")
    with (
        patch.object(storage, "get_storage_platform", return_value=_platform()),
        patch("backend.services.samba_engine.get_samba_engine", return_value=engine),
    ):
        refused = _post(client, auth_headers, timemachine=True, quota_gb=500)
    assert missing.status_code == 400 and "Time Machine could not be turned on" in missing.text
    assert refused.status_code == 400 and "no room" in refused.text
