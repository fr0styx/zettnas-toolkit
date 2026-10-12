"""
Tests for Phase 3: DMTF Redfish REST API and SNMP v2c/v3 Monitoring & MIB Management.
"""

from backend.state import Z_STATE


def test_redfish_service_root(client):
    res = client.get("/redfish/v1/")
    assert res.status_code == 200
    data = res.json()
    assert data["RedfishVersion"] == "1.15.0"
    assert data["Id"] == "RootService"
    assert "Systems" in data
    assert "Chassis" in data
    assert "Storage" in data


def test_redfish_chassis_and_thermal(client):
    # Seed cached stats
    Z_STATE.cached_stats = {
        "chassis": "d6u",
        "cpu": {"temp": 42.5, "util": 15.0},
        "disks": [
            {"dev": "sda", "name": "sda", "temp": 35.0, "standby": False, "size_bytes": 4000000000000},
            {"dev": "nvme0n1", "name": "nvme0n1", "temp": 40.0, "standby": False, "size_bytes": 1000000000000},
        ],
        "fans": [1200, 850],
        "mem": {"total_gb": 32.0, "used_gb": 8.0, "pct": 25.0},
    }

    # 1. Chassis/1
    res = client.get("/redfish/v1/Chassis/1")
    assert res.status_code == 200
    chassis = res.json()
    assert chassis["Id"] == "1"
    assert chassis["PowerState"] == "On"
    assert chassis["ChassisType"] == "RackMount"

    # 2. Chassis/1/Thermal
    res = client.get("/redfish/v1/Chassis/1/Thermal")
    assert res.status_code == 200
    thermal = res.json()
    assert "Temperatures" in thermal
    assert "Fans" in thermal

    # Find CPU temp
    cpu_sensor = next((s for s in thermal["Temperatures"] if s["MemberId"] == "CPU"), None)
    assert cpu_sensor is not None
    assert cpu_sensor["ReadingCelsius"] == 42.5

    # Check Fans
    assert len(thermal["Fans"]) == 2
    assert thermal["Fans"][0]["Reading"] == 1200


def test_redfish_systems_and_storage(client):
    # 1. Systems/1
    res = client.get("/redfish/v1/Systems/1")
    assert res.status_code == 200
    sys_data = res.json()
    assert sys_data["Id"] == "1"
    assert sys_data["PowerState"] == "On"
    assert "MemorySummary" in sys_data

    # 2. Storage/1
    res = client.get("/redfish/v1/Storage/1")
    assert res.status_code == 200
    storage = res.json()
    assert "Drives" in storage

    # 3. Individual Drive
    res = client.get("/redfish/v1/Storage/1/Drives/sda")
    assert res.status_code == 200
    drive = res.json()
    assert drive["Id"] == "sda"
    assert drive["MediaType"] == "HDD"
    assert drive["Protocol"] == "SATA"


def test_snmp_api_suite(client, auth_headers):
    # 1. SNMP Status
    res = client.get("/api/snmp/status", headers=auth_headers)
    assert res.status_code == 200
    status = res.json()
    assert status["enabled"] is True
    assert status["port"] == 161
    assert status["enterprise_oid"] == "1.3.6.1.4.1.58925"

    # 2. SNMP Config (Masked credentials)
    res = client.get("/api/snmp/config", headers=auth_headers)
    assert res.status_code == 200
    cfg = res.json()
    assert "community" not in cfg
    assert "community_masked" in cfg
    assert cfg["v3_user"] == "zettnas_admin"

    # 3. Update SNMP Config
    new_cfg = {
        "enabled": True,
        "port": 1161,
        "version": "both",
        "community": "secret_monitoring_comm",
        "v3_user": "sec_operator",
        "v3_security_level": "authPriv",
    }
    res = client.post("/api/snmp/config", json=new_cfg, headers=auth_headers)
    assert res.status_code == 200

    # Verify update persisted and masked
    res = client.get("/api/snmp/config", headers=auth_headers)
    assert res.status_code == 200
    updated = res.json()
    assert updated["port"] == 1161
    assert updated["v3_user"] == "sec_operator"
    assert updated["community_masked"].startswith("sec")

    # 4. Enterprise MIB file download
    res = client.get("/api/snmp/mib")
    assert res.status_code == 200
    text = res.text
    assert "ZETTLAB-ZETTNAS-MIB DEFINITIONS ::= BEGIN" in text
    assert "enterprises 58925" in text
    assert "zettnasCpuTemp" in text

    # 5. Evaluated Live OIDs
    res = client.get("/api/snmp/oids", headers=auth_headers)
    assert res.status_code == 200
    oids = res.json()
    assert "1.3.6.1.4.1.58925.1.0" in oids
    assert "1.3.6.1.4.1.58925.2.0" in oids
    assert oids["1.3.6.1.4.1.58925.2.0"]["name"] == "zettnasCpuTemp"
