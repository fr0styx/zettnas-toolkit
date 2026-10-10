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
    assert features["is_custom_appliance"] is True
    assert features["has_copy_button"] is True
    assert features["has_sd_slot"] is True
    assert features["has_mcu"] is True
    assert features["has_custom_hardware"] is True


def test_detect_hardware_features_generic_server(monkeypatch):
    """Verifies that generic enterprise servers (Dell, HP, Supermicro, VMs) are cleanly recognized as non-custom hardware."""
    monkeypatch.setattr(ChassisEngine, "_read_dmi_sys_vendor", lambda: "Dell Inc.")
    monkeypatch.setattr(ChassisEngine, "_read_dmi_product_name", lambda: "PowerEdge R730")
    monkeypatch.setattr("backend.hardware.led.find_led_port", lambda: None)
    monkeypatch.setattr("os.path.exists", lambda p: False)

    features = ChassisEngine.detect_hardware_features()

    assert features["sys_vendor"] == "Dell Inc."
    assert features["product_name"] == "PowerEdge R730"
    assert features["is_custom_appliance"] is False
    assert features["has_lcd"] is False
    assert features["has_mcu"] is False
    assert features["has_copy_button"] is False
    assert features["has_sd_slot"] is False
    assert features["has_custom_hardware"] is False
