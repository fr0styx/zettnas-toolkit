"""The UPS found by the last scan is read directly, without a new device scan (PERF-1)."""

from types import SimpleNamespace

from backend.hardware import ups


def _fake_ioctl(fd, req, buf):
    buf[1] = 87  # every feature report answers 87 in its first byte


def _cache(tmp_path, monkeypatch):
    node = tmp_path / "hidraw0"
    node.mkdir()
    char = tmp_path / "dev-hidraw0"
    char.write_bytes(b"")
    monkeypatch.setattr(ups, "fcntl", SimpleNamespace(ioctl=_fake_ioctl))
    ups._HID_UPS_CACHE.clear()
    ups._HID_UPS_CACHE.update(
        node_dir=str(node), char=str(char), vid="04d8", pid="d005", name="Test UPS", mapping={(0x85, 0x66): (1, 0, 0)}
    )
    return char


def test_the_known_device_is_read_without_a_scan(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch)
    monkeypatch.setattr(ups, "_parse_hid_report_descriptor", lambda *a: (_ for _ in ()).throw(AssertionError("parsed")))
    real_listdir = ups.os.listdir

    def no_hidraw_scan(path):
        assert "hidraw" not in str(path), "scanned hidraw devices"
        return real_listdir(path)

    monkeypatch.setattr(ups.os, "listdir", no_hidraw_scan)
    monkeypatch.setattr(ups.os.path, "isdir", lambda p: "power_supply" not in str(p) and real_isdir(p))
    out = ups._query_direct_usb()
    assert out["BCHARGE"] == "87" and out["PROTOCOL"] == "direct_usb_hid" and out["MODEL"] == "Test UPS"


real_isdir = ups.os.path.isdir


def test_a_device_that_is_gone_is_forgotten(tmp_path, monkeypatch):
    char = _cache(tmp_path, monkeypatch)
    char.unlink()
    assert ups._cached_hid_ups() is None
    assert ups._HID_UPS_CACHE == {}


def test_status_is_cached_for_at_least_ten_seconds():
    assert ups._UPS_CACHE_TTL >= 10
