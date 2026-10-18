"""
Unit tests for storage share quotas, user permissions matrix,
SMART self-test spindown guards, and Docker update policies.
"""

from unittest.mock import MagicMock, patch
import pytest

from backend.api.storage import StorageShareCreateRequest
from backend.hardware.pal_storage import GenericLinuxStorageAdapter
from backend.services.samba_engine import SambaShareConfig, SambaEngine
from backend.hardware.disks import run_disk_smart_test
from backend.services.docker_updates import (
    get_container_update_policy,
    set_container_update_policy,
    get_container_update_policies,
    _check_container_image_update,
)


def test_storage_share_create_request_model():
    req = StorageShareCreateRequest(
        name="backup_vault",
        path="/mnt/storage/backup_vault",
        quota_gb=500,
        user_permissions={"alice": "rw", "bob": "ro", "guest": "deny"},
    )
    assert req.name == "backup_vault"
    assert req.quota_gb == 500
    assert req.user_permissions["alice"] == "rw"
    assert req.user_permissions["bob"] == "ro"
    assert req.user_permissions["guest"] == "deny"


@patch("os.makedirs")
@patch("backend.services.samba_engine.get_samba_engine")
def test_generic_linux_storage_adapter_creates_share_with_quotas_and_perms(mock_get_samba, mock_makedirs):
    mock_samba = MagicMock()
    mock_get_samba.return_value = mock_samba

    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")
    res = adapter.create_share(
        name="finance",
        path="/mnt/storage/finance",
        comment="Finance team documents",
        security="private",
        read_only=False,
        export_smb=True,
        export_nfs=False,
        quota_gb=250,
        user_permissions={"cfo": "rw", "auditor": "ro", "contractor": "deny"},
    )

    assert res["status"] == "created"
    assert res["quota_gb"] == 250
    assert res["user_permissions"] == {"cfo": "rw", "auditor": "ro", "contractor": "deny"}

    # Verify SambaEngine was called with appropriate configuration
    mock_samba.add_or_update_share.assert_called_once()
    cfg: SambaShareConfig = mock_samba.add_or_update_share.call_args[0][0]
    assert cfg.name == "finance"
    assert cfg.quota_gb == 250
    assert "cfo" in cfg.valid_users
    assert "auditor" in cfg.valid_users
    assert cfg.write_list == "cfo"
    assert cfg.read_list == "auditor"


def test_samba_engine_conf_includes_read_write_lists_and_quota(tmp_path):
    conf_file = tmp_path / "smb.conf"
    with patch("backend.services.samba_engine.SAMBA_CONF_FILE", str(conf_file)):
        engine = SambaEngine()
        engine._shares = {}

        share = SambaShareConfig(
            name="projects",
            path="/mnt/storage/projects",
            quota_gb=100,
            valid_users="dev1 dev2",
            read_list="dev2",
            write_list="dev1",
        )
        engine.add_or_update_share(share)
        conf_text = engine.generate_and_save_conf()

        assert "[projects]" in conf_text
        assert "valid users = dev1 dev2" in conf_text
        assert "read list = dev2" in conf_text
        assert "write list = dev1" in conf_text
        assert "# storage quota = 100G" in conf_text


@patch("backend.hardware.smart_engine.SmartEngine.is_device_sleeping", return_value=True)
def test_smart_self_test_skips_when_device_sleeping(mock_is_sleeping):
    from backend.state import Z_STATE

    with patch.dict(Z_STATE.cached_smart_data, {}, clear=True):
        res = run_disk_smart_test("/dev/sdb", test_type="short", skip_if_standby=True)
        assert res["skipped"] is True
        assert "standby mode" in res["output"]
        mock_is_sleeping.assert_called_once()


def test_docker_update_policies_workflow(tmp_path):
    policies_file = tmp_path / "policies.json"
    with patch("backend.services.docker_updates.DOCKER_POLICIES_FILE", str(policies_file)):
        # Default policy is notify
        assert get_container_update_policy("test_container") == "notify"

        # Set specific policies
        set_container_update_policy("auto_app", "auto")
        set_container_update_policy("static_app", "off")

        assert get_container_update_policy("auto_app") == "auto"
        assert get_container_update_policy("static_app") == "off"
        assert get_container_update_policy("unknown_app") == "notify"

        # Check invalid policy rejected
        with pytest.raises(ValueError):
            set_container_update_policy("bad_app", "invalid_policy")

        # Check disabled policy in check_container_image_update
        c = {"Id": "123456", "Names": ["/static_app"], "Image": "nginx:alpine"}
        res = _check_container_image_update(c)
        assert res["status"] == "policy_off"
        assert res["has_update"] is False


def test_docker_update_policies_api_endpoints(client, auth_headers, tmp_path):
    policies_file = tmp_path / "policies.json"
    with patch("backend.services.docker_updates.DOCKER_POLICIES_FILE", str(policies_file)):
        # GET initial policies
        res = client.get("/api/docker/updates/policies", headers=auth_headers)
        assert res.status_code == 200
        assert isinstance(res.json(), dict)

        # POST single policy
        res2 = client.post(
            "/api/docker/updates/policies",
            json={"name": "plex_server", "policy": "auto"},
            headers=auth_headers,
        )
        assert res2.status_code == 200
        assert res2.json()["policies"]["plex_server"] == "auto"

        # POST multiple policies
        res3 = client.post(
            "/api/docker/updates/policies",
            json={"policies": {"vaultwarden": "notify", "nextcloud": "off"}},
            headers=auth_headers,
        )
        assert res3.status_code == 200
        assert res3.json()["policies"]["vaultwarden"] == "notify"
        assert res3.json()["policies"]["nextcloud"] == "off"


@patch("backend.api.storage.get_storage_platform")
def test_storage_share_create_endpoint_with_quota_and_matrix(mock_get_platform, client, auth_headers):
    mock_adapter = MagicMock()
    mock_caps = MagicMock()
    mock_caps.is_observer_mode = False
    mock_adapter.get_capabilities.return_value = mock_caps
    mock_adapter.create_share.return_value = {
        "status": "created",
        "name": "documents",
        "quota_gb": 150,
        "user_permissions": {"john": "rw", "sarah": "ro"},
    }
    mock_get_platform.return_value = mock_adapter

    res = client.post(
        "/api/storage/shares",
        json={
            "name": "documents",
            "path": "/mnt/storage/documents",
            "quota_gb": 150,
            "user_permissions": {"john": "rw", "sarah": "ro"},
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "created"
    assert data["quota_gb"] == 150
    assert data["user_permissions"] == {"john": "rw", "sarah": "ro"}
    mock_adapter.create_share.assert_called_once()
