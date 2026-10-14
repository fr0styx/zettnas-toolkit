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
        prod = cls._read_dmi_field("product_name")
        if not prod:
            try:
                from backend.hardware.storage import _read_dt_text

                prod = _read_dt_text("model")
            except Exception:
                pass
        return prod

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
        board = cls._read_dmi_field("board_name").lower()
        sku = cls._read_dmi_field("product_sku").lower()
        family = cls._read_dmi_field("product_family").lower()

        dt_text = ""
        try:
            from backend.hardware.storage import _read_dt_text

            dt_text = f"{_read_dt_text('model')} {_read_dt_text('compatible')}".lower().strip()
        except Exception:
            pass

        dmi_combined = f"{product} {board} {sku} {family} {vendor} {dt_text}"

        # Check for known custom hardware brands / models
        is_zettlabs = bool(
            "zettlab" in vendor
            or "zettos" in family
            or "zettlab" in dt_text
            or "zettos" in dt_text
            or any(
                k in dmi_combined
                for k in (
                    "wy110",
                    "wy120",
                    "wy140",
                    "d4",
                    "d6",
                    "d6u",
                    "d6 ultra",
                    "d8",
                    "d8u",
                    "zettbox",
                    "zettnas",
                )
            )
        )
        is_ugreen = bool("ugreen" in vendor or any(k in dmi_combined for k in ("dxp", "ugos", "ugreen")))
        is_minisforum = bool("minisforum" in vendor or any(k in dmi_combined for k in ("ms-01", "ms-a1", "minisforum")))
        is_custom_appliance = bool(
            is_zettlabs
            or "aoostar" in vendor
            or any(k in dmi_combined for k in ("wtr", "r1"))
            or is_ugreen
            or is_minisforum
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

        # LCD display resolution & geometry discovery
        display_w, display_h, stride = 640, 172, 704
        if has_lcd:
            for base in (
                os.path.join(HOST_SYS, "class/graphics/fb0") if HOST_SYS else None,
                "/host/sys/class/graphics/fb0",
                "/sys/class/graphics/fb0",
            ):
                if not base or not os.path.exists(base):
                    continue
                v_path = os.path.join(base, "virtual_size")
                s_path = os.path.join(base, "stride")
                if os.path.exists(v_path):
                    try:
                        with open(v_path, "r", encoding="utf-8", errors="replace") as f:
                            parts = [int(x.strip()) for x in f.read().split(",") if x.strip()]
                            if len(parts) == 2 and parts[0] > 0 and parts[1] > 0:
                                display_w, display_h = max(parts), min(parts)
                    except Exception:
                        pass
                if os.path.exists(s_path):
                    try:
                        with open(s_path, "r", encoding="utf-8", errors="replace") as f:
                            s_val = int(f.read().strip())
                            if s_val > 0:
                                stride = s_val
                    except Exception:
                        pass

        lcd_resolution = {
            "width": display_w,
            "height": display_h,
            "stride": stride,
            "spec": f"{display_w} × {display_h} IPS" if has_lcd else "N/A",
        }

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
            "is_zettlabs": is_zettlabs,
            "is_custom_appliance": is_custom_appliance,
            "has_lcd": has_lcd,
            "has_mcu": has_mcu,
            "has_copy_button": has_copy_button,
            "has_sd_slot": has_sd_slot,
            "has_custom_hardware": has_custom_hardware,
            "lcd_resolution": lcd_resolution,
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
        hdds = [
            r
            for r in records
            if r.transport not in ("nvme", "usb", "mmc")
            and not r.dev_name.startswith(("nvme", "mmcblk", "loop", "ram", "zram"))
            and r.role != "os"
            and not r.removable
        ]
        nvmes = [r for r in records if r.transport == "nvme" or r.dev_name.startswith("nvme")]

        cfg = cls.load_bay_mapping_config()
        configured_profile = cfg.get("profile", "auto")
        configured_total_bays = cfg.get("total_bays")
        user_mappings: List[Dict[str, Any]] = cfg.get("mappings", [])

        # 1. Determine Friendly Chassis Model Label & Hardware Brand
        dmi_prod = cls._read_dmi_product_name().lower()
        dmi_board = cls._read_dmi_field("board_name").lower()
        dmi_sku = cls._read_dmi_field("product_sku").lower()
        vendor_lower = cls._read_dmi_sys_vendor().lower()

        raw_prod = cls._read_dmi_product_name()

        dt_model = ""
        try:
            from backend.hardware.storage import _read_dt_text

            dt_model = f"{_read_dt_text('model')} {_read_dt_text('compatible')}".lower().strip()
        except Exception:
            pass

        # Check explicit product name first, then fallback to board/sku/dt
        if (
            "d4" in dmi_prod
            or "wy110" in dmi_prod
            or "wy110" in dt_model
            or ("d4" in dt_model and any(k in dt_model for k in ("zettlab", "rk3588", "rockchip", "zettos")))
        ):
            chassis_model = "ZETTLAB D4"
            friendly_label = "Zettlab D4 (4-Bay)"
        elif (
            "d8" in dmi_prod
            or "wy140" in dmi_prod
            or "wy140" in dt_model
            or ("d8" in dt_model and any(k in dt_model for k in ("zettlab", "rk3588", "rockchip", "zettos")))
        ):
            chassis_model = "ZETTLAB D8"
            friendly_label = "Zettlab D8 Ultra (8-Bay)"
        elif (
            "d6" in dmi_prod
            or "wy120" in dmi_prod
            or "wy120" in dt_model
            or ("d6" in dt_model and any(k in dt_model for k in ("zettlab", "rk3588", "rockchip", "zettos")))
        ):
            chassis_model = "ZETTLAB D6"
            friendly_label = "Zettlab D6 Ultra (6-Bay)"
        elif "wy110" in dmi_board or "wy110" in dmi_sku or "d4" in dmi_board or "d4" in dmi_sku:
            chassis_model = "ZETTLAB D4"
            friendly_label = "Zettlab D4 (4-Bay)"
        elif "wy140" in dmi_board or "wy140" in dmi_sku or "d8" in dmi_board or "d8" in dmi_sku:
            chassis_model = "ZETTLAB D8"
            friendly_label = "Zettlab D8 Ultra (8-Bay)"
        elif "wy120" in dmi_board or "wy120" in dmi_sku or "d6" in dmi_board or "d6" in dmi_sku:
            chassis_model = "ZETTLAB D6"
            friendly_label = "Zettlab D6 Ultra (6-Bay)"
        elif "wtr" in dmi_prod or "aoostar" in vendor_lower:
            chassis_model = f"AOOSTAR WTR ({raw_prod})" if raw_prod else "AOOSTAR WTR"
            friendly_label = chassis_model
        elif "ugreen" in vendor_lower or any(k in f"{dmi_prod} {dmi_board}" for k in ("dxp", "ugreen")):
            chassis_model = f"UGREEN DXP ({raw_prod.upper()})" if raw_prod else "UGREEN DXP"
            friendly_label = chassis_model
        elif "minisforum" in vendor_lower or any(
            k in f"{dmi_prod} {dmi_board}" for k in ("ms-01", "ms-a1", "minisforum")
        ):
            chassis_model = f"MINISFORUM ({raw_prod.upper()})" if raw_prod else "MINISFORUM NAS"
            friendly_label = chassis_model
        else:
            chassis_model = None
            friendly_label = None

        # 2. Determine Profile & Total Bays
        hdd_count = len(hdds)
        if configured_profile != "auto" and configured_profile in (
            "compact_dual",
            "tower_desktop",
            "rackmount_backplane",
            "custom",
        ):
            profile = configured_profile
        else:
            if chassis_model in ("ZETTLAB D4", "ZETTLAB D6", "ZETTLAB D8"):
                profile = "tower_desktop"
            elif hdd_count <= 2:
                profile = "compact_dual"
            elif hdd_count <= 6:
                profile = "tower_desktop"
            else:
                profile = "rackmount_backplane"

        if configured_total_bays and configured_total_bays >= 1:
            total_bays = configured_total_bays
        else:
            if chassis_model == "ZETTLAB D4":
                total_bays = 4
            elif chassis_model == "ZETTLAB D6":
                total_bays = 6
            elif chassis_model == "ZETTLAB D8":
                total_bays = 8
            elif profile == "compact_dual":
                total_bays = max(2, hdd_count)
            elif profile == "tower_desktop":
                total_bays = 4 if hdd_count <= 4 else 6
            else:
                total_bays = 8 if hdd_count <= 8 else (12 if hdd_count <= 12 else 24)

        if not chassis_model:
            if profile == "compact_dual":
                chassis_model = f"COMPACT DUAL ({total_bays}-BAY)"
                friendly_label = chassis_model
            elif profile == "tower_desktop":
                chassis_model = f"DESKTOP TOWER ({total_bays}-BAY)"
                friendly_label = chassis_model
            elif profile == "rackmount_backplane":
                chassis_model = f"ENTERPRISE RACK ({total_bays}-BAY)"
                friendly_label = chassis_model
            else:
                chassis_model = f"STORAGE ENCLOSURE ({total_bays}-BAY)"
                friendly_label = chassis_model

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
            "chassis_label": friendly_label,
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
            "message": "Chassis bay mapping updated successfully",
            "config": payload,
        }

    @classmethod
    def get_appliance_bridge_status(cls) -> Dict[str, Any]:
        """Discovers active hardware bridges for specialized NAS platforms."""
        features = cls.detect_hardware_features()
        vendor = features.get("sys_vendor", "").lower()
        product = features.get("product_name", "").lower()

        is_ugreen = "ugreen" in vendor or "dxp" in product
        is_aoostar = "aoostar" in vendor or "wtr" in product
        is_zettlabs = features.get("is_zettlabs", False)
        is_cwwk = any(k in vendor or k in product for k in ("cwwk", "topton", "nas-"))

        return {
            "appliance_detected": features.get("is_custom_appliance", False),
            "platform_bridges": {
                "zettlabs": {
                    "active": is_zettlabs,
                    "subsystems": ["lcd_fb0", "mcu_argb", "mmio_copy_button"],
                },
                "aoostar": {
                    "active": is_aoostar,
                    "subsystems": ["lcd_portrait", "fan_pwm_dual_zone"],
                },
                "ugreen": {
                    "active": is_ugreen,
                    "subsystems": ["bay_led_indicators", "it87_ec_fan_curves", "pwr_button_monitor"],
                },
                "cwwk_topton": {
                    "active": is_cwwk,
                    "subsystems": ["multi_nic_fans", "superio_nct6775_pwm"],
                },
            },
        }

    @classmethod
    def set_ugreen_bay_led(cls, slot: int, state: str = "on") -> bool:
        """Controls Ugreen DXP front drive bay indicator LEDs via sysfs."""
        val = "1" if state.lower() in ("on", "1", "blink") else "0"
        for base in [HOST_SYS, "/sys", "/host/sys"]:
            if not base or not os.path.exists(base):
                continue
            led_path = os.path.join(base, f"class/leds/ugreen::disk{slot}/brightness")
            if os.path.exists(led_path):
                try:
                    with open(led_path, "w") as f:
                        f.write(f"{val}\n")
                    return True
                except Exception:
                    pass
        return False
