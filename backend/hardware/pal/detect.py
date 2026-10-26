"""Which storage platform this host runs (StoragePlatformDetector).

Part of the storage abstraction layer (backend/hardware/pal); split out of pal_storage.py (ARC-5)."""

import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import time
from abc import ABC, abstractmethod
from enum import Enum, StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, POOL_PATH, logger
from backend.fsutil import atomic_write_json
from backend.hardware.pal import base as pal_base
from backend.hardware.pal.base import (
    PlatformType,
)
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status


class StoragePlatformDetector:
    """Detects the underlying NAS host OS and runtime environment."""

    @staticmethod
    def detect() -> PlatformType:
        obs_adapter = os.environ.get("ZETTNAS_OBSERVER_ADAPTER", "").strip().lower()
        if obs_adapter == "auto":
            obs_adapter = ""
        pal_mode = os.environ.get("ZETTNAS_PAL_MODE", "").strip().lower()
        if pal_mode == "auto":
            pal_mode = ""
        env_platform = os.environ.get("ZETTNAS_PLATFORM", "").strip().lower() or obs_adapter or pal_mode
        if env_platform:
            if env_platform in ("unraid",):
                return PlatformType.UNRAID
            if env_platform in ("truenas", "scale"):
                return PlatformType.TRUENAS
            if env_platform in ("proxmox", "pve"):
                return PlatformType.PROXMOX
            if env_platform in ("fygoos", "fyde", "fydeos"):
                return PlatformType.FYGOOS
            if env_platform in ("zettos", "zettlab", "zettlabs"):
                return PlatformType.ZETTOS
            if env_platform in ("ugos", "ugreen"):
                return PlatformType.UGOS
            if env_platform in ("generic_observer", "observer", "readonly", "telemetry"):
                return PlatformType.GENERIC_OBSERVER
            if env_platform in ("generic_linux", "linux"):
                return PlatformType.GENERIC_LINUX

        # 1. Unraid Detection
        if pal_base._find_emhttp_dir() is not None:
            return PlatformType.UNRAID
        ident_candidates = ["/boot/config/ident.cfg", "/host/boot/config/ident.cfg"]
        if any(os.path.isfile(p) for p in ident_candidates):
            return PlatformType.UNRAID

        # 2. ZettOS Detection
        zettos_candidates = [
            "/etc/zettos-release",
            "/host/etc/zettos-release",
            "/etc/zettos/version",
            "/host/etc/zettos/version",
            "/etc/zettos",
            "/host/etc/zettos",
            "/zettos",
            "/host/zettos",
            "/zettlab",
            "/host/zettlab",
        ]
        if any(os.path.isfile(p) or os.path.exists(p) for p in zettos_candidates):
            return PlatformType.ZETTOS

        # Check mount files for ZettOS / Zettlab rootfs signatures
        for m_file in [
            os.path.join(pal_base.HOST_PROC, "1/mounts") if pal_base.HOST_PROC else None,
            os.path.join(pal_base.HOST_PROC, "mounts") if pal_base.HOST_PROC else None,
            "/proc/mounts",
        ]:
            if m_file and os.path.isfile(m_file):
                try:
                    with open(m_file, encoding="utf-8", errors="replace") as f:
                        m_content = f.read()
                        if "upperdir=/zettlab" in m_content or ("/rom" in m_content and "/zettlab" in m_content):
                            return PlatformType.ZETTOS
                        if "/zettos" in m_content:
                            return PlatformType.ZETTOS
                except Exception:
                    logger.debug(
                        "backend.hardware.pal_storage.StoragePlatformDetector.detect: ignored error", exc_info=True
                    )

        # Check kernel cmdline for ZettOS signatures
        for cmd_file in [
            os.path.join(pal_base.HOST_PROC, "cmdline") if pal_base.HOST_PROC else None,
            "/proc/cmdline",
        ]:
            if cmd_file and os.path.isfile(cmd_file):
                try:
                    with open(cmd_file, encoding="utf-8", errors="replace") as f:
                        cmd_text = f.read().lower()
                        if "zettos" in cmd_text or "zettlab" in cmd_text:
                            return PlatformType.ZETTOS
                except Exception:
                    logger.debug(
                        "backend.hardware.pal_storage.StoragePlatformDetector.detect: ignored error", exc_info=True
                    )

        # 3. FygoOS Detection
        fygoos_candidates = [
            "/etc/fygoos-release",
            "/host/etc/fygoos-release",
            "/etc/fyde-release",
            "/host/etc/fyde-release",
            "/var/run/fygoos",
            "/host/var/run/fygoos",
        ]
        if any(os.path.exists(p) for p in fygoos_candidates):
            return PlatformType.FYGOOS

        # 4. UGOS (UGREEN NAS OS) Detection
        ugos_candidates = [
            "/etc/ugos-release",
            "/host/etc/ugos-release",
            "/etc/ugreen",
            "/host/etc/ugreen",
        ]
        if any(os.path.exists(p) for p in ugos_candidates):
            return PlatformType.UGOS

        # 5. Kernel /proc/version checks
        proc_ver_path = os.path.join(pal_base.HOST_PROC, "version")
        if os.path.isfile(proc_ver_path):
            try:
                with open(proc_ver_path, encoding="utf-8", errors="replace") as f:
                    ver_text = f.read().lower()
                    if "unraid" in ver_text:
                        return PlatformType.UNRAID
                    if "zettos" in ver_text:
                        return PlatformType.ZETTOS
                    if "fygoos" in ver_text or "fydeos" in ver_text:
                        return PlatformType.FYGOOS
                    if "ugos" in ver_text or "ugreen" in ver_text:
                        return PlatformType.UGOS
                    if "pve" in ver_text:
                        return PlatformType.PROXMOX
                    if "truenas" in ver_text:
                        return PlatformType.TRUENAS
            except Exception:
                logger.debug(
                    "backend.hardware.pal_storage.StoragePlatformDetector.detect: ignored error", exc_info=True
                )

        # 6. /etc/os-release checks
        os_release_paths = ["/etc/os-release", "/host/etc/os-release"]
        for p in os_release_paths:
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8", errors="replace") as f:
                        text = f.read().lower()
                        if "unraid" in text:
                            return PlatformType.UNRAID
                        if "zettos" in text:
                            return PlatformType.ZETTOS
                        if "fygoos" in text or "fydeos" in text:
                            return PlatformType.FYGOOS
                        if "ugos" in text or "ugreen" in text:
                            return PlatformType.UGOS
                        if "truenas" in text:
                            return PlatformType.TRUENAS
                        if "proxmox" in text:
                            return PlatformType.PROXMOX
                except Exception:
                    logger.debug(
                        "backend.hardware.pal_storage.StoragePlatformDetector.detect: ignored error", exc_info=True
                    )

        # 7. Other Appliance NAS (Synology, QNAP, Asustor, CasaOS) or Observer Mode env
        other_nas_candidates = [
            "/etc/synoinfo.conf",
            "/host/etc/synoinfo.conf",
            "/etc/config/uLinux.conf",
            "/host/etc/config/uLinux.conf",
            "/etc/nas.conf",
            "/host/etc/nas.conf",
            "/etc/casaos",
            "/host/etc/casaos",
        ]
        if any(os.path.exists(p) for p in other_nas_candidates):
            return PlatformType.GENERIC_OBSERVER

        if os.environ.get("ZETTNAS_PAL_MODE", "").strip().lower() in ("observer", "readonly", "telemetry"):
            return PlatformType.GENERIC_OBSERVER
        if os.environ.get("ZETTNAS_OBSERVER_MODE") == "1":
            return PlatformType.GENERIC_OBSERVER

        return PlatformType.GENERIC_LINUX
