"""SET-14: the download catalog's checksums can match a file, and no entry points at an address whose file changes."""

import re

from backend.services import vm_store


def _entries():
    for name in dir(vm_store):
        value = getattr(vm_store, name)
        if isinstance(value, list) and value and isinstance(value[0], dict) and "download_url" in value[0]:
            return value
    raise AssertionError("no catalog list in vm_store")


def test_every_checksum_is_a_sha256():
    for e in _entries():
        if e.get("sha256"):
            assert re.fullmatch(r"[0-9a-f]{64}", e["sha256"]), e["id"]


def test_no_moving_addresses():
    for e in _entries():
        assert "stable-virtio" not in e["download_url"] and "latest" not in e["download_url"], e["id"]


def test_the_values_checked_against_the_vendors():
    by_id = {e["id"]: e for e in _entries()}
    assert by_id["truenas-scale"]["sha256"].startswith("471543fb")
    assert by_id["fedora-40"]["sha256"].startswith("32d9ab17")
    assert by_id["virtio-win"]["download_url"].endswith("virtio-win-0.1.262.iso")
