"""Code scanning 474-493: what was real is fixed, what was a guard one call away is now where it's used."""

import os
import ssl

import pytest


def test_a_version_is_never_restored_through_a_symlink_out_of_the_shares(pool_tree, tmp_path, monkeypatch):
    from backend.services import file_versions

    POOL_DIR = pool_tree
    secret = os.path.join(os.path.realpath(os.path.join(pool_tree, "escape")), "secret", "keep.txt")
    with open(secret, "w") as f:
        f.write("untouched")
    link = os.path.join(POOL_DIR, "media", "looks-normal.txt")
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(secret, link)
    src = tmp_path / "old.txt"
    src.write_text("old version")
    monkeypatch.setattr(file_versions, "version_path", lambda path, vid: str(src))
    try:
        with pytest.raises(PermissionError, match="outside the shared folders"):
            file_versions.restore_version(link, "v1", overwrite=True)
        with open(secret) as f:
            assert f.read() == "untouched"
        plain = os.path.join(POOL_DIR, "media", "plain.txt")
        with open(plain, "w") as f:
            f.write("now")
        assert file_versions.restore_version(plain, "v1", overwrite=True) == os.path.realpath(plain)
        with open(plain) as f:
            assert f.read() == "old version"
    finally:
        os.remove(link)


def test_mqtt_over_tls_asks_for_tls_1_2_at_least(monkeypatch):
    from backend.services import mqtt_lite

    seen = {}

    class Ctx:
        minimum_version = None

        def wrap_socket(self, raw, server_hostname=None):
            seen["min"] = self.minimum_version
            raise OSError("stop here")

    monkeypatch.setattr(mqtt_lite.socket, "create_connection", lambda addr, timeout=None: object())
    monkeypatch.setattr(mqtt_lite.ssl, "create_default_context", lambda: Ctx())
    with pytest.raises(OSError, match="stop here"):
        mqtt_lite.publish("broker.lan", 8883, [], tls=True)
    assert seen["min"] == ssl.TLSVersion.TLSv1_2


def test_the_space_result_file_stays_in_its_folder():
    from backend.services import storage_analyzer as sa

    base = os.path.normpath(sa.RESULT_DIR)
    for share in ("photos", "../../etc/passwd", "..", "a/b\\c\nd", ""):
        path = sa._result_path(share)
        assert os.path.dirname(path) == base and path.endswith(".json")


def test_settings_file_names_in_the_log_have_no_line_breaks():
    from backend import fsutil

    assert fsutil._shown("/data/x\nFAKE LINE\r.json") == "x?FAKE LINE?.json"


def test_the_logo_fetch_refuses_other_hosts_by_itself():
    from backend.services import catalog_logos

    with pytest.raises(ValueError, match="not a logo host"):
        catalog_logos.fetch("http://192.168.50.1/admin")
