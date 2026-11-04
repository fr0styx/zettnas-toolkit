"""DRV-9: a SATA drive seen from a container gets its real serial and full model without waking it,
so Drive Health doesn't list a drive that is still in the box as taken out."""

from backend.hardware.hal import DiskDiscoveryHAL
from backend.services import drive_registry


def test_the_by_id_link_names_the_serial_and_full_model():
    model, serial = DiskDiscoveryHAL._fill_identity(
        "sda", "/host/dev/disk/by-id/ata-ST22000DM000-3Y6103_ZXA0T9C8", "ST22000DM000-3Y6", "Unknown"
    )
    assert (model, serial) == ("ST22000DM000-3Y6103", "ZXA0T9C8")
    model, serial = DiskDiscoveryHAL._fill_identity(
        "sdc", "/dev/disk/by-id/ata-WDC_WD40EFRX-68N32N0_WD-WCC7K1234567", "WDC WD40EFRX-68N", ""
    )
    assert (model, serial) == ("WDC WD40EFRX-68N32N0", "WD-WCC7K1234567")


def test_a_known_serial_and_a_different_model_are_kept():
    assert DiskDiscoveryHAL._fill_identity(
        "nvme0n1", "/dev/disk/by-id/nvme-WD_BLACK_SN7100_1TB_25235H801651", "WD_BLACK SN7100 1TB", "25235H801651"
    ) == ("WD_BLACK SN7100 1TB", "25235H801651")
    assert DiskDiscoveryHAL._fill_identity("sda", "/dev/disk/by-id/ata-OTHER_X1", "Generic Storage", "S1") == (
        "Generic Storage",
        "S1",
    )


def test_without_a_link_the_kernels_serial_page_is_read(tmp_path, monkeypatch):
    dev = tmp_path / "block" / "sdb" / "device"
    dev.mkdir(parents=True)
    (dev / "vpd_pg80").write_bytes(b"\x00\x80\x00\x14            ZXA1A40W")
    monkeypatch.setattr(DiskDiscoveryHAL, "_resolve_sys_root", classmethod(lambda cls: str(tmp_path)))
    assert DiskDiscoveryHAL._fill_identity("sdb", None, "ST22000DM000-3Y6", "Unknown") == (
        "ST22000DM000-3Y6",
        "ZXA1A40W",
    )
    assert DiskDiscoveryHAL._fill_identity("sdz", None, "X", "Unknown") == ("X", "Unknown")


def test_a_drive_in_the_box_is_not_taken_out(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_registry, "SEEN_FILE", str(tmp_path / "seen.json"))
    drive_registry.note_present([{"serial": "ZXA0T9C8", "model": "ST22000DM000-3Y6103", "dev": "sda"}])
    assert drive_registry.taken_out(["Unknown", "ZXA1A40W"])  # the old discovery: shown as taken out
    assert drive_registry.taken_out(["ZXA0T9C8", "ZXA1A40W"]) == []
