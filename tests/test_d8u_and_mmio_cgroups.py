"""
Unit & Integration tests for Zettlab D8 Ultra hardware detection and MMIO cgroup error handling.
"""

from unittest.mock import MagicMock, patch
import pytest

from backend.hardware.chassis import ChassisEngine
from backend.hardware.fans import ZettlabMmioFanController, is_zettlab_appliance
from backend.hardware.hal import PhysicalDiskRecord
from backend.hardware.storage import detect_chassis_model, get_chassis_friendly_name
from backend.state import Z_STATE


def test_detect_chassis_d8u_via_unraid_model(monkeypatch):
    """Verifies that an Unraid host with SYS_MODEL='Zettlab D8 Ultra' is correctly detected as d8u,

    even when the physical motherboard DMI reports 'WY120' or 'D6 Ultra'.
    """
    monkeypatch.setattr(
        "backend.hardware.storage._read_dmi_text",
        lambda f: {"product_name": "D6 Ultra", "board_name": "WY120", "sys_vendor": "Default string"}.get(f, ""),
    )
    monkeypatch.setattr(
        "backend.hardware.unraid.read_unraid_status",
        lambda: {"available": True, "model": "Zettlab D8 Ultra"},
    )
    # Clear cached model
    Z_STATE.cached_chassis_model = None

    model = detect_chassis_model(force=True)
    assert model == "d8u"
    assert get_chassis_friendly_name(model) == "Zettlab D8 Ultra (8-Bay)"


def test_detect_chassis_d8u_via_bay_count_override(monkeypatch):
    """Verifies that a generic system with WY120 motherboard but 8 physical bay drives is detected as d8u."""
    monkeypatch.setattr(
        "backend.hardware.storage._read_dmi_text",
        lambda f: {"product_name": "D6 Ultra", "board_name": "WY120", "sys_vendor": "Default string"}.get(f, ""),
    )
    monkeypatch.setattr(
        "backend.hardware.unraid.read_unraid_status",
        lambda: {"available": False, "model": ""},
    )

    mock_disks = [
        PhysicalDiskRecord(
            dev_name=f"sd{chr(ord('a') + i)}",
            canonical_id=f"wwn-0x5000cca2{i}",
            dev_path=f"/dev/sd{chr(ord('a') + i)}",
            size_bytes=16000000000000,
            model="WDC WD161KRYZ",
            serial=f"WD-WMC4N0{i}",
            transport="sata",
            role="data",
            removable=False,
        )
        for i in range(8)
    ]
    monkeypatch.setattr(
        "backend.hardware.hal.DiskDiscoveryHAL.discover_physical_disks",
        lambda: mock_disks,
    )
    Z_STATE.cached_chassis_model = None

    model = detect_chassis_model(force=True)
    assert model == "d8u"
    assert get_chassis_friendly_name(model) == "Zettlab D8 Ultra (8-Bay)"


def test_chassis_engine_status_d8u(monkeypatch):
    """Verifies ChassisEngine synthesizes 8 bays and tower_desktop profile for D8 Ultra."""
    monkeypatch.setattr("backend.hardware.storage.detect_chassis_model", lambda **kw: "d8u")

    mock_disks = [
        PhysicalDiskRecord(
            dev_name=f"sd{chr(ord('a') + i)}",
            canonical_id=f"wwn-0x5000cca2{i}",
            dev_path=f"/dev/sd{chr(ord('a') + i)}",
            size_bytes=16000000000000,
            model="WDC WD161KRYZ",
            serial=f"WD-WMC4N0{i}",
            transport="sata",
            role="data",
            removable=False,
        )
        for i in range(8)
    ]
    monkeypatch.setattr(
        "backend.hardware.hal.DiskDiscoveryHAL.discover_physical_disks",
        lambda: mock_disks,
    )
    monkeypatch.setattr(
        ChassisEngine,
        "load_bay_mapping_config",
        lambda: {"profile": "auto", "total_bays": None, "mappings": []},
    )

    status = ChassisEngine.get_chassis_status()
    assert status["chassis_model"] == "ZETTLAB D8U"
    assert status["chassis_label"] == "Zettlab D8 Ultra (8-Bay)"
    assert status["total_bays"] == 8
    assert status["profile"] == "tower_desktop"


def test_is_zettlab_appliance_d8u(monkeypatch):
    """Verifies is_zettlab_appliance returns True when running on D8 Ultra."""
    monkeypatch.setattr("backend.hardware.storage.detect_chassis_model", lambda **kw: "d8u")
    assert is_zettlab_appliance() is True


def test_mmio_fan_controller_permission_error(monkeypatch):
    """Verifies that PermissionError on /dev/mem logs an informative cgroup warning and records an event."""
    monkeypatch.setenv("FORCE_ZETTLAB_MMIO", "1")
    ctrl = ZettlabMmioFanController("/dev/mem")

    monkeypatch.setattr("os.path.exists", lambda p: p == "/dev/mem")

    def mock_open(*args, **kwargs):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("os.open", mock_open)

    events_recorded = []
    monkeypatch.setattr(
        "backend.state.add_event", lambda level, title, msg: events_recorded.append((level, title, msg))
    )

    assert ctrl._ensure_mapped() is False
    assert len(events_recorded) == 1
    assert events_recorded[0][0] == "warning"
    assert "Permission Denied" in events_recorded[0][1]
    assert "--device-cgroup-rule='c 1:1 rwm'" in events_recorded[0][2]
