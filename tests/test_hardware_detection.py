import os

from backend.hardware.chassis import ChassisEngine


def test_detect_hardware_features_custom_appliance(monkeypatch):
    """Verifies that Zettlab appliances are recognized as custom hardware with LCD, MCU, COPY button, and SD slot."""
    monkeypatch.setattr(ChassisEngine, "_read_dmi_sys_vendor", lambda: "Zettlab")
    monkeypatch.setattr(ChassisEngine, "_read_dmi_product_name", lambda: "D6 Ultra")
    monkeypatch.setattr("backend.hardware.led.find_led_port", lambda: "/dev/ttyACM0")

    features = ChassisEngine.detect_hardware_features()

    assert features["sys_vendor"] == "Zettlab"
    assert features["product_name"] == "D6 Ultra"
    assert features["is_zettlabs"] is True
    assert features["is_custom_appliance"] is True
    assert features["has_copy_button"] is True
    assert features["has_sd_slot"] is True
    assert features["has_mcu"] is True
    assert features["has_custom_hardware"] is True
    assert "lcd_resolution" in features


def test_detect_hardware_features_generic_server(monkeypatch):
    """Verifies that generic enterprise servers (Dell, HP, Supermicro, VMs) are cleanly recognized as non-custom hardware."""
    monkeypatch.setattr(ChassisEngine, "_read_dmi_sys_vendor", lambda: "Dell Inc.")
    monkeypatch.setattr(ChassisEngine, "_read_dmi_product_name", lambda: "PowerEdge R730")
    monkeypatch.setattr("backend.hardware.led.find_led_port", lambda: None)
    monkeypatch.setattr("os.path.exists", lambda p: False)

    features = ChassisEngine.detect_hardware_features()

    assert features["sys_vendor"] == "Dell Inc."
    assert features["product_name"] == "PowerEdge R730"
    assert features["is_zettlabs"] is False
    assert features["is_custom_appliance"] is False
    assert features["has_lcd"] is False
    assert features["has_mcu"] is False
    assert features["has_copy_button"] is False
    assert features["has_sd_slot"] is False
    assert features["has_custom_hardware"] is False
    assert features["lcd_resolution"]["spec"] == "N/A"


def test_detect_hardware_features_d4_wy110(monkeypatch):
    """Verifies that Zettlab D4 with WY110 board is recognized as custom Zettlab appliance even if product_name is Default string."""
    monkeypatch.setattr(ChassisEngine, "_read_dmi_sys_vendor", lambda: "Default string")
    monkeypatch.setattr(ChassisEngine, "_read_dmi_product_name", lambda: "Default string")
    monkeypatch.setattr(
        ChassisEngine,
        "_read_dmi_field",
        lambda f: "WY110" if f == "board_name" else ("Zettlab" if f == "sys_vendor" else ""),
    )
    monkeypatch.setattr("backend.hardware.led.find_led_port", lambda: "/dev/ttyACM0")

    features = ChassisEngine.detect_hardware_features()
    assert features["is_zettlabs"] is True
    assert features["is_custom_appliance"] is True


def test_detect_chassis_model_d4_dmi(monkeypatch):
    """Verifies that detect_chassis_model returns 'd4' when WY110 or D4 is present in DMI."""
    from backend.hardware.storage import detect_chassis_model, get_chassis_friendly_name

    monkeypatch.setattr(
        "backend.hardware.storage._read_dmi_text",
        lambda f: "WY110" if f == "board_name" else ("Zettlab" if f == "sys_vendor" else ""),
    )
    chassis = detect_chassis_model(force=True)
    assert chassis == "d4"
    assert get_chassis_friendly_name(chassis) == "Zettlab D4 (4-Bay)"


def test_detect_chassis_model_filters_nvme_and_usb():
    """Verifies that 4 SATA drives + 2 NVMe drives + 1 USB boot drive (7 total) correctly classifies as D4 (4-bay), NOT D8U."""
    from unittest.mock import patch

    from backend.hardware.hal import PhysicalDiskRecord
    from backend.hardware.storage import detect_chassis_model

    fake_records = [
        # 4 SATA data drives
        PhysicalDiskRecord(
            dev_name=f"sd{chr(98 + i)}",
            canonical_id=f"ata-DISK_{i}",
            dev_path=f"/dev/sd{chr(98 + i)}",
            transport="sata",
            controller_driver="ahci",
            is_rotational=True,
            role="data",
            removable=False,
        )
        for i in range(4)
    ] + [
        # 2 M.2 NVMe SSDs
        PhysicalDiskRecord(
            dev_name="nvme0n1",
            canonical_id="nvme-SAMSUNG_1",
            dev_path="/dev/nvme0n1",
            transport="nvme",
            controller_driver="nvme",
            is_rotational=False,
            role="cache",
            removable=False,
        ),
        PhysicalDiskRecord(
            dev_name="nvme1n1",
            canonical_id="nvme-SAMSUNG_2",
            dev_path="/dev/nvme1n1",
            transport="nvme",
            controller_driver="nvme",
            is_rotational=False,
            role="cache",
            removable=False,
        ),
        # 1 USB Flash Boot Drive (e.g. Unraid flash sda)
        PhysicalDiskRecord(
            dev_name="sda",
            canonical_id="usb-SanDisk_Cruzer",
            dev_path="/dev/sda",
            transport="usb",
            controller_driver="uas",
            is_rotational=False,
            role="os",
            removable=True,
        ),
    ]

    with (
        patch("backend.hardware.storage._read_dmi_text", return_value=""),
        patch("backend.hardware.chassis.ChassisEngine.load_bay_mapping_config", return_value={}),
        patch("backend.hardware.hal.DiskDiscoveryHAL.discover_physical_disks", return_value=fake_records),
    ):
        model = detect_chassis_model(force=True)
        # MUST be detected as d4 (4-bay), NOT d8u
        assert model == "d4"


def test_get_chassis_status_d4_defaults_to_4_bays():
    """Verifies that on a Zettlab D4 appliance with 2 populated drives, total_bays defaults to 4."""
    from unittest.mock import patch

    from backend.hardware.hal import PhysicalDiskRecord

    fake_disks = [
        PhysicalDiskRecord(
            dev_name="sdb",
            canonical_id="ata-DISK_1",
            dev_path="/dev/sdb",
            transport="sata",
            controller_driver="ahci",
            is_rotational=True,
            role="data",
        ),
        PhysicalDiskRecord(
            dev_name="sdc",
            canonical_id="ata-DISK_2",
            dev_path="/dev/sdc",
            transport="sata",
            controller_driver="ahci",
            is_rotational=True,
            role="data",
        ),
    ]

    with (
        patch("backend.hardware.chassis.DiskDiscoveryHAL.discover_physical_disks", return_value=fake_disks),
        patch(
            "backend.hardware.chassis.ChassisEngine.load_bay_mapping_config",
            return_value={"profile": "auto", "mappings": []},
        ),
        patch(
            "backend.hardware.chassis.ChassisEngine._read_dmi_field",
            lambda f: "WY110" if f == "board_name" else "",
        ),
        patch("backend.hardware.chassis.ChassisEngine._read_dmi_product_name", return_value="WY110"),
    ):
        status = ChassisEngine.get_chassis_status()
        assert status["chassis_model"] == "ZETTLAB D4"
        assert status["chassis_label"] == "Zettlab D4 (4-Bay)"
        assert status["total_bays"] == 4
        assert status["profile"] == "tower_desktop"
