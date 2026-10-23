"""Leads the 2026-10 security audit could not confirm, fixed defensively: proxy-SSO writes
need this server's Origin, VM backup restore checks what the archive says, NFS export
settings cannot inject lines or leave the pool, and CI jobs get least privilege."""

import io
import json
import os
import tarfile

import pytest

from backend import config

# ---------------------------------------------------------------- proxy SSO CSRF


@pytest.fixture
def proxy_sso(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_PROXY_SSO", True)
    monkeypatch.setattr(config, "TRUSTED_PROXIES", ["testclient", "127.0.0.1"])


def test_proxy_sso_writes_need_this_servers_origin(client, proxy_sso):
    sso = {"Remote-User": "admin"}
    assert client.get("/api/auth/me", headers=sso).status_code == 200
    r = client.post("/api/auth/ticket", headers={**sso, "Origin": "http://cross-site.test"})
    assert r.status_code == 403 and r.json().get("error") == "csrf_blocked"
    assert client.post("/api/auth/ticket", headers=sso).status_code == 403  # no Origin or Referer
    assert client.post("/api/auth/ticket", headers={**sso, "Origin": "http://testserver"}).status_code == 200


def test_api_token_through_the_proxy_authenticates_as_the_token(client, proxy_sso, token):
    r = client.post("/api/auth/ticket", headers={"Remote-User": "admin", "Authorization": f"Bearer {token}"})
    assert r.status_code == 200


# ---------------------------------------------------------------- VM backup restore


def _vm_archive(path, vm_config):
    def add(tar, name, data):
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    with tarfile.open(path, "w:gz") as tar:
        add(tar, "manifest.json", json.dumps({"vm_config": vm_config}).encode())
        add(tar, "vm_data/marker.txt", b"dummy")
        add(tar, "vm_data/../escape.txt", b"dummy")


def test_vm_restore_ignores_the_archive_folder_and_checks_settings(tmp_path):
    from backend.services import app_backup

    vm_id = "vmtest_restore"
    archive = tmp_path / "vm.tar.gz"
    outside = tmp_path / "outside"
    _vm_archive(
        archive,
        {"id": vm_id, "name": "t", "vm_dir": str(outside), "disk_bus": "virtio", "mac": "52:54:00:00:00:01"},
    )
    app_backup.save_app_backup_record(
        {"id": "vbk_ok", "type": "vm", "vm_id": vm_id, "vm_name": "t", "filepath": str(archive)}
    )
    app_backup.restore_vm_backup("vbk_ok")

    vm_dir = os.path.join(app_backup.DATA_DIR, "vms", vm_id)
    assert os.path.isfile(os.path.join(vm_dir, "marker.txt"))
    assert not outside.exists()
    assert not os.path.exists(os.path.join(app_backup.DATA_DIR, "vms", "escape.txt"))
    with open(os.path.join(app_backup.DATA_DIR, "vms.json"), encoding="utf-8") as f:
        stored = next(v for v in json.load(f) if v["id"] == vm_id)
    assert stored["vm_dir"] == vm_dir


@pytest.mark.parametrize(
    "bad",
    [
        {"disk_path": "/dev/sda"},
        {"disk_bus": "virtio,file=/etc/shadow"},
        {"disk_format": "raw,readonly=off"},
        {"mac": "52:54:00:00:00:01,id=x"},
        {"id": "other-vm"},
    ],
)
def test_vm_restore_refuses_unsafe_settings(tmp_path, bad):
    from backend.services import app_backup

    vm_id = "vmtest_bad"
    archive = tmp_path / "bad.tar.gz"
    _vm_archive(archive, {"id": vm_id, "name": "t", **bad})
    app_backup.save_app_backup_record(
        {"id": "vbk_bad", "type": "vm", "vm_id": vm_id, "vm_name": "t", "filepath": str(archive)}
    )
    with pytest.raises(ValueError):
        app_backup.restore_vm_backup("vbk_bad")


# ---------------------------------------------------------------- NFS exports


def test_nfs_export_fields_cannot_add_lines():
    from pydantic import ValidationError

    from backend.services.nfs_engine import NfsEngine, NfsExportRule

    rule = NfsExportRule(name="s", path="/mnt/user/s", comment="note\n/etc *(rw)")
    engine = NfsEngine.__new__(NfsEngine)
    engine._exports = {"s": rule}
    content = engine.generate_exports_file_content()
    assert "\n/etc" not in content and "# note /etc *(rw)" in content
    for bad in (
        {"clients": "*\n/etc *(rw,no_root_squash)"},
        {"clients": "host1 host2(rw)"},
        {"squash": "no_root_squash,rw"},
        {"path": '/mnt/user/s" *(rw) "/etc'},
    ):
        with pytest.raises(ValidationError):
            NfsExportRule(**{"name": "s", "path": "/mnt/user/s", **bad})


def test_generic_linux_share_stays_inside_the_pool(tmp_path):
    from backend.hardware.pal_storage import GenericLinuxStorageAdapter

    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path / "pool"))
    target = tmp_path / "outside-share"
    with pytest.raises(ValueError):
        adapter.create_share("s", str(target), export_smb=False, export_nfs=True)
    assert not target.exists()


# ---------------------------------------------------------------- CI least privilege


def test_ci_jobs_get_least_privilege():
    import yaml

    path = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "ci.yml")
    with open(path, encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    assert wf["permissions"] == {"contents": "read"}
    jobs = wf["jobs"]
    for name in ("lint-and-test", "frontend", "e2e-integration"):
        assert "permissions" not in jobs[name], name
    for name in ("lint-and-test", "frontend", "e2e-integration"):
        checkouts = [s for s in jobs[name]["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
        assert checkouts and all(s.get("with", {}).get("persist-credentials") is False for s in checkouts), name
    assert jobs["build-and-push"]["permissions"] == {"contents": "read", "packages": "write", "id-token": "write"}
    assert jobs["create-release"]["permissions"] == {"contents": "write"}
