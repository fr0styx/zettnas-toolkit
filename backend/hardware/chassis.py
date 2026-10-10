"""
ZettNAS Toolkit - Dynamic Parametric Chassis Engine
Auto-scales across Mini-PCs, Desktop Towers, and Enterprise Rackmounts (1-24 bays),
with persistent user bay slot mapping and Motherboard NVMe twin layout.
"""

import json
import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.config import DATA_DIR, HOST_DEV, HOST_SYS, logger
from backend.fsutil import atomic_write_json
from backend.hardware.hal import DiskDiscoveryHAL, PhysicalDiskRecord
from backend.state import Z_STATE

CHASSIS_MAP_FILE = os.path.join(DATA_DIR, "bay_mapping.json")


class BaySlotMapping(BaseModel):
    slot_index: int = Field(..., ge=1, le=48, description="Physical chassis slot number (1-based)")
    canonical_id: str = Field(..., description="Canonical persistent drive ID or serial")
    custom_label: Optional[str] = Field(default=None, max_length=64)


class ChassisBayMapRequest(BaseModel):
    profile: str = Field(default="auto", pattern=r"^(auto|compact_dual|tower_desktop|rackmount_backplane|custom)$")
    total_bays: Optional[int] = Field(default=None, ge=1, le=48)
    mappings: List[BaySlotMapping] = Field(default_factory=list)


class ChassisEngine:
    """
    Parametric, responsive hardware chassis manager.
    Eliminates fixed D4/D6/D8 assumptions and enables drag-and-drop bay slot mapping.
    """

    @classmethod
    def _read_dmi_field(cls, field: str) -> str:
        for base in (HOST_SYS, "/sys", "/host/sys"):
            dmi_path = os.path.join(base, "class/dmi/id", field)
            if os.path.exists(dmi_path):
                try:
                    with open(dmi_path, "r") as f:
                        return f.read().strip()
                except Exception:
                    pass
        return ""

    @classmethod
    def _read_dmi_product_name(cls) -> str:
        return cls._read_dmi_field("product_name")

    @classmethod
    def _read_dmi_sys_vendor(cls) -> str:
        return cls._read_dmi_field("sys_vendor")

    @classmethod
    def detect_hardware_features(cls) -> Dict[str, Any]:
        """
        Detects whether running platform has custom hardware peripherals:
        Physical LCD Screen, Front Panel COPY Button, SD/TF Card slot, MCU ARGB Lightbar.
        Distinguishes custom appliances (e.g. Zettlab D6U/D8/D4, Aoostar WTR) from generic PCs/servers/VMs.
        """
        vendor = cls._read_dmi_sys_vendor().lower()
        product = cls._read_dmi_product_name().lower()

        # Check for known custom hardware brands / models
        is_custom_appliance = bool(
            "zettlab" in vendor or "aoostar" in vendor or any(k in product for k in ("d4", "d6", "d8", "wtr"))
        )

        # LCD Framebuffer detection
        from backend.config import ENABLE_FB

        has_lcd = bool(
            ENABLE_FB
            and (
                os.path.exists("/dev/fb0")
                or os.path.exists(os.path.join(HOST_DEV, "fb0"))
                or os.path.exists("/host/dev/fb0")
            )
        )

        # MCU / ARGB serial controller
        from backend.hardware.led import find_led_port

        led_port = find_led_port()
        has_mcu = bool(
            led_port is not None
            or os.path.exists("/dev/ttyACM0")
            or os.path.exists(os.path.join(HOST_DEV, "ttyACM0"))
            or os.path.exists("/host/dev/ttyACM0")
        )

        # Physical COPY button
        # On Zettlab appliances it's mapped to MMIO /dev/mem
        has_copy_button = bool(
            is_custom_appliance
            or (
                (os.path.exists("/dev/mem") or os.path.exists(os.path.join(HOST_DEV, "mem")))
                and ("zettlab" in vendor or any(k in product for k in ("d4", "d6", "d8")))
            )
        )

        # SD / TF card slot detection
        has_sd_slot = is_custom_appliance
        if not has_sd_slot:
            try:
                from backend.services.copy_engine import read_media_slots

                slots = read_media_slots()
                if (
                    slots.get("sd", {}).get("dev")
                    or slots.get("sd", {}).get("size", 0) > 0
                    or slots.get("tf", {}).get("dev")
                    or slots.get("tf", {}).get("size", 0) > 0
                ):
                    has_sd_slot = True
            except Exception:
                pass

        # Unified custom hardware flag
        has_custom_hardware = bool(has_lcd or has_mcu or has_copy_button or has_sd_slot or is_custom_appliance)

        return {
            "sys_vendor": cls._read_dmi_sys_vendor(),
            "product_name": cls._read_dmi_product_name(),
            "is_custom_appliance": is_custom_appliance,
            "has_lcd": has_lcd,
            "has_mcu": has_mcu,
            "has_copy_button": has_copy_button,
            "has_sd_slot": has_sd_slot,
            "has_custom_hardware": has_custom_hardware,
        }

    @classmethod
    def load_bay_mapping_config(cls) -> Dict[str, Any]:
        if os.path.exists(CHASSIS_MAP_FILE):
            try:
                with open(CHASSIS_MAP_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.debug(f"[ChassisEngine] Failed reading {CHASSIS_MAP_FILE}: {e}")
        return {"profile": "auto", "total_bays": None, "mappings": []}

    @classmethod
    def get_chassis_status(cls) -> Dict[str, Any]:
        """
        Synthesizes active physical disks, user slot mappings, and hardware chassis status.
        """
        records: List[PhysicalDiskRecord] = DiskDiscoveryHAL.discover_physical_disks()
        hdds = [r for r in records if r.transport != "nvme" and not r.dev_name.startswith("nvme")]
        nvmes = [r for r in records if r.transport == "nvme" or r.dev_name.startswith("nvme")]

        cfg = cls.load_bay_mapping_config()
        configured_profile = cfg.get("profile", "auto")
        configured_total_bays = cfg.get("total_bays")
        user_mappings: List[Dict[str, Any]] = cfg.get("mappings", [])

        # 1. Determine Chassis Profile & Total Bays
        hdd_count = len(hdds)
        if configured_profile != "auto" and configured_profile in (
            "compact_dual",
            "tower_desktop",
            "rackmount_backplane",
            "custom",
        ):
            profile = configured_profile
        else:
            if hdd_count <= 2:
                profile = "compact_dual"
            elif hdd_count <= 6:
                profile = "tower_desktop"
            else:
                profile = "rackmount_backplane"

        if configured_total_bays and configured_total_bays >= 1:
            total_bays = configured_total_bays
        else:
            if profile == "compact_dual":
                total_bays = max(2, hdd_count)
            elif profile == "tower_desktop":
                total_bays = 4 if hdd_count <= 4 else 6
            else:
                total_bays = 8 if hdd_count <= 8 else (12 if hdd_count <= 12 else 24)

        # 2. Determine Friendly Chassis Model Label
        dmi_prod = cls._read_dmi_product_name()
        dmi_lower = dmi_prod.lower()
        if "d8" in dmi_lower:
            chassis_model = "ZETTLAB D8"
        elif "d6" in dmi_lower:
            chassis_model = "ZETTLAB D6"
        elif "d4" in dmi_lower:
            chassis_model = "ZETTLAB D4"
        elif "wtr" in dmi_lower:
            chassis_model = f"AOOSTAR WTR ({dmi_prod})"
        elif profile == "compact_dual":
            chassis_model = f"COMPACT DUAL ({total_bays}-BAY)"
        elif profile == "tower_desktop":
            chassis_model = f"DESKTOP TOWER ({total_bays}-BAY)"
        elif profile == "rackmount_backplane":
            chassis_model = f"ENTERPRISE RACK ({total_bays}-BAY)"
        else:
            chassis_model = f"STORAGE ENCLOSURE ({total_bays}-BAY)"

        # 3. Build Drive Lookup Tables
        disk_by_canonical: Dict[str, PhysicalDiskRecord] = {r.canonical_id: r for r in hdds}
        disk_by_dev: Dict[str, PhysicalDiskRecord] = {r.dev_name: r for r in hdds}
        disk_by_serial: Dict[str, PhysicalDiskRecord] = {
            r.serial: r for r in hdds if r.serial and r.serial != "Unknown"
        }

        # 4. Map Disks to Bays
        slot_map: Dict[int, Dict[str, Any]] = {}
        assigned_canonical: set = set()

        # Apply user mappings first
        for m in user_mappings:
            slot_idx = m.get("slot_index")
            cid = m.get("canonical_id")
            if not slot_idx or not cid:
                continue
            matched_disk = disk_by_canonical.get(cid) or disk_by_dev.get(cid) or disk_by_serial.get(cid)
            if matched_disk:
                slot_map[slot_idx] = {
                    "disk": matched_disk,
                    "custom_label": m.get("custom_label"),
                }
                assigned_canonical.add(matched_disk.canonical_id)

        # Auto-assign remaining disks sequentially to unmapped vacant slots
        unassigned_hdds = [d for d in hdds if d.canonical_id not in assigned_canonical]
        next_unassigned_idx = 0

        bays: List[Dict[str, Any]] = []
        for slot in range(1, total_bays + 1):
            if slot in slot_map:
                entry = slot_map[slot]
                d = entry["disk"]
                custom_label = entry["custom_label"]
            elif next_unassigned_idx < len(unassigned_hdds):
                d = unassigned_hdds[next_unassigned_idx]
                next_unassigned_idx += 1
                custom_label = None
            else:
                d = None
                custom_label = None

            if d:
                cached_temp, cached_health = Z_STATE.cached_smart_data.get(d.dev_name, (None, "ok"))
                is_standby = cached_health == "standby"
                bays.append(
                    {
                        "slot_index": slot,
                        "is_populated": True,
                        "custom_label": custom_label,
                        "disk": {
                            "dev": d.dev_name,
                            "canonical_id": d.canonical_id,
                            "model": d.model,
                            "serial": d.serial,
                            "vendor": d.vendor,
                            "transport": d.transport,
                            "controller_driver": d.controller_driver,
                            "size_bytes": d.size_bytes,
                            "size_formatted": d.size_formatted,
                            "role": d.role,
                            "temp": cached_temp,
                            "health": cached_health,
                            "standby": is_standby,
                            "is_nvme": False,
                        },
                    }
                )
            else:
                bays.append(
                    {
                        "slot_index": slot,
                        "is_populated": False,
                        "custom_label": custom_label,
                        "disk": None,
                    }
                )

        # 5. Motherboard M.2 NVMe Slots
        nvme_slots: List[Dict[str, Any]] = []
        for idx, nv in enumerate(nvmes, start=1):
            cached_temp, cached_health = Z_STATE.cached_smart_data.get(nv.dev_name, (None, "ok"))
            nvme_slots.append(
                {
                    "slot_index": idx,
                    "disk": {
                        "dev": nv.dev_name,
                        "canonical_id": nv.canonical_id,
                        "model": nv.model,
                        "serial": nv.serial,
                        "vendor": nv.vendor,
                        "transport": nv.transport,
                        "controller_driver": nv.controller_driver,
                        "size_bytes": nv.size_bytes,
                        "size_formatted": nv.size_formatted,
                        "role": nv.role,
                        "temp": cached_temp,
                        "health": cached_health,
                        "standby": False,
                        "is_nvme": True,
                    },
                }
            )

        return {
            "profile": profile,
            "total_bays": total_bays,
            "chassis_model": chassis_model,
            "bays": bays,
            "nvme_slots": nvme_slots,
            "available_drives": [
                {
                    "dev": r.dev_name,
                    "canonical_id": r.canonical_id,
                    "model": r.model,
                    "serial": r.serial,
                    "size_formatted": r.size_formatted,
                    "is_rotational": r.is_rotational,
                }
                for r in hdds
            ],
        }

    @classmethod
    def save_bay_mapping(cls, req: ChassisBayMapRequest) -> Dict[str, Any]:
        """
        Persists user custom chassis profile and bay slot ordering.
        """
        payload = {
            "profile": req.profile,
            "total_bays": req.total_bays,
            "mappings": [m.model_dump() for m in req.mappings],
        }
        atomic_write_json(CHASSIS_MAP_FILE, payload)
        return {
            "success": True,
            "message": "Chassis bay mapping updated successfully.",
            "config": payload,
        }
