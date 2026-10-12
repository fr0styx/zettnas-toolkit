"""
ZettNAS Toolkit - DMTF Redfish Scalable Platforms Management API (Phase 3)
Provides high-performance, DMTF-compliant RESTful telemetry (< 2ms response time)
served directly from in-memory system state without blocking disk or subprocess I/O.
"""

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Response
from backend.state import Z_STATE
from backend import __version__

router = APIRouter(tags=["Redfish"])

REDFISH_HEADERS = {
    "OData-Version": "4.0",
    "Content-Type": "application/json;charset=utf-8",
}


def _get_stats() -> Dict[str, Any]:
    return getattr(Z_STATE, "cached_stats", {}) or {}


@router.get("", include_in_schema=True)
@router.get("/", include_in_schema=True)
def get_service_root():
    """Redfish Service Root (/redfish/v1/)."""
    return {
        "@odata.context": "/redfish/v1/$metadata#ServiceRoot.ServiceRoot",
        "@odata.id": "/redfish/v1",
        "@odata.type": "#ServiceRoot.v1_15_0.ServiceRoot",
        "Id": "RootService",
        "Name": "ZettNAS Redfish Service Root",
        "RedfishVersion": "1.15.0",
        "UUID": "e7b0a701-9988-4444-a1a2-589255892500",
        "Product": "ZettNAS Appliance Management Suite",
        "Vendor": "Zettlab",
        "SoftwareVersion": __version__,
        "Systems": {"@odata.id": "/redfish/v1/Systems"},
        "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
        "Storage": {"@odata.id": "/redfish/v1/Storage"},
        "Oem": {
            "ZettLab": {
                "ToolkitVersion": __version__,
                "Architecture": "Universal Hardware & OS Agnostic",
            }
        },
    }


@router.get("/Chassis")
@router.get("/Chassis/")
def list_chassis():
    """Redfish Chassis Collection."""
    return {
        "@odata.context": "/redfish/v1/$metadata#ChassisCollection.ChassisCollection",
        "@odata.id": "/redfish/v1/Chassis",
        "@odata.type": "#ChassisCollection.ChassisCollection",
        "Name": "Chassis Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": "/redfish/v1/Chassis/1"}],
    }


@router.get("/Chassis/1")
@router.get("/Chassis/1/")
def get_chassis_detail():
    """Redfish Chassis/1 Detail."""
    stats = _get_stats()
    chassis_model = stats.get("chassis", "d4")
    model_name = f"Zettlab {chassis_model.upper()} NAS Appliance"

    return {
        "@odata.context": "/redfish/v1/$metadata#Chassis.Chassis",
        "@odata.id": "/redfish/v1/Chassis/1",
        "@odata.type": "#Chassis.v1_22_0.Chassis",
        "Id": "1",
        "Name": model_name,
        "ChassisType": "RackMount" if "u" in chassis_model.lower() else "StandAlone",
        "Manufacturer": "Zettlab",
        "Model": chassis_model.upper(),
        "Status": {
            "State": "Enabled",
            "Health": "OK",
        },
        "PowerState": "On",
        "Thermal": {"@odata.id": "/redfish/v1/Chassis/1/Thermal"},
        "Links": {
            "ComputerSystems": [{"@odata.id": "/redfish/v1/Systems/1"}],
            "Storage": [{"@odata.id": "/redfish/v1/Storage/1"}],
        },
    }


@router.get("/Chassis/1/Thermal")
@router.get("/Chassis/1/Thermal/")
def get_thermal_telemetry():
    """Redfish Chassis/1/Thermal: Fan RPMs and Temperature Sensors."""
    stats = _get_stats()

    # Temperature Sensors
    temps = []

    # CPU Temperature
    cpu = stats.get("cpu", {})
    cpu_temp = cpu.get("temp")
    if cpu_temp is not None:
        temps.append(
            {
                "@odata.id": "/redfish/v1/Chassis/1/Thermal#/Temperatures/CPU",
                "MemberId": "CPU",
                "Name": "CPU Thermal Package",
                "ReadingCelsius": float(cpu_temp),
                "UpperThresholdCritical": 85.0,
                "UpperThresholdFatal": 100.0,
                "Status": {"State": "Enabled", "Health": "OK" if cpu_temp < 80 else "Critical"},
            }
        )

    # Disks & NVMe Temperatures
    for d in stats.get("disks", []):
        dev = d.get("dev") or d.get("name", "disk")
        temp = d.get("temp")
        is_standby = d.get("standby", False)
        is_nvme = "nvme" in dev.lower()
        crit_thresh = 70.0 if is_nvme else 55.0

        temps.append(
            {
                "@odata.id": f"/redfish/v1/Chassis/1/Thermal#/Temperatures/{dev}",
                "MemberId": dev,
                "Name": f"Disk Sensor {dev}",
                "ReadingCelsius": float(temp) if temp is not None else None,
                "UpperThresholdCritical": crit_thresh,
                "Status": {
                    "State": "StandbyOffline" if is_standby else "Enabled",
                    "Health": "OK" if (temp is None or temp < crit_thresh) else "Warning",
                },
            }
        )

    # Fans
    fans_data = []
    fans = stats.get("fans", [])
    for idx, rpm in enumerate(fans):
        fans_data.append(
            {
                "@odata.id": f"/redfish/v1/Chassis/1/Thermal#/Fans/{idx + 1}",
                "MemberId": f"Fan{idx + 1}",
                "Name": f"Chassis Fan {idx + 1}",
                "Reading": int(rpm),
                "ReadingUnits": "RPM",
                "Status": {"State": "Enabled", "Health": "OK"},
            }
        )

    return {
        "@odata.context": "/redfish/v1/$metadata#Thermal.Thermal",
        "@odata.id": "/redfish/v1/Chassis/1/Thermal",
        "@odata.type": "#Thermal.v1_7_2.Thermal",
        "Id": "Thermal",
        "Name": "Thermal Subsystem",
        "Temperatures": temps,
        "Fans": fans_data,
    }


@router.get("/Systems")
@router.get("/Systems/")
def list_systems():
    """Redfish Systems Collection."""
    return {
        "@odata.context": "/redfish/v1/$metadata#ComputerSystemCollection.ComputerSystemCollection",
        "@odata.id": "/redfish/v1/Systems",
        "@odata.type": "#ComputerSystemCollection.ComputerSystemCollection",
        "Name": "Computer System Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": "/redfish/v1/Systems/1"}],
    }


@router.get("/Systems/1")
@router.get("/Systems/1/")
def get_system_detail():
    """Redfish Systems/1 Detail: Compute & Memory Telemetry."""
    stats = _get_stats()
    mem = stats.get("mem", {})
    cpu = stats.get("cpu", {})

    return {
        "@odata.context": "/redfish/v1/$metadata#ComputerSystem.ComputerSystem",
        "@odata.id": "/redfish/v1/Systems/1",
        "@odata.type": "#ComputerSystem.v1_20_0.ComputerSystem",
        "Id": "1",
        "Name": "ZettNAS Host System",
        "SystemType": "Physical",
        "Manufacturer": "Zettlab",
        "Model": stats.get("chassis", "d4").upper(),
        "PowerState": "On",
        "Status": {"State": "Enabled", "Health": "OK"},
        "ProcessorSummary": {
            "Count": 1,
            "Model": "x86_64 Multi-Core Processor",
            "Status": {"State": "Enabled", "Health": "OK"},
        },
        "MemorySummary": {
            "TotalSystemMemoryGiB": float(mem.get("total_gb", 32.0)),
            "Status": {"State": "Enabled", "Health": "OK"},
        },
        "Storage": {"@odata.id": "/redfish/v1/Storage"},
    }


@router.get("/Storage")
@router.get("/Storage/")
def list_storage():
    """Redfish Storage Collection."""
    return {
        "@odata.context": "/redfish/v1/$metadata#StorageCollection.StorageCollection",
        "@odata.id": "/redfish/v1/Storage",
        "@odata.type": "#StorageCollection.StorageCollection",
        "Name": "Storage Subsystem Collection",
        "Members@odata.count": 1,
        "Members": [{"@odata.id": "/redfish/v1/Storage/1"}],
    }


@router.get("/Storage/1")
@router.get("/Storage/1/")
def get_storage_detail():
    """Redfish Storage/1 Detail: Drives & Volumes."""
    stats = _get_stats()
    disks = stats.get("disks", [])

    drives_members = []
    for d in disks:
        dev = d.get("dev") or d.get("name", "disk")
        drives_members.append({"@odata.id": f"/redfish/v1/Storage/1/Drives/{dev}"})

    return {
        "@odata.context": "/redfish/v1/$metadata#Storage.Storage",
        "@odata.id": "/redfish/v1/Storage/1",
        "@odata.type": "#Storage.v1_16_0.Storage",
        "Id": "1",
        "Name": "ZettNAS Storage Array",
        "Status": {"State": "Enabled", "Health": "OK"},
        "Drives@odata.count": len(drives_members),
        "Drives": drives_members,
    }


@router.get("/Storage/1/Drives/{drive_id}")
def get_drive_detail(drive_id: str):
    """Redfish Storage/1/Drives/{drive_id}: Individual Drive Telemetry."""
    stats = _get_stats()
    disks = stats.get("disks", [])

    target = None
    for d in disks:
        dev = d.get("dev") or d.get("name", "")
        if dev.lower() == drive_id.lower():
            target = d
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"Drive {drive_id} not found.")

    is_standby = target.get("standby", False)
    is_nvme = "nvme" in drive_id.lower()

    return {
        "@odata.context": "/redfish/v1/$metadata#Drive.Drive",
        "@odata.id": f"/redfish/v1/Storage/1/Drives/{drive_id}",
        "@odata.type": "#Drive.v1_17_0.Drive",
        "Id": drive_id,
        "Name": f"Physical Drive {drive_id}",
        "MediaType": "SSD" if is_nvme else "HDD",
        "Protocol": "NVMe" if is_nvme else "SATA",
        "CapacityBytes": target.get("size_bytes", 0),
        "Status": {
            "State": "StandbyOffline" if is_standby else "Enabled",
            "Health": "OK" if not target.get("smart_fail") else "Critical",
        },
    }
