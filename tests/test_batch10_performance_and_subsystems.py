import json
import os
from unittest.mock import MagicMock, patch

import pytest

from backend.hardware.disks import _parse_smart
from backend.hardware.led import (
    _close_serial_connection,
    _get_serial_connection,
    send_led_packet,
)


# ============================================================================
# 1. SMART JSON Parsing Tests (smartctl -j)
# ============================================================================


def test_parse_smart_nvme_json_healthy():
    sample_nvme_json = {
        "device": {"name": "/dev/nvme0n1", "type": "nvme"},
        "smart_status": {"passed": True},
        "temperature": {"current": 25},
        "nvme_smart_health_information_log": {
            "critical_warning": 0,
            "temperature": 25,
            "available_spare": 100,
            "available_spare_threshold": 1,
            "percentage_used": 0,
            "data_units_read": 28039687,
            "data_units_written": 1665680,
            "power_cycles": 839,
            "media_errors": 0,
        },
    }
    raw_str = json.dumps(sample_nvme_json)
    temp, health, metrics = _parse_smart(raw_str, is_nvme=True)

    assert temp == 25
    assert health == "ok"
    assert metrics["nvme_spare"] == 100
    assert metrics["nvme_spare_thresh"] == 1
    assert metrics["nvme_used"] == 0
    assert metrics["nvme_media_err"] == 0
    assert metrics["power_cycles"] == 839
    assert metrics["tbw_tb"] == 0.85
    assert metrics["critical_warning"] == "0x0"


def test_parse_smart_nvme_json_critical_spare_and_media_errors():
    sample_nvme_json = {
        "smart_status": {"passed": True},
        "temperature": {"current": 42},
        "nvme_smart_health_information_log": {
            "critical_warning": 2,
            "temperature": 42,
            "available_spare": 5,
            "available_spare_threshold": 10,
            "percentage_used": 95,
            "data_units_written": 10000000,
            "media_errors": 12,
        },
    }
    temp, health, metrics = _parse_smart(sample_nvme_json, is_nvme=True)

    assert temp == 42
    assert health == "crit"
    assert metrics["nvme_spare"] == 5
    assert metrics["nvme_spare_thresh"] == 10
    assert metrics["nvme_media_err"] == 12


def test_parse_smart_sata_json_healthy():
    sample_sata_json = {
        "device": {"name": "/dev/sda", "type": "sat"},
        "smart_status": {"passed": True},
        "temperature": {"current": 37},
        "power_cycle_count": 85,
        "ata_smart_attributes": {
            "table": [
                {"id": 5, "name": "Reallocated_Sector_Ct", "raw": {"value": 0}},
                {"id": 197, "name": "Current_Pending_Sector", "raw": {"value": 0}},
                {"id": 198, "name": "Offline_Uncorrectable", "raw": {"value": 0}},
                {"id": 199, "name": "UDMA_CRC_Error_Count", "raw": {"value": 0}},
                {"id": 194, "name": "Temperature_Celsius", "raw": {"value": 37, "string": "37"}},
                {"id": 241, "name": "Total_LBAs_Written", "raw": {"value": 72850040380}},
            ]
        },
    }
    temp, health, metrics = _parse_smart(sample_sata_json, is_nvme=False)

    assert temp == 37
    assert health == "ok"
    assert metrics["realloc"] == 0
    assert metrics["pending"] == 0
    assert metrics["offline"] == 0
    assert metrics["crc"] == 0
    assert metrics["power_cycles"] == 85
    assert metrics["tbw_tb"] == 37.3  # (72850040380 * 512) / 1e12


def test_parse_smart_sata_json_warning_and_critical():
    # Warning case: reallocated sectors
    sata_warn = {
        "smart_status": {"passed": True},
        "temperature": {"current": 35},
        "ata_smart_attributes": {
            "table": [
                {"id": 5, "name": "Reallocated_Sector_Ct", "raw": {"value": 16}},
                {"id": 197, "name": "Current_Pending_Sector", "raw": {"value": 0}},
            ]
        },
    }
    temp, health, metrics = _parse_smart(sata_warn, is_nvme=False)
    assert health == "warn"
    assert metrics["realloc"] == 16

    # Critical case: current pending sector > 0
    sata_crit = {
        "smart_status": {"passed": True},
        "temperature": {"current": 35},
        "ata_smart_attributes": {
            "table": [
                {"id": 5, "name": "Reallocated_Sector_Ct", "raw": {"value": 0}},
                {"id": 197, "name": "Current_Pending_Sector", "raw": {"value": 4}},
            ]
        },
    }
    _, health_crit, metrics_crit = _parse_smart(sata_crit, is_nvme=False)
    assert health_crit == "crit"
    assert metrics_crit["pending"] == 4


def test_parse_smart_fallback_on_corrupt_json():
    # If JSON is corrupted or invalid, it gracefully falls back to text parsing without exception
    corrupt_json = '{ "device": { broken json'
    temp, health, metrics = _parse_smart(corrupt_json, is_nvme=False)
    assert temp is None
    assert health == "ok"
    assert metrics["realloc"] == 0


# ============================================================================
# 2. Persistent Serial Connection Tests (backend/hardware/led.py)
# ============================================================================


def test_persistent_serial_reuse_and_backoff(monkeypatch):
    _close_serial_connection()
    mock_file = MagicMock()
    mock_open = MagicMock(return_value=mock_file)

    monkeypatch.setattr("backend.hardware.led.find_led_port", lambda: "/dev/ttyACM0")
    monkeypatch.setattr("os.path.exists", lambda p: True)
    monkeypatch.setattr("builtins.open", mock_open)
    monkeypatch.setattr("backend.hardware.led.serial", None)

    # First write should open the handle
    ok, msg = send_led_packet(6, 255, 0, 0)
    assert ok is True
    assert mock_open.call_count == 1
    assert mock_file.write.call_count == 1

    # Second write should REUSE the open handle without re-opening
    ok, msg = send_led_packet(6, 0, 255, 0)
    assert ok is True
    assert mock_open.call_count == 1  # No additional open call!
    assert mock_file.write.call_count == 2

    # Simulate write failure (e.g. broken pipe / USB unplug)
    mock_file.write.side_effect = OSError("Broken pipe")
    ok, msg = send_led_packet(6, 0, 0, 255)
    assert ok is False
    assert "Broken pipe" in msg

    # Immediate next attempt should be throttled by backoff interval
    ok2, msg2 = send_led_packet(6, 255, 255, 255)
    assert ok2 is False
    assert "Serial connection unavailable" in msg2

    _close_serial_connection()


# ============================================================================
# 3. Direct Physical Verification in Copy Engine (backend/services/copy_engine.py)
# ============================================================================


@pytest.mark.asyncio
async def test_copy_engine_invokes_fdatasync_and_fadvise(tmp_path, monkeypatch):
    from backend.services.copy_engine import _do_copy
    from backend.state import Z_STATE

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    test_file = src_dir / "photo.jpg"
    test_file.write_bytes(b"EXIF_IMAGE_DATA_1234567890" * 100)

    fdatasync_called = False
    fadvise_called = False

    def mock_fdatasync(fd):
        nonlocal fdatasync_called
        fdatasync_called = True

    def mock_fadvise(fd, offset, length, advice):
        nonlocal fadvise_called
        if advice == getattr(os, "POSIX_FADV_DONTNEED", 4):
            fadvise_called = True

    monkeypatch.setattr(os, "fdatasync", mock_fdatasync)
    if hasattr(os, "posix_fadvise"):
        monkeypatch.setattr(os, "posix_fadvise", mock_fadvise)
    else:
        monkeypatch.setattr(os, "posix_fadvise", mock_fadvise, raising=False)
        monkeypatch.setattr(os, "POSIX_FADV_DONTNEED", 4, raising=False)

    monkeypatch.setattr("backend.services.copy_engine.resolve_copy_destination", lambda d: str(dst_dir))
    monkeypatch.setattr("glob.glob", lambda pat: ["/sys/block/sdc"])
    monkeypatch.setattr("os.readlink", lambda p: "usb/1:0:0:1/block/sdc")
    monkeypatch.setattr("backend.services.copy_engine.HOST_DEV", str(tmp_path))
    monkeypatch.setattr("backend.services.copy_engine.HOST_SYS", str(tmp_path))
    monkeypatch.setattr("backend.services.copy_engine.HOST_PROC", str(tmp_path))

    # Fake sysfs block size
    size_file = tmp_path / "block" / "sdc" / "size"
    size_file.parent.mkdir(parents=True, exist_ok=True)
    size_file.write_text("1000\n")

    # Fake mounts file showing sdc mounted at src_dir
    mounts_file = tmp_path / "mounts"
    mounts_file.write_text(f"/dev/sdc {str(src_dir)} vfat rw 0 0\n")

    Z_STATE.copy_active = False
    Z_STATE.copy_status = "idle"
    Z_STATE.copy_abort_flag = False

    # Avoid 8s UI hold delay in finally block
    monkeypatch.setattr("time.sleep", lambda s: None)

    await _do_copy(
        {
            "source": "sd",
            "dest": str(dst_dir),
            "use_exif": False,
            "verify_checksum": True,
        }
    )

    assert Z_STATE.copy_progress["files_done"] == 1
    assert Z_STATE.copy_progress["file"] == "Finished successfully."
    assert fdatasync_called is True
    assert fadvise_called is True
    assert (dst_dir / "photo.jpg").exists()
    assert (dst_dir / "photo.jpg").read_bytes() == test_file.read_bytes()
